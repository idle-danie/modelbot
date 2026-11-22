"""modelbot.yaml schema and loader (Requirement 1)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator


class ConfigError(Exception):
    """Raised when modelbot.yaml is missing or invalid."""


class CandidatePolicy(BaseModel):
    providers: list[str] = Field(min_length=1)
    deny: list[str] = Field(default_factory=list)


class PortingPolicy(BaseModel):
    enabled: bool = True
    margin: float = Field(0.10, ge=0, le=1)
    max_iterations: int = Field(3, ge=1, le=10)
    max_regressions: int = Field(1, ge=0)


class Limits(BaseModel):
    max_cost_ratio: float = Field(1.5, gt=0)
    max_p95_ratio: float = Field(1.5, gt=0)


class Target(BaseModel):
    name: str
    file: str
    key: str | None = None
    pattern: str | None = None
    prompts: list[str] = Field(min_length=1)
    evals: str
    threshold: float = Field(0.9, ge=0, le=1)
    tolerance: float = Field(0.02, ge=0, le=1)
    porting: PortingPolicy = Field(default_factory=PortingPolicy)
    limits: Limits = Field(default_factory=Limits)

    @model_validator(mode="after")
    def _key_xor_pattern(self) -> Target:
        if (self.key is None) == (self.pattern is None):
            raise ValueError("exactly one of 'key' or 'pattern' must be set")
        return self


class Config(BaseModel):
    region: str = "us-east-1"
    budget_usd: float = Field(5.0, gt=0)
    concurrency: int = Field(4, ge=1, le=64)
    judge_model: str | None = None
    porting_model: str | None = None
    candidates: CandidatePolicy
    targets: list[Target] = Field(min_length=1)


def _format_error(err: ValidationError) -> str:
    lines = []
    for e in err.errors():
        path = ".".join(str(p) for p in e["loc"]) or "<root>"
        lines.append(f"  {path}: {e['msg']}")
    return "invalid modelbot.yaml:\n" + "\n".join(lines)


def load_config(path: str | Path = "modelbot.yaml") -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
        return Config.model_validate(raw)
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {path}: {e}") from e
    except ValidationError as e:
        raise ConfigError(_format_error(e)) from e
