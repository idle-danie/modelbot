from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example_dir() -> Path:
    return ROOT / "examples" / "ticket-classifier"
