"""
Corpus evaluation commands.

  warden corpus eval [CORPUS_DIR]     — score F1/FP/TP across labeled corpus
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import typer
from rich.console import Console

corpus_app = typer.Typer(name="corpus", help="Corpus-based evaluation commands", no_args_is_help=True)
console = Console()

_DEFAULT_CORPUS = Path("verify/corpus")


@corpus_app.command(name="eval")
def eval_command(
    corpus_dir: Path = typer.Argument(
        _DEFAULT_CORPUS,
        help="Labeled corpus directory [default: verify/corpus]",
        show_default=True,
    ),
    check: str | None = typer.Option(
        None, "--check", "-c",
        help="Evaluate only this check (e.g. sql-injection)",
    ),
    format: str = typer.Option(
        "table", "--format",
        help="Output format: table, json",
    ),
    min_f1: float | None = typer.Option(
        None, "--min-f1",
        help="Exit with code 1 if overall F1 is below this threshold (CI gate)",
    ),
    fast: bool = typer.Option(
        False, "--fast",
        help="Skip LLM — deterministic checks only",
    ),
) -> None:
    """
    Evaluate security checks against a labeled FP/TP corpus.

    Files in CORPUS_DIR must contain a corpus_labels: block:

    \b
        corpus_labels:
          sql-injection: 2    # expected finding count (0 = FP file)
          xss: 0

    Exit codes:
      0 — evaluation passed (or no --min-f1 set)
      1 — F1 below --min-f1 threshold
      2 — corpus directory not found or no labeled files
    """
    if not corpus_dir.exists():
        console.print(f"[red]Corpus directory not found:[/red] {corpus_dir}")
        raise typer.Exit(2)

    exit_code = asyncio.run(_run_eval(corpus_dir, check, format, min_f1, fast))
    raise typer.Exit(exit_code)


async def _run_eval(
    corpus_dir: Path,
    check_id: str | None,
    fmt: str,
    min_f1: float | None,
    fast: bool,
) -> int:
    from warden.validation.corpus.runner import CorpusRunner, format_metrics_table
    from warden.validation.frames.security.security_frame import SecurityFrame

    frame = SecurityFrame()

    if fast:
        # Disable LLM in the frame for deterministic-only evaluation
        try:
            frame._llm_client = None  # type: ignore[attr-defined]
        except Exception:
            pass

    runner = CorpusRunner(corpus_dir, frame)

    console.print(f"\n[bold]Corpus:[/bold] {corpus_dir.resolve()}")
    if check_id:
        console.print(f"[bold]Check:[/bold] {check_id}")
    console.print()

    with console.status("Scanning corpus files…"):
        result = await runner.evaluate(check_id=check_id)

    if result.files_scanned == 0:
        console.print("[yellow]No labeled corpus files found.[/yellow]")
        console.print("Add [bold]corpus_labels:[/bold] blocks to your corpus files.")
        return 2

    if fmt == "json":
        print(json.dumps(result.to_dict(), indent=2))
    else:
        console.print(format_metrics_table(result))
        console.print(f"\n[dim]Files scanned: {result.files_scanned}[/dim]")

    if min_f1 is not None:
        if result.overall_f1 < min_f1:
            console.print(
                f"\n[red]✗ F1 {result.overall_f1:.2f} below minimum {min_f1:.2f}[/red]"
            )
            return 1
        console.print(
            f"\n[green]✓ F1 {result.overall_f1:.2f} ≥ minimum {min_f1:.2f}[/green]"
        )

    return 0
