"""File rewriting and pull request creation (Requirement 7.3–7.5)."""

from __future__ import annotations


def branch_name(target: str, candidate: str) -> str:
    slug = candidate.replace(":", "-").replace(".", "-").replace("/", "-")
    return f"modelbot/{target}/{slug}"


def open_or_update_pr(*args, **kwargs) -> str:
    # TODO(task 8.3): rewrite model IDs (key path or regex) and accepted prompts.
    # TODO(task 8.4): PyGithub — find open PR for branch_name(); update it, else create one.
    raise NotImplementedError("PR creation is not implemented yet (tasks 8.3–8.4)")
