"""modelbot CLI (Requirement 8.1)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from modelbot import discovery
from modelbot.config import Config, ConfigError, Target, load_config
from modelbot.decision import decide
from modelbot.pricing import BudgetTracker, has_price, load_prices
from modelbot.report import render_markdown
from modelbot.runner import load_cases, run_suite

app = typer.Typer(help="Dependabot for LLMs: eval-gated model upgrades on Amazon Bedrock.")

ConfigOpt = Annotated[Path, typer.Option("--config", "-c", help="Path to modelbot.yaml")]


def _load(config: Path) -> Config:
    try:
        return load_config(config)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e


def current_model(target_file: Path, key: str | None, pattern: str | None) -> str:
    text = target_file.read_text()
    if pattern:
        m = re.search(pattern, text)
        if not m:
            raise typer.BadParameter(f"pattern did not match in {target_file}")
        return m.group(1)
    node: Any = yaml.safe_load(text)
    for part in key.split("."):
        node = node[part]
    return str(node)


def _read_prompt(root: Path, target: Target) -> str:
    return "\n\n".join((root / p).read_text().strip() for p in target.prompts)


def _scan(cfg: Config, root: Path) -> tuple[dict[str, discovery.ModelInfo], list[discovery.ScanResult]]:
    import boto3

    catalog = discovery.fetch_catalog(boto3.client("bedrock", region_name=cfg.region), cfg.region)
    results = []
    for t in cfg.targets:
        baseline = current_model(root / t.file, t.key, t.pattern)
        results.append(
            discovery.ScanResult(
                target=t.name,
                baseline=baseline,
                urgent=discovery.is_urgent(baseline, catalog),
                candidates=discovery.find_candidates(baseline, catalog, cfg.candidates),
            )
        )
    return catalog, results


@app.command()
def scan(
    config: ConfigOpt = Path("modelbot.yaml"),
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show deprecated baselines and upgrade candidates for every target."""
    cfg = _load(config)
    _, results = _scan(cfg, config.parent)
    if as_json:
        payload = [
            {
                "target": r.target,
                "baseline": r.baseline,
                "urgent": r.urgent,
                "candidates": [c.invoke_id for c in r.candidates],
            }
            for r in results
        ]
        typer.echo(json.dumps(payload, indent=2))
        return
    for r in results:
        flag = "⚠️  LEGACY" if r.urgent else "ok"
        typer.echo(f"{r.target}: {r.baseline} [{flag}] — {len(r.candidates)} candidate(s)")
        for c in r.candidates:
            typer.echo(f"    • {c.invoke_id}")


@app.command(name="eval")
def eval_cmd(
    config: ConfigOpt = Path("modelbot.yaml"),
    candidate: Annotated[
        list[str] | None, typer.Option("--candidate", help="Evaluate only these model / profile IDs")
    ] = None,
    max_candidates: Annotated[int, typer.Option(help="Cap on auto-selected candidates per target")] = 3,
    prices_file: Annotated[Path | None, typer.Option("--prices", help="Price override YAML")] = None,
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("modelbot-report.md"),
) -> None:
    """Evaluate baseline and candidates on each target's eval suite and write a report."""
    import boto3

    cfg = _load(config)
    root = config.parent
    prices = load_prices(override=prices_file)
    runtime = boto3.client("bedrock-runtime", region_name=cfg.region)
    budget = BudgetTracker(cfg.budget_usd)
    _, scans = _scan(cfg, root)

    reports = []
    for target, sc in zip(cfg.targets, scans, strict=True):
        prompt = _read_prompt(root, target)
        cases = load_cases(root / target.evals)
        ids = candidate or [c.invoke_id for c in sc.candidates][:max_candidates]
        priced = [m for m in ids if has_price(prices, m)]
        for m in sorted(set(ids) - set(priced)):
            typer.echo(f"skip {m}: no price (add it with --prices)", err=True)
        if not has_price(prices, sc.baseline):
            typer.echo(f"{target.name}: baseline {sc.baseline} has no price; add it with --prices", err=True)
            raise typer.Exit(2)

        def run(model_id: str, prompt: str = prompt, cases: list = cases):
            typer.echo(f"  evaluating {model_id} on {len(cases)} cases …", err=True)
            return run_suite(
                runtime, model_id, prompt, cases, concurrency=cfg.concurrency, prices=prices, budget=budget
            )

        typer.echo(f"[{target.name}]", err=True)
        baseline = run(sc.baseline)
        results = []
        for model_id in priced:
            r = run(model_id)
            if r.results and len(r.errored) == len(r.results):
                typer.echo(f"  skip {model_id}: every case errored ({r.errored[0].error})", err=True)
                continue
            results.append(r)
        rec = decide(target, baseline, results, prices, urgent=sc.urgent)
        reports.append(render_markdown(rec, prices))

    md = "\n---\n\n".join(reports)
    output.write_text(md)
    typer.echo(md)
    typer.echo(
        f"requests: {budget.requests} · estimated spend: ${budget.spent_usd:.4f} of ${cfg.budget_usd:.2f}"
        + (" (budget exhausted — results are partial)" if budget.exhausted else ""),
        err=True,
    )


@app.command()
def run() -> None:
    """scan → eval → port → decide → report/PR (tasks 6–8)."""
    typer.echo("not implemented yet — see .kiro/specs/modelbot/tasks.md", err=True)
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
