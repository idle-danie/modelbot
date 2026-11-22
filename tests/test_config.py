import pytest

from modelbot.config import ConfigError, load_config


def test_example_config_loads(example_dir):
    cfg = load_config(example_dir / "modelbot.yaml")
    assert cfg.targets[0].key == "llm.model_id"
    assert cfg.candidates.providers == ["anthropic", "amazon"]


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_key_and_pattern_are_exclusive(tmp_path):
    p = tmp_path / "modelbot.yaml"
    p.write_text(
        "candidates: {providers: [amazon]}\n"
        "targets:\n"
        "  - {name: t, file: f, key: a.b, pattern: 'x', prompts: [p], evals: e}\n"
    )
    with pytest.raises(ConfigError, match="targets.0"):
        load_config(p)


def test_error_names_field(tmp_path):
    p = tmp_path / "modelbot.yaml"
    p.write_text("budget_usd: -1\ncandidates: {providers: [amazon]}\ntargets: []\n")
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "budget_usd" in str(e.value) and "targets" in str(e.value)
