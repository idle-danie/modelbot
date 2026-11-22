"""Bedrock model catalog and candidate selection (Requirement 2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from modelbot.config import CandidatePolicy

LEGACY = "LEGACY"
# Cross-region inference profile prefixes, e.g. "us.anthropic.claude-...".
_PROFILE_PREFIXES = ("us.", "eu.", "apac.", "global.")


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    provider: str
    lifecycle: str = "ACTIVE"
    input_modalities: tuple[str, ...] = ("TEXT",)
    output_modalities: tuple[str, ...] = ("TEXT",)


@dataclass
class ScanResult:
    target: str
    baseline: str
    urgent: bool
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
        )
        catalog[info.model_id] = info
    return catalog


def fetch_catalog(bedrock_client: Any) -> dict[str, ModelInfo]:
    # TODO(task 3.2): merge ListInferenceProfiles so profile IDs are first-class candidates.
    return parse_catalog(bedrock_client.list_foundation_models(byOutputModality="TEXT"))


def is_urgent(baseline: str, catalog: dict[str, ModelInfo]) -> bool:
    info = catalog.get(base_model_id(baseline))
    return info is not None and info.lifecycle == LEGACY


def find_candidates(baseline: str, catalog: dict[str, ModelInfo], policy: CandidatePolicy) -> list[ModelInfo]:
    base = base_model_id(baseline)
    needed = catalog[base].input_modalities if base in catalog else ("TEXT",)
    allowed = {p.lower() for p in policy.providers}
    denied = {base_model_id(d) for d in policy.deny}
    return sorted(
        (
            m
            for m in catalog.values()
            if m.model_id != base
            and m.provider in allowed
            and m.model_id not in denied
            and m.lifecycle != LEGACY
            and set(needed) <= set(m.input_modalities)
        ),
        key=lambda m: m.model_id,
    )
