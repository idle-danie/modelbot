from modelbot.config import CandidatePolicy
from modelbot.discovery import base_model_id, find_candidates, is_urgent, parse_catalog

RESPONSE = {
    "modelSummaries": [
        {
            "modelId": "anthropic.claude-3-5-haiku-20241022-v1:0",
            "providerName": "Anthropic",
            "modelLifecycle": {"status": "LEGACY"},
            "inputModalities": ["TEXT"],
        },
        {
            "modelId": "anthropic.claude-haiku-4-5-20251001-v1:0",
            "providerName": "Anthropic",
            "modelLifecycle": {"status": "ACTIVE"},
            "inputModalities": ["TEXT", "IMAGE"],
        },
        {
            "modelId": "amazon.nova-lite-v1:0",
            "providerName": "Amazon",
            "modelLifecycle": {"status": "ACTIVE"},
            "inputModalities": ["TEXT", "IMAGE"],
        },
        {
            "modelId": "meta.llama3-70b-instruct-v1:0",
            "providerName": "Meta",
            "modelLifecycle": {"status": "ACTIVE"},
            "inputModalities": ["TEXT"],
        },
    ]
}
BASELINE = "us.anthropic.claude-3-5-haiku-20241022-v1:0"


def test_profile_prefix_stripped():
    assert base_model_id(BASELINE) == "anthropic.claude-3-5-haiku-20241022-v1:0"
    assert base_model_id("amazon.nova-lite-v1:0") == "amazon.nova-lite-v1:0"


def test_legacy_baseline_is_urgent():
    assert is_urgent(BASELINE, parse_catalog(RESPONSE))


def test_candidates_respect_policy():
    catalog = parse_catalog(RESPONSE)
    policy = CandidatePolicy(providers=["anthropic", "amazon"])
    ids = [m.model_id for m in find_candidates(BASELINE, catalog, policy)]
    assert ids == ["amazon.nova-lite-v1:0", "anthropic.claude-haiku-4-5-20251001-v1:0"]


def test_denylist():
    catalog = parse_catalog(RESPONSE)
    policy = CandidatePolicy(providers=["amazon", "anthropic"], deny=["amazon.nova-lite-v1:0"])
    assert [m.model_id for m in find_candidates(BASELINE, catalog, policy)] == [
        "anthropic.claude-haiku-4-5-20251001-v1:0"
    ]
