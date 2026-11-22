"""Per-token pricing and budget tracking (Requirement 3.5, design D5)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import yaml

from modelbot.discovery import base_model_id

DEFAULT_TABLE = Path(__file__).with_name("prices.yaml")


@dataclass(frozen=True)
class Price:
    input_per_1m: float
    output_per_1m: float


def load_prices(path: str | Path = DEFAULT_TABLE, override: str | Path | None = None) -> dict[str, Price]:
    """Load the bundled table, then let an optional override file add or replace entries."""
    prices: dict[str, Price] = {}
    for p in (path, override):
        if p is not None:
            raw = yaml.safe_load(Path(p).read_text()) or {}
            prices.update({base_model_id(k): Price(**v) for k, v in raw.get("models", {}).items()})
    return prices


def has_price(prices: dict[str, Price], model_id: str) -> bool:
    return base_model_id(model_id) in prices


def cost_usd(prices: dict[str, Price], model_id: str, input_tokens: int, output_tokens: int) -> float:
    price = prices.get(base_model_id(model_id))
    if price is None:
        raise KeyError(f"no price for {model_id}; add it to prices.yaml or your override file")
    return (input_tokens * price.input_per_1m + output_tokens * price.output_per_1m) / 1_000_000


class BudgetTracker:
    """Thread-safe running total of estimated spend.

    Never raises: callers check `exhausted` before issuing new requests, so in-flight requests finish and
    their results are kept (Requirement 3.5).
    """

    def __init__(self, cap_usd: float):
        self.cap_usd = cap_usd
        self.spent_usd = 0.0
        self.requests = 0
        self._lock = threading.Lock()

    def add(self, amount: float) -> None:
        with self._lock:
            self.spent_usd += amount
            self.requests += 1

    @property
    def exhausted(self) -> bool:
        return self.spent_usd >= self.cap_usd
