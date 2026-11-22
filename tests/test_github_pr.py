from types import SimpleNamespace

import pytest

from modelbot.config import Target
from modelbot.github_pr import branch_name, open_or_update_pr, plan_changes, rewrite_model_id

OLD, NEW = "us.anthropic.claude-3-5-haiku-20241022-v1:0", "amazon.nova-micro-v1:0"


def target(**kw):
    base = dict(name="t", file="app/config.yaml", prompts=["prompts/p.md"], evals="e.jsonl")
    return Target(**{**base, **kw})


def test_rewrite_key_target_preserves_formatting():
    text = f"llm:\n  model_id: {OLD}   # pinned\n  temperature: 0\n"
    out = rewrite_model_id(text, target(key="llm.model_id"), OLD, NEW)
    assert out == f"llm:\n  model_id: {NEW}   # pinned\n  temperature: 0\n"


def test_rewrite_refuses_ambiguous_key_target():
    with pytest.raises(ValueError, match="exactly one"):
        rewrite_model_id(f"a: {OLD}\nb: {OLD}\n", target(key="a"), OLD, NEW)


def test_rewrite_pattern_target():
    text = f'MODEL_ID = "{OLD}"\nOTHER = "{OLD}"\n'
    out = rewrite_model_id(text, target(file="s.py", pattern=r'MODEL_ID = "([^"]+)"'), OLD, NEW)
    assert out == f'MODEL_ID = "{NEW}"\nOTHER = "{OLD}"\n'


def test_plan_changes_includes_ported_prompt(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "prompts").mkdir()
    (tmp_path / "app/config.yaml").write_text(f"llm:\n  model_id: {OLD}\n")
    (tmp_path / "prompts/p.md").write_text("old prompt\n")
    changes = plan_changes(tmp_path, target(key="llm.model_id"), OLD, NEW, "new prompt", root=tmp_path)
    assert [c.path for c in changes] == ["app/config.yaml", "prompts/p.md"]
    assert changes[1].content == "new prompt\n"


def test_branch_name_is_ref_safe():
    assert branch_name("ticket", OLD) == "modelbot/ticket/us-anthropic-claude-3-5-haiku-20241022-v1-0"


class FakePR:
    def __init__(self, number, title, body, branch):
        self.number, self.title, self.body, self.state = number, title, body, "open"
        self.head = SimpleNamespace(ref=branch)
        self.html_url = f"https://x/pull/{number}"
        self.comments: list[str] = []

    def edit(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def create_issue_comment(self, text):
        self.comments.append(text)


class FakeRepo:
    """The subset of PyGithub's Repository that github_pr uses."""

    default_branch = "main"
    owner = SimpleNamespace(login="me")

    def __init__(self):
        self.files = {"app/config.yaml": "old"}
        self.branch_files: dict[str, dict[str, str]] = {}
        self.prs: list[FakePR] = []
        self.commits = 0

    def get_pulls(self, state, head=None):
        return [p for p in self.prs if p.state == state and (head is None or f"me:{p.head.ref}" == head)]

    def get_branch(self, name):
        return SimpleNamespace(commit=SimpleNamespace(sha="abc"))

    def create_git_ref(self, ref, sha):
        self.branch_files[ref.removeprefix("refs/heads/")] = dict(self.files)

    def get_contents(self, path, ref):
        content = self.branch_files[ref][path]
        return SimpleNamespace(decoded_content=content.encode(), sha=f"sha-{content}")

    def update_file(self, path, message, content, sha, branch):
        self.branch_files[branch][path] = content
        self.commits += 1

    def create_pull(self, title, body, head, base):
        pr = FakePR(len(self.prs) + 1, title, body, head)
        self.prs.append(pr)
        return pr


def test_open_then_update_without_duplicate_pr():
    from modelbot.github_pr import FileChange

    repo = FakeRepo()
    ch = [FileChange("app/config.yaml", "new")]
    url1 = open_or_update_pr(repo, branch="modelbot/t/x", title="t1", body="b1", changes=ch)
    url2 = open_or_update_pr(repo, branch="modelbot/t/x", title="t2", body="b2", changes=ch)
    assert url1 == url2 and len(repo.prs) == 1
    assert repo.prs[0].body == "b2"
    assert repo.commits == 1  # unchanged content is not re-committed


def test_new_recommendation_closes_superseded_pr_for_same_target_only():
    from modelbot.github_pr import FileChange

    repo = FakeRepo()
    ch = [FileChange("app/config.yaml", "new")]
    open_or_update_pr(repo, branch="modelbot/t/model-a", title="a", body="a", changes=ch)
    open_or_update_pr(repo, branch="modelbot/other/model-a", title="o", body="o", changes=ch)
    open_or_update_pr(repo, branch="modelbot/t/model-b", title="b", body="b", changes=ch)
    states = {p.head.ref: p.state for p in repo.prs}
    assert states == {
        "modelbot/t/model-a": "closed",
        "modelbot/other/model-a": "open",
        "modelbot/t/model-b": "open",
    }
    assert repo.prs[0].comments == ["Superseded by #3: modelbot now recommends a different model."]
