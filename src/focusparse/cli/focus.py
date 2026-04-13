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

import json
import os
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
        raise typer.Exit(code=2)

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
    pb_schema = Path(__file__).resolve().parents[3] / "third_party" / "parser-bench" / "src" / "utils" / "schema.py"
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
) -> None:
    """Run an evaluation."""
    _ = _parse_kv(budget)
    if agent == "simple":
        typer.echo(
            f"[focus eval] agent=simple backend={backend} model={model} "
            f"protocol={protocol} split={split} limit={limit}"
        )
        typer.echo("Simple harness is wired to focusparse.eval.harness.run_simple_eval (Phase 1 final).")
        raise NotImplementedError(
            "Phase 1 final commit: implement run_simple_eval and call it here."
        )
    elif agent == "focus":
        typer.echo(
            f"[focus eval] agent=focus tier={tier} protocol={protocol} "
            f"split={split} limit={limit}"
        )
        raise NotImplementedError("Focus workflow wired in Phase 2.")
    else:
        typer.echo(f"Unknown agent: {agent!r}")
        raise typer.Exit(code=2)


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
def report(run_dir: Path = typer.Argument(..., help="Path to a results/runs/<ts>/ directory")) -> None:
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
