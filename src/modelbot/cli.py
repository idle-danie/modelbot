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
from modelbot.decision import decide, portable
from modelbot.porter import port_prompt, strands_reviser, strands_rule_checker
from modelbot.pricing import BudgetTracker, cost_usd, has_price, load_prices
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


def _rule_checker(cfg: Config, candidate: str, on_usage: Any) -> Any:
    """Judge-backed rule check (None without a judge). The judge must not be the candidate (R4.3)."""
    if not cfg.judge_model:
        typer.echo(
            "  warning: no judge_model configured; ported prompts are not checked for rule changes", err=True
        )
        return None
    if discovery.base_model_id(cfg.judge_model) == discovery.base_model_id(candidate):
        typer.echo(f"judge_model {cfg.judge_model} must differ from the candidate under evaluation", err=True)
        raise typer.Exit(2)
    return strands_rule_checker(cfg.judge_model, cfg.region, on_usage=on_usage)


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
                status=discovery.baseline_status(baseline, catalog),
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
                "status": r.status,
                "candidates": [c.invoke_id for c in r.candidates],
            }
            for r in results
        ]
        typer.echo(json.dumps(payload, indent=2))
        return
    for r in results:
        flag = {"LEGACY": "⚠️  LEGACY", "MISSING": "⛔ NOT IN CATALOG"}.get(r.status, "ok")
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
    no_port: Annotated[bool, typer.Option("--no-port", help="Skip agent-driven prompt porting")] = False,
    repeats: Annotated[int | None, typer.Option(help="Run each case N times (overrides config)")] = None,
) -> None:
    """Evaluate baseline and candidates on each target's eval suite and write a report."""
    import boto3

    cfg = _load(config)
    root = config.parent
    prices = load_prices(override=prices_file)
    runtime = boto3.client("bedrock-runtime", region_name=cfg.region)
    budget = BudgetTracker(cfg.budget_usd)
    catalog, scans = _scan(cfg, root)

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

        n_runs = repeats or target.repeats

        def run(
            model_id: str, prompt: str = prompt, cases: list = cases, quiet: bool = False, n: int = n_runs
        ):
            if not quiet:
                typer.echo(f"  evaluating {model_id} on {len(cases)} cases …", err=True)
            return run_suite(
                runtime,
                model_id,
                prompt,
                cases,
                concurrency=cfg.concurrency,
                prices=prices,
                budget=budget,
                repeats=n,
            )

        def track_agent_usage(model_id: str, input_tokens: int, output_tokens: int) -> None:
            if has_price(prices, model_id):
                budget.add(cost_usd(prices, model_id, input_tokens, output_tokens))
            else:
                typer.echo(
                    f"  warning: no price for porting model {model_id}; its spend is not tracked", err=True
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
        rec = decide(target, baseline, results, prices, urgent=sc.urgent, baseline_status=sc.status)

        can_port = not no_port and target.porting.enabled and cfg.porting_model and rec.chosen is None
        near_misses = [c for c in rec.ranked if portable(c, baseline, target)] if can_port else []
        if near_misses:
            best = near_misses[0]
            info = catalog.get(discovery.base_model_id(best.model_id))
            typer.echo(
                f"  porting prompt for {best.model_id} ({best.pass_rate:.0%}) with {cfg.porting_model} …",
                err=True,
            )
            ported = port_prompt(
                model_id=best.model_id,
                provider=info.provider if info else "",
                prompt=prompt,
                cases=cases,
                policy=target.porting,
                evaluate=lambda p, cs, m=best.model_id: run(m, prompt=p, cases=cs, quiet=True),
                reviser=strands_reviser(cfg.porting_model, cfg.region, on_usage=track_agent_usage),
                rule_checker=_rule_checker(cfg, best.model_id, track_agent_usage),
                should_stop=lambda: budget.exhausted,
            )
            if ported.accepted:
                rerun = run(best.model_id, prompt=ported.revised)
                results = [rerun if r is best else r for r in results]
                rec = decide(target, baseline, results, prices, urgent=sc.urgent, baseline_status=sc.status)
            rec.ported[best.model_id] = ported
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
def port(
    candidate: Annotated[str, typer.Option("--candidate", help="Model or inference profile ID to port to")],
    config: ConfigOpt = Path("modelbot.yaml"),
    target_name: Annotated[str | None, typer.Option("--target", help="Target name (default: first)")] = None,
    porting_model: Annotated[str | None, typer.Option(help="Override porting_model from config")] = None,
    prices_file: Annotated[Path | None, typer.Option("--prices", help="Price override YAML")] = None,
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("modelbot-port.md"),
) -> None:
    """Adapt a target's prompt to one specific candidate model, regardless of thresholds."""
    import boto3

    from modelbot.porter import porting_report

    cfg = _load(config)
    root = config.parent
    target = next((t for t in cfg.targets if target_name in (None, t.name)), None)
    if target is None:
        typer.echo(f"no target named {target_name!r}", err=True)
        raise typer.Exit(2)
    agent_model = porting_model or cfg.porting_model
    if not agent_model:
        typer.echo("set porting_model in modelbot.yaml or pass --porting-model", err=True)
        raise typer.Exit(2)
    prices = load_prices(override=prices_file)
    for m in (candidate, agent_model, *([cfg.judge_model] if cfg.judge_model else [])):
        if not has_price(prices, m):
            typer.echo(f"no price for {m}; add it with --prices", err=True)
            raise typer.Exit(2)

    runtime = boto3.client("bedrock-runtime", region_name=cfg.region)
    budget = BudgetTracker(cfg.budget_usd)
    prompt = _read_prompt(root, target)
    cases = load_cases(root / target.evals)

    def evaluate(p: str, cs: list) -> Any:
        return run_suite(
            runtime,
            candidate,
            p,
            cs,
            concurrency=cfg.concurrency,
            prices=prices,
            budget=budget,
            repeats=target.repeats,
        )

    def on_usage(model_id: str, input_tokens: int, output_tokens: int) -> None:
        budget.add(cost_usd(prices, model_id, input_tokens, output_tokens))

    typer.echo(f"[{target.name}] porting prompt to {candidate} with {agent_model} …", err=True)
    before = evaluate(prompt, cases)
    result = port_prompt(
        model_id=candidate,
        provider=discovery.base_model_id(candidate).split(".", 1)[0],
        prompt=prompt,
        cases=cases,
        policy=target.porting,
        evaluate=evaluate,
        reviser=strands_reviser(agent_model, cfg.region, on_usage=on_usage),
        rule_checker=_rule_checker(cfg, candidate, on_usage),
        should_stop=lambda: budget.exhausted,
    )
    after = evaluate(result.revised, cases) if result.accepted else before
    md = porting_report(result, before, after, target.name)
    output.write_text(md)
    typer.echo(md)
    typer.echo(
        f"requests: {budget.requests} · estimated spend: ${budget.spent_usd:.4f} of ${cfg.budget_usd:.2f}",
        err=True,
    )


@app.command()
def run() -> None:
    """scan → eval → port → decide → report/PR (tasks 6–8)."""
    typer.echo("not implemented yet — see .kiro/specs/modelbot/tasks.md", err=True)
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
