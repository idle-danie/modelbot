"""modelbot CLI (Requirement 8.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from modelbot import discovery
from modelbot.config import ConfigError, load_config

app = typer.Typer(help="Dependabot for LLMs: eval-gated model upgrades on Amazon Bedrock.")


def _current_model(target_file: Path, key: str | None, pattern: str | None) -> str:
    import re

    import yaml

    text = target_file.read_text()
    if pattern:
        m = re.search(pattern, text)
        if not m:
            raise typer.BadParameter(f"pattern did not match in {target_file}")
        return m.group(1)
    node = yaml.safe_load(text)
    for part in key.split("."):
        node = node[part]
    return str(node)


@app.command()
def scan(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("modelbot.yaml"),
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show deprecated baselines and upgrade candidates for every target."""
    import boto3

    try:
        cfg = load_config(config)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e

    root = config.parent
    catalog = discovery.fetch_catalog(boto3.client("bedrock", region_name=cfg.region))
    results = []
    for t in cfg.targets:
        baseline = _current_model(root / t.file, t.key, t.pattern)
        results.append(
            discovery.ScanResult(
                target=t.name,
                baseline=baseline,
                urgent=discovery.is_urgent(baseline, catalog),
                candidates=discovery.find_candidates(baseline, catalog, cfg.candidates),
            )
        )

    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "target": r.target,
                        "baseline": r.baseline,
                        "urgent": r.urgent,
                        "candidates": [c.model_id for c in r.candidates],
                    }
                    for r in results
                ],
                indent=2,
            )
        )
        return
    for r in results:
        flag = "⚠️  LEGACY" if r.urgent else "ok"
        typer.echo(f"{r.target}: {r.baseline} [{flag}] — {len(r.candidates)} candidate(s)")
        for c in r.candidates:
            typer.echo(f"    • {c.model_id}")


@app.command(name="eval")
def eval_cmd() -> None:
    """Evaluate baseline and candidates on the eval suite (task 4)."""
    raise typer.Exit(typer.echo("not implemented yet — see .kiro/specs/modelbot/tasks.md", err=True) or 1)


@app.command()
def run() -> None:
    """scan → eval → port → decide → report/PR (tasks 6–8)."""
    raise typer.Exit(typer.echo("not implemented yet — see .kiro/specs/modelbot/tasks.md", err=True) or 1)


if __name__ == "__main__":
    app()
