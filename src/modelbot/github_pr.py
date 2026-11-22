"""File rewriting and pull request creation (Requirement 7.3–7.5).

Changes are committed through the GitHub contents API on a dedicated branch, so modelbot never touches the
local working tree and works the same locally and inside GitHub Actions.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modelbot.config import Target


@dataclass(frozen=True)
class FileChange:
    path: str  # repository-relative, POSIX separators
    content: str


def branch_name(target: str, candidate: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9-]+", "-", candidate).strip("-")
    return f"modelbot/{target}/{slug}"


def pr_title(target: str, old: str, new: str) -> str:
    return f"modelbot({target}): {old} → {new}"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def repo_root(start: Path) -> Path:
    return Path(_git(start, "rev-parse", "--show-toplevel"))


def rewrite_model_id(text: str, target: Target, old: str, new: str) -> str:
    """Replace the model ID in a target file, preserving everything else (task 8.3)."""
    if target.pattern:
        m = re.search(target.pattern, text)
        if not m or m.group(1) != old:
            raise ValueError(f"pattern for {target.name} no longer matches {old!r}")
        return text[: m.start(1)] + new + text[m.end(1) :]
    # Key targets: replace the literal value. Refuse if it is ambiguous rather than guess.
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{target.file}: expected exactly one occurrence of {old!r}, found {count}")
    return text.replace(old, new)


def plan_changes(
    config_dir: Path, target: Target, old: str, new: str, ported_prompt: str | None, root: Path | None = None
) -> list[FileChange]:
    root = root or repo_root(config_dir)

    def rel(p: Path) -> str:
        return p.resolve().relative_to(root.resolve()).as_posix()

    model_file = config_dir / target.file
    changes = [FileChange(rel(model_file), rewrite_model_id(model_file.read_text(), target, old, new))]
    if ported_prompt is not None:
        if len(target.prompts) != 1:
            raise ValueError(
                f"{target.name}: ported prompts can only be written back to a single prompt file"
            )
        changes.append(FileChange(rel(config_dir / target.prompts[0]), ported_prompt.rstrip() + "\n"))
    return changes


def connect(config_dir: Path) -> Any:
    """PyGithub repository for this checkout, using GITHUB_TOKEN / GH_TOKEN or the gh CLI login."""
    from github import Auth, Github

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        token = subprocess.run(
            ["gh", "auth", "token"], check=True, capture_output=True, text=True
        ).stdout.strip()
    full_name = os.environ.get("GITHUB_REPOSITORY")
    if not full_name:
        url = _git(config_dir, "remote", "get-url", "origin")
        m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
        if not m:
            raise ValueError(f"cannot determine GitHub repository from remote {url!r}")
        full_name = m.group(1)
    return Github(auth=Auth.Token(token)).get_repo(full_name)


def open_or_update_pr(
    repo: Any, *, branch: str, title: str, body: str, changes: list[FileChange], base: str | None = None
) -> str:
    """Create the branch and PR, or update both if a modelbot PR is already open (R7.3, R7.4)."""
    from github import GithubException

    base = base or repo.default_branch
    open_prs = list(repo.get_pulls(state="open", head=f"{repo.owner.login}:{branch}"))
    if not open_prs:
        try:
            repo.create_git_ref(f"refs/heads/{branch}", repo.get_branch(base).commit.sha)
        except GithubException as e:
            if e.status != 422:  # 422: branch already exists (e.g. a previously closed PR)
                raise
    for ch in changes:
        current = repo.get_contents(ch.path, ref=branch)
        if current.decoded_content.decode() != ch.content:
            repo.update_file(ch.path, f"{title}\n\nUpdate {ch.path}", ch.content, current.sha, branch=branch)
    if open_prs:
        pr = open_prs[0]
        pr.edit(title=title, body=body)
    else:
        pr = repo.create_pull(title=title, body=body, head=branch, base=base)
    close_superseded(repo, branch, pr)
    return pr.html_url


def close_superseded(repo: Any, branch: str, current: Any) -> list[int]:
    """Close other open modelbot PRs for the same target, like Dependabot does for newer versions."""
    target_prefix = branch.rsplit("/", 1)[0] + "/"
    closed = []
    for pr in repo.get_pulls(state="open"):
        head = pr.head.ref
        if head.startswith(target_prefix) and head != branch:
            pr.create_issue_comment(
                f"Superseded by #{current.number}: modelbot now recommends a different model."
            )
            pr.edit(state="closed")
            closed.append(pr.number)
    return closed
