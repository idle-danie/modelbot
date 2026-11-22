"""Per-token pricing and budget tracking (Requirement 3.5, design D5)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import yaml

from modelbot.discovery import base_model_id

DEFAULT_TABLE = Path(__file__).with_name("prices.yaml")


class BudgetExceeded(Exception):
    pass


@dataclass(frozen=True)
class Price:
    input_per_1m: float
    output_per_1m: float


def load_prices(path: str | Path = DEFAULT_TABLE) -> dict[str, Price]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return {k: Price(**v) for k, v in raw.get("models", {}).items()}


def cost_usd(prices: dict[str, Price], model_id: str, input_tokens: int, output_tokens: int) -> float:
    price = prices.get(base_model_id(model_id))
    if price is None:
        raise KeyError(f"no price for {model_id}; add it to prices.yaml or your override file")
    return (input_tokens * price.input_per_1m + output_tokens * price.output_per_1m) / 1_000_000


class BudgetTracker:
    """Thread-safe running total; raises once the cap is reached."""

    def __init__(self, cap_usd: float):
        self.cap_usd = cap_usd
        self.spent_usd = 0.0
        self._lock = threading.Lock()

    def add(self, amount: float) -> None:
        with self._lock:
            self.spent_usd += amount
            if self.spent_usd >= self.cap_usd:
                raise BudgetExceeded(f"spent ${self.spent_usd:.4f} of ${self.cap_usd:.2f} budget")
