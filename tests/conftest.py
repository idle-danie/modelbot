import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PINNED_BASELINE = "us.anthropic.claude-3-5-haiku-20241022-v1:0"


@pytest.fixture
def example_dir(tmp_path) -> Path:
    """A copy of the ticket-classifier example with the baseline pinned.

    The real example is upgraded by modelbot's own pull requests, so tests must not depend on whichever model
    it currently points at.
    """
    dst = tmp_path / "ticket-classifier"
    shutil.copytree(ROOT / "examples" / "ticket-classifier", dst)
    (dst / "app" / "config.yaml").write_text(f"llm:\n  model_id: {PINNED_BASELINE}\n  temperature: 0\n")
    return dst
