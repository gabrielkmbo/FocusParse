"""`focus` CLI — the single entrypoint for humans and subagents.

Subcommands:
  focus status [--short]                            — print env + tier config
  focus eval --agent (simple|focus) ...             — run evaluation
  focus report <run_dir>                            — render HTML report (Phase 4)
  focus export-traces <run_dir> [--out path]        — export SFT-ready JSONL (Phase 6)

Phase 1 status:
  - `focus status` works standalone (no API calls).
  - `focus eval --agent simple` is wired to the harness stub — NotImplementedError
    until the harness is filled in (Phase 1 final commit). Structure is stable.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from focusparse.utils.config import load_config

app = typer.Typer(add_completion=False, help="FocusParse — agentic evidence-localization pipeline.")
console = Console()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(short: bool = typer.Option(False, "--short", help="One-line summary")) -> None:
    """Print env + tier config."""
    try:
        config = load_config()
    except Exception as e:
        typer.echo(f"focusparse: config load failed: {e}")
        raise typer.Exit(code=2) from e

    env_keys = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "HF_TOKEN",
        "VLLM_API_KEY",
        "LLAMA_CLOUD_API_KEY",
        "TESSERACT_CMD",
    ]
    present = {k: (os.environ.get(k) not in (None, "")) for k in env_keys}

    if short:
        tiers = ", ".join(
            f"{role}={config.tier_for(role).provider}:{config.tier_for(role).model}"
            for role in ("planner", "router", "reasoner", "verifier")
        )
        n_env = sum(present.values())
        typer.echo(f"focusparse v0.1.0 | env {n_env}/{len(env_keys)} | {tiers}")
        return

    # Env table
    env_table = Table(title="Environment", show_header=True, header_style="bold")
    env_table.add_column("Variable")
    env_table.add_column("Status")
    for k, ok in present.items():
        env_table.add_row(k, "[green]present[/green]" if ok else "[red]missing[/red]")
    console.print(env_table)

    # Tier table
    tier_table = Table(title="Per-role tier assignment", show_header=True, header_style="bold")
    tier_table.add_column("Role")
    tier_table.add_column("Tier")
    tier_table.add_column("Provider:model")
    for role in config.roles:
        tier = config.tier_for(role)
        env_override = os.environ.get(f"FOCUSPARSE_TIER_{role.upper()}")
        tier_name = env_override or config.roles[role]
        tier_table.add_row(role, tier_name, f"{tier.provider}:{tier.model}")
    console.print(tier_table)

    # Dataset + NFS
    ds_table = Table(title="Dataset + NFS", show_header=True, header_style="bold")
    ds_table.add_column("Key")
    ds_table.add_column("Value")
    ds_table.add_row("dataset.source", config.dataset.source)
    ds_table.add_row("dataset.hf_repo", config.dataset.hf_repo)
    ds_table.add_row(
        "dataset.revision",
        config.dataset.revision or "[yellow]unpinned[/yellow]",
    )
    ds_table.add_row("nfs.host", config.nfs.host)
    ds_table.add_row("nfs.remote_root", config.nfs.remote_root)
    ds_table.add_row("cache.root", config.cache.root)
    ds_table.add_row("traces.schema_version", config.traces.schema_version)
    console.print(ds_table)

    # Submodule presence check
    pb_schema = (
        Path(__file__).resolve().parents[3]
        / "third_party"
        / "parser-bench"
        / "src"
        / "utils"
        / "schema.py"
    )
    if pb_schema.exists():
        console.print("[green]parser-bench submodule: present[/green]")
    else:
        console.print(
            "[red]parser-bench submodule: missing[/red] — run "
            "`git submodule add https://github.com/gabrielkmbo/parse-bench third_party/parser-bench "
            "&& git submodule update --init --recursive`"
        )


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------


@app.command()
def eval(  # noqa: A001 — command name intentionally shadows builtin
    agent: str = typer.Option("simple", help="simple | focus"),
    backend: str = typer.Option("gemini", help="openai | anthropic | gemini"),
    model: str = typer.Option("gemini-3.1-pro-preview"),
    protocol: str = typer.Option("full_doc", help="full_doc | oracle_page | oracle_crop | focus"),
    split: str = typer.Option("dev", help="dev | test | holdout"),
    limit: int = typer.Option(30, help="Max examples to score"),
    tier: str = typer.Option("balanced", help="simple | cheap | balanced | frontier"),
    budget: str = typer.Option(
        "tokens=120000,tool_calls=12,crops=8",
        help="Comma-separated key=value overrides for the focus-agent budget",
    ),
    output_dir: Path = typer.Option(Path("results/runs"), help="Per-run output dir root"),
    export_traces_path: Path | None = typer.Option(None, "--export-traces", help="JSONL output"),
    hf_staging: Path | None = typer.Option(
        None,
        "--hf-staging",
        help="HF materialized staging root (e.g. ~/.cache/focusparse/hf_staging). "
        "If set, eval loads from <staging>/benchmark.jsonl and resolves page_images "
        "relative to this directory.",
    ),
    hf_revision: str | None = typer.Option(None, "--hf-revision"),
    no_resume: bool = typer.Option(False, "--no-resume", help="Ignore prediction cache"),
) -> None:
    """Run an evaluation."""
    _ = _parse_kv(budget)
    if agent == "focus":
        typer.echo(
            f"[focus eval] agent=focus tier={tier} protocol={protocol} split={split} limit={limit}"
        )
        raise NotImplementedError("Focus workflow wired in Phase 2.")
    if agent != "simple":
        typer.echo(f"Unknown agent: {agent!r}")
        raise typer.Exit(code=2)

    typer.echo(
        f"[focus eval] agent=simple backend={backend} model={model} "
        f"protocol={protocol} split={split} limit={limit}"
    )

    run_dir = (
        output_dir / f"simple_{backend}_{model.replace('/', '_')}_{protocol}_{int(time.time())}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    result = asyncio.run(
        _run_simple_eval_cli(
            backend=backend,
            model=model,
            protocol=protocol,
            split=split,
            limit=limit,
            run_dir=run_dir,
            hf_staging=hf_staging,
            hf_revision=hf_revision,
            resume=not no_resume,
        )
    )

    agg = result["aggregate"]
    table = Table(title=f"simple · {backend}:{model} · {protocol} · {split}[:{limit}]")
    table.add_column("metric")
    table.add_column("value")
    table.add_row("n", str(agg.n))
    table.add_row("accuracy", f"{agg.accuracy:.3f}")
    table.add_row("page_recall_mean", f"{agg.page_recall_mean:.3f}")
    table.add_row("bbox_iou_mean", f"{agg.bbox_iou_mean:.3f}")
    table.add_row("evidence_reward_mean", f"{agg.evidence_reward_mean:.3f}")
    table.add_row("lazy_answer_rate", f"{agg.lazy_answer_rate:.3f}")
    table.add_row("usd_total", f"${agg.usd_total:.4f}")
    table.add_row(
        "usd_per_correct",
        f"${agg.usd_per_correct:.4f}" if agg.usd_per_correct is not None else "n/a",
    )
    console.print(table)
    console.print(f"[green]Wrote[/green] {run_dir / 'run.json'}")


async def _run_simple_eval_cli(
    *,
    backend: str,
    model: str,
    protocol: str,
    split: str,
    limit: int,
    run_dir: Path,
    hf_staging: Path | None,
    hf_revision: str | None,
    resume: bool,
) -> dict[str, Any]:
    from focusparse.eval.harness import run_simple_eval
    from focusparse.models.anthropic import AnthropicClient
    from focusparse.models.gemini import GeminiClient
    from focusparse.models.openai import OpenAIClient

    if backend == "gemini":
        client = GeminiClient(model=model)
    elif backend == "openai":
        client = OpenAIClient(model=model)
    elif backend == "anthropic":
        client = AnthropicClient(model=model)
    else:
        raise typer.BadParameter(f"Unknown backend: {backend!r}")

    examples, images_root = _load_examples(split, limit, hf_staging, hf_revision)

    return await run_simple_eval(
        examples,
        backend_client=client,
        backend=backend,
        model=model,
        protocol=protocol,
        output_dir=run_dir,
        images_root=images_root,
        limit=limit,
        resume=resume,
    )


def _load_examples(
    split: str,
    limit: int,
    hf_staging: Path | None,
    hf_revision: str | None,
):
    """Return `(iterable_of_examples, images_root)` for the eval harness."""
    from focusparse._parser_bench import BenchmarkExample

    if hf_staging is not None:
        # Materialized staging: <staging>/benchmark.jsonl + data/processed/...
        from focusparse.eval.hf_loader import materialize_split

        split_name = "validation" if split in ("test", "holdout") else split
        jsonl_path, _ = materialize_split(
            hf_staging, split=split_name, revision=hf_revision, limit=limit
        )
        images_root = hf_staging
        examples = (
            BenchmarkExample.model_validate_json(line)
            for line in jsonl_path.read_text().splitlines()
            if line.strip()
        )
        return examples, images_root

    # Fallback: HF streaming via BenchmarkLoader — no local image paths.
    from focusparse.dataset.loader import BenchmarkLoader

    loader = BenchmarkLoader.from_hf(revision=hf_revision)
    split_name = "validation" if split in ("test", "holdout") else split
    return loader.iter_split(split_name, limit=limit), Path.cwd()


def _parse_kv(s: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        k, _, v = part.partition("=")
        v = v.strip()
        if v.endswith("k") and v[:-1].isdigit():
            out[k.strip()] = int(v[:-1]) * 1000
        elif v.isdigit():
            out[k.strip()] = int(v)
        else:
            try:
                out[k.strip()] = float(v)
            except ValueError:
                out[k.strip()] = v
    return out


# ---------------------------------------------------------------------------
# report + export-traces (stubs)
# ---------------------------------------------------------------------------


@app.command()
def report(
    run_dir: Path = typer.Argument(..., help="Path to a results/runs/<ts>/ directory"),
) -> None:
    """Render an HTML report for a completed run."""
    raise NotImplementedError("focus report — wire in Phase 4")


@app.command("export-traces")
def export_traces(
    run_dir: Path = typer.Argument(...),
    out: Path = typer.Option(Path("traces.jsonl")),
    min_coverage: float = typer.Option(0.8),
    min_iou: float = typer.Option(0.3),
    require_correct: bool = typer.Option(True),
) -> None:
    """Export SFT-ready JSONL trajectories from a run (Phase 6)."""
    _ = (run_dir, out, min_coverage, min_iou, require_correct)
    raise NotImplementedError("focus export-traces — wire in Phase 6")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    app()


if __name__ == "__main__":
    main()


__all__ = ["app", "main"]
