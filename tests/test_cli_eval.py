"""End-to-end `modelbot eval` on the example project with a fake boto3 (no AWS calls)."""

import json
import sys
import types

from typer.testing import CliRunner

from modelbot.cli import app

CATALOG = {
    "modelSummaries": [
        {
            "modelId": "anthropic.claude-3-5-haiku-20241022-v1:0",
            "providerName": "Anthropic",
            "modelLifecycle": {"status": "LEGACY"},
            "inferenceTypesSupported": ["INFERENCE_PROFILE"],
        },
        {
            "modelId": "amazon.nova-lite-v1:0",
            "providerName": "Amazon",
            "modelLifecycle": {"status": "ACTIVE"},
            "inferenceTypesSupported": ["ON_DEMAND"],
        },
    ]
}

ANSWERS = {  # case id -> (category, urgent)
    "billing-01": ("billing", True),
    "billing-02": ("billing", False),
    "bug-01": ("bug", True),
    "bug-02": ("bug", False),
    "account-01": ("account", True),
    "account-02": ("account", False),
    "feature-01": ("feature_request", False),
    "feature-02": ("feature_request", False),
    "other-01": ("other", False),
    "tricky-01": ("billing", False),
    "tricky-02": ("billing", True),
    "tricky-03": ("other", False),
}


def make_boto3(example_dir):
    inputs = {}
    for line in (example_dir / "evals" / "cases.jsonl").read_text().splitlines():
        d = json.loads(line)
        inputs[d["input"]] = d["id"]

    class Bedrock:
        def list_foundation_models(self, **_):
            return CATALOG

        def list_inference_profiles(self, **_):
            return {"inferenceProfileSummaries": []}

    class Runtime:
        def converse(self, modelId, messages, **_):
            case_id = inputs[messages[0]["content"][0]["text"]]
            cat, urgent = ANSWERS[case_id]
            if "haiku" in modelId and case_id == "tricky-03":
                cat = "poem"  # the old model falls for the prompt injection
            text = json.dumps({"category": cat, "urgent": urgent})
            return {
                "output": {"message": {"content": [{"text": text}]}},
                "usage": {"inputTokens": 200, "outputTokens": 20},
                "metrics": {"latencyMs": 300},
            }

    return types.SimpleNamespace(client=lambda name, **_: Bedrock() if name == "bedrock" else Runtime())


def test_eval_recommends_upgrade_from_legacy_model(example_dir, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", make_boto3(example_dir))
    out = tmp_path / "report.md"
    result = CliRunner().invoke(app, ["eval", "-c", str(example_dir / "modelbot.yaml"), "-o", str(out)])
    assert result.exit_code == 0, result.output
    md = out.read_text()
    assert "LEGACY" in md
    assert "→ `amazon.nova-lite-v1:0`" in md
    assert "92%" in md and "100%" in md
