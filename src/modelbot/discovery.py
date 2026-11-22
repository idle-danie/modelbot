"""Bedrock model catalog and candidate selection (Requirement 2)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from modelbot.config import CandidatePolicy

LEGACY = "LEGACY"
MISSING = "MISSING"  # not listed in the region's catalog any more: likely end-of-life
# Speech-to-speech models need the bidirectional streaming API, not Converse.
_UNSUPPORTED_INPUTS = {"SPEECH"}
# Tier words used to prefer like-for-like upgrades (haiku -> haiku, lite -> lite).
_TIERS = ("haiku", "sonnet", "opus", "fable", "micro", "lite", "pro", "premier")
# Cross-region inference profile prefixes, e.g. "us.anthropic.claude-...".
_PROFILE_PREFIXES = ("us.", "eu.", "apac.", "global.")


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    provider: str
    lifecycle: str = "ACTIVE"
    input_modalities: tuple[str, ...] = ("TEXT",)
    output_modalities: tuple[str, ...] = ("TEXT",)
    inference_types: tuple[str, ...] = ("ON_DEMAND",)
    # ID to pass to Converse: the model ID itself, or an inference profile for models without on-demand.
    invoke_id: str = ""

    def __post_init__(self) -> None:
        if not self.invoke_id:
            object.__setattr__(self, "invoke_id", self.model_id)


@dataclass
class ScanResult:
    target: str
    baseline: str
    urgent: bool
    status: str = "ACTIVE"
    candidates: list[ModelInfo] = field(default_factory=list)


def base_model_id(model_id: str) -> str:
    """Strip a cross-region inference profile prefix so profiles map to catalog entries."""
    for prefix in _PROFILE_PREFIXES:
        if model_id.startswith(prefix):
            return model_id[len(prefix) :]
    return model_id


def parse_catalog(response: dict[str, Any]) -> dict[str, ModelInfo]:
    """Parse a ListFoundationModels response into {model_id: ModelInfo}."""
    catalog: dict[str, ModelInfo] = {}
    for s in response.get("modelSummaries", []):
        info = ModelInfo(
            model_id=s["modelId"],
            provider=s.get("providerName", "").lower(),
            lifecycle=s.get("modelLifecycle", {}).get("status", "ACTIVE"),
            input_modalities=tuple(s.get("inputModalities", ["TEXT"])),
            output_modalities=tuple(s.get("outputModalities", ["TEXT"])),
            inference_types=tuple(s.get("inferenceTypesSupported", ["ON_DEMAND"])),
        )
        catalog[info.model_id] = info
    return catalog


def _region_prefix(region: str) -> str:
    geo = region.split("-")[0]
    return {"ap": "apac."}.get(geo, f"{geo}.")


def attach_profiles(catalog: dict[str, ModelInfo], profiles: list[dict[str, Any]], region: str) -> None:
    """Point models without on-demand support at a system-defined inference profile.

    Prefers the geographic profile for the region (data stays in-geo), then falls back to `global.`.
    """
    by_model: dict[str, list[str]] = {}
    for prof in profiles:
        for m in prof.get("models", []):
            model_id = m["modelArn"].rsplit("/", 1)[-1]
            by_model.setdefault(model_id, []).append(prof["inferenceProfileId"])
    preferred = (_region_prefix(region), "global.")
    for model_id, info in list(catalog.items()):
        if "ON_DEMAND" in info.inference_types:
            continue
        options = by_model.get(model_id, [])
        for prefix in preferred:
            match = next((o for o in options if o.startswith(prefix)), None)
            if match:
                catalog[model_id] = replace(info, invoke_id=match)
                break


def _paginate(call: Any, key: str, **kwargs: Any) -> list[dict[str, Any]]:
    items, token = [], None
    while True:
        resp = call(**kwargs, **({"nextToken": token} if token else {}))
        items += resp.get(key, [])
        token = resp.get("nextToken")
        if not token:
            return items


def fetch_catalog(bedrock_client: Any, region: str) -> dict[str, ModelInfo]:
    catalog = parse_catalog(bedrock_client.list_foundation_models(byOutputModality="TEXT"))
    profiles = _paginate(
        bedrock_client.list_inference_profiles, "inferenceProfileSummaries", typeEquals="SYSTEM_DEFINED"
    )
    attach_profiles(catalog, profiles, region)
    return catalog


def invocable(info: ModelInfo) -> bool:
    """False when the model has neither on-demand throughput nor a matching inference profile."""
    return "ON_DEMAND" in info.inference_types or info.invoke_id != info.model_id


def baseline_status(baseline: str, catalog: dict[str, ModelInfo]) -> str:
    info = catalog.get(base_model_id(baseline))
    return MISSING if info is None else info.lifecycle


def is_urgent(baseline: str, catalog: dict[str, ModelInfo]) -> bool:
    return baseline_status(baseline, catalog) in (LEGACY, MISSING)


def tier(model_id: str) -> str | None:
    return next((t for t in _TIERS if f"-{t}" in model_id or f".{t}" in model_id), None)


def find_candidates(baseline: str, catalog: dict[str, ModelInfo], policy: CandidatePolicy) -> list[ModelInfo]:
    base = base_model_id(baseline)
    needed = catalog[base].input_modalities if base in catalog else ("TEXT",)
    allowed = {p.lower() for p in policy.providers}
    denied = {base_model_id(d) for d in policy.deny}
    eligible = [
        m
        for m in catalog.values()
        if m.model_id != base
        and m.provider in allowed
        and m.model_id not in denied
        and m.lifecycle != LEGACY
        and invocable(m)
        and not _UNSUPPORTED_INPUTS & set(m.input_modalities)
        and set(needed) <= set(m.input_modalities)
    ]
    # Newest-looking IDs first, then (stable sort) same provider and same tier as the baseline first.
    eligible.sort(key=lambda m: m.model_id, reverse=True)
    base_provider = catalog[base].provider if base in catalog else base.split(".", 1)[0]
    base_tier = tier(base)
    eligible.sort(
        key=lambda m: (m.provider != base_provider, base_tier is None or tier(m.model_id) != base_tier)
    )
    return eligible
