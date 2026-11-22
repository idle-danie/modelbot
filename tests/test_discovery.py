from modelbot.config import CandidatePolicy
from modelbot.discovery import (
    MISSING,
    attach_profiles,
    base_model_id,
    baseline_status,
    find_candidates,
    is_urgent,
    parse_catalog,
)

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
    # Same provider as the baseline is listed first.
    assert ids == ["anthropic.claude-haiku-4-5-20251001-v1:0", "amazon.nova-lite-v1:0"]


def test_denylist():
    catalog = parse_catalog(RESPONSE)
    policy = CandidatePolicy(providers=["amazon", "anthropic"], deny=["amazon.nova-lite-v1:0"])
    assert [m.model_id for m in find_candidates(BASELINE, catalog, policy)] == [
        "anthropic.claude-haiku-4-5-20251001-v1:0"
    ]


PROFILE_ONLY = {
    "modelSummaries": [
        {
            "modelId": "anthropic.claude-sonnet-4-5-20250929-v1:0",
            "providerName": "Anthropic",
            "inferenceTypesSupported": ["INFERENCE_PROFILE"],
        },
        {
            "modelId": "amazon.nova-premier-v1:0",
            "providerName": "Amazon",
            "inferenceTypesSupported": ["INFERENCE_PROFILE"],
        },
    ]
}
PROFILES = [
    {
        "inferenceProfileId": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "models": [
            {"modelArn": "arn:aws:bedrock:::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0"}
        ],
    },
    {
        "inferenceProfileId": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "models": [
            {
                "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0"
            }
        ],
    },
]


def test_profile_only_models_use_geo_profile_and_others_are_dropped():
    catalog = parse_catalog(PROFILE_ONLY)
    attach_profiles(catalog, PROFILES, "us-east-1")
    found = find_candidates(
        "amazon.nova-lite-v1:0", catalog, CandidatePolicy(providers=["anthropic", "amazon"])
    )
    # nova-premier has no profile here, so it is not invocable and is excluded.
    assert [m.invoke_id for m in found] == ["us.anthropic.claude-sonnet-4-5-20250929-v1:0"]


def test_global_profile_fallback():
    catalog = parse_catalog(PROFILE_ONLY)
    attach_profiles(catalog, PROFILES, "eu-west-1")
    assert catalog["anthropic.claude-sonnet-4-5-20250929-v1:0"].invoke_id.startswith("global.")


def test_missing_baseline_is_urgent():
    catalog = parse_catalog(RESPONSE)
    assert baseline_status("us.anthropic.claude-2-v1", catalog) == MISSING
    assert is_urgent("us.anthropic.claude-2-v1", catalog)


TIERED = {
    "modelSummaries": [
        {"modelId": m, "providerName": p, "inputModalities": i}
        for m, p, i in [
            ("anthropic.claude-haiku-4-5", "Anthropic", ["TEXT"]),
            ("anthropic.claude-haiku-5-5", "Anthropic", ["TEXT"]),
            ("anthropic.claude-sonnet-5", "Anthropic", ["TEXT"]),
            ("anthropic.claude-sonnet-5-5", "Anthropic", ["TEXT"]),
            ("amazon.nova-lite-v1:0", "Amazon", ["TEXT"]),
            ("amazon.nova-2-5-sonic", "Amazon", ["SPEECH", "TEXT"]),
        ]
    ]
}


def test_same_tier_newest_first_and_speech_excluded():
    catalog = parse_catalog(TIERED)
    ids = [
        m.model_id
        for m in find_candidates(
            "anthropic.claude-haiku-3", catalog, CandidatePolicy(providers=["anthropic", "amazon"])
        )
    ]
    assert ids == [
        "anthropic.claude-haiku-5-5",
        "anthropic.claude-haiku-4-5",
        "anthropic.claude-sonnet-5-5",
        "anthropic.claude-sonnet-5",
        "amazon.nova-lite-v1:0",
    ]
