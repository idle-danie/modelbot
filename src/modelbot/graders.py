"""Grader registry (Requirement 4)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jsonschema


@dataclass(frozen=True)
class GraderResult:
    name: str
    passed: bool
    detail: str = ""


Grader = Callable[[str, dict[str, Any]], GraderResult]
_REGISTRY: dict[str, Grader] = {}


def register(name: str) -> Callable[[Grader], Grader]:
    def deco(fn: Grader) -> Grader:
        _REGISTRY[name] = fn
        return fn

    return deco


def get(name: str) -> Grader:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown grader '{name}'; available: {sorted(_REGISTRY)}") from None


@register("exact")
def exact(output: str, spec: dict[str, Any]) -> GraderResult:
    ok = output.strip() == str(spec["value"]).strip()
    return GraderResult("exact", ok, "" if ok else f"expected {spec['value']!r}")


@register("contains")
def contains(output: str, spec: dict[str, Any]) -> GraderResult:
    needle = str(spec["value"])
    hay = output if spec.get("case_sensitive", False) else output.lower()
    ok = (needle if spec.get("case_sensitive", False) else needle.lower()) in hay
    return GraderResult("contains", ok, "" if ok else f"missing {needle!r}")


@register("regex")
def regex(output: str, spec: dict[str, Any]) -> GraderResult:
    ok = re.search(spec["pattern"], output) is not None
    return GraderResult("regex", ok, "" if ok else f"no match for /{spec['pattern']}/")


@register("json_schema")
def json_schema(output: str, spec: dict[str, Any]) -> GraderResult:
    text = output.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        jsonschema.validate(json.loads(text), spec["schema"])
    except (json.JSONDecodeError, jsonschema.ValidationError) as e:
        return GraderResult("json_schema", False, str(e).splitlines()[0])
    return GraderResult("json_schema", True)


# TODO(task 5.2): register("llm_judge") — score against spec["rubric"] with the pinned judge model.
