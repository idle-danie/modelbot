from modelbot import graders


def test_exact_and_contains():
    assert graders.get("exact")(" bug ", {"value": "bug"}).passed
    assert graders.get("contains")("Category: BUG", {"value": "bug"}).passed
    assert not graders.get("contains")("Category: BUG", {"value": "bug", "case_sensitive": True}).passed


def test_regex():
    assert graders.get("regex")("ticket #123", {"pattern": r"#\d+"}).passed


def test_json_schema_accepts_fenced_json():
    schema = {"type": "object", "properties": {"category": {"const": "bug"}}, "required": ["category"]}
    out = '```json\n{"category": "bug"}\n```'
    assert graders.get("json_schema")(out, {"schema": schema}).passed


def test_json_schema_reports_failure():
    schema = {"type": "object", "properties": {"category": {"const": "bug"}}}
    r = graders.get("json_schema")('{"category": "billing"}', {"schema": schema})
    assert not r.passed and r.detail
