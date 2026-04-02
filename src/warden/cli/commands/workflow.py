"""
Workflow Commands for Warden CLI

Provides named scan presets via `warden workflow`:
- warden workflow list        — show all presets with descriptions
- warden workflow run <name>  — run a named scan preset

Presets translate a human-readable name into the equivalent scan
arguments and invoke the scan pipeline directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

console = Console()

# ---------------------------------------------------------------------------
# Preset Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowPreset:
    """Definition of a named scan workflow preset."""

    name: str
    description: str
    # Keyword arguments forwarded to scan_command()
    scan_kwargs: dict[str, Any] = field(default_factory=dict)


PRESETS: dict[str, WorkflowPreset] = {
    "ci": WorkflowPreset(
        name="ci",
        description="Fast scan optimised for CI pipelines (basic level, no-preflight, 120s timeout).",
        scan_kwargs={
            "level": "basic",
            "no_preflight": True,
            "ci": True,
        },
    ),
    "security-audit": WorkflowPreset(
        name="security-audit",
        description="Deep security audit with SARIF output for compliance and penetration testing.",
        scan_kwargs={
            "level": "deep",
            "format": "sarif",
        },
    ),
    "pre-commit": WorkflowPreset(
        name="pre-commit",
        description="Diff-only scan for pre-commit hooks — analyses only files changed since HEAD.",
        scan_kwargs={
            "level": "standard",
            "diff": True,
            "base": "HEAD",
        },
    ),
    "nightly": WorkflowPreset(
        name="nightly",
        description="Full scan with SARIF output written to .warden/reports/ for nightly baseline updates.",
        scan_kwargs={
            "level": "standard",
            "format": "sarif",
            "output": ".warden/reports/",
        },
    ),
}


def get_preset(name: str) -> WorkflowPreset | None:
    """Return the preset for *name*, or None if it does not exist."""
    return PRESETS.get(name)


def list_presets() -> list[WorkflowPreset]:
    """Return all available presets in alphabetical order."""
    return sorted(PRESETS.values(), key=lambda p: p.name)


# ---------------------------------------------------------------------------
# Typer app
# ---------------------------------------------------------------------------

workflow_app = typer.Typer(
    name="workflow",
    help="Run named scan presets (ci, security-audit, pre-commit, nightly).",
    no_args_is_help=True,
)


@workflow_app.command("list")
def workflow_list() -> None:
    """
    List all available named workflow presets.

    Examples:
        warden workflow list
    """
    presets = list_presets()

    table = Table(title="Available Workflow Presets", show_header=True, header_style="bold cyan")
    table.add_column("Preset", style="bold green", min_width=16)
    table.add_column("Description", style="white")
    table.add_column("Key Options", style="dim")

    for preset in presets:
        opts = ", ".join(
            f"{k}={v}" for k, v in preset.scan_kwargs.items()
        )
        table.add_row(preset.name, preset.description, opts)

    console.print()
    console.print(table)
    console.print()
    console.print(
        "[dim]Run a preset with:[/dim] [bold]warden workflow run <preset>[/bold]"
    )


@workflow_app.command("run")
def workflow_run(
    preset_name: str = typer.Argument(..., help="Preset name: ci, security-audit, pre-commit, nightly"),
    paths: list[str] | None = typer.Argument(None, help="Optional file/directory paths to scan"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed scan logs"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what the preset would run without executing"
    ),
) -> None:
    """
    Run a named workflow preset.

    Translates the preset name into the equivalent scan arguments and
    invokes the scan pipeline directly.

    Examples:
        warden workflow run ci
        warden workflow run security-audit src/
        warden workflow run pre-commit --verbose
        warden workflow run nightly --dry-run
    """
    preset = get_preset(preset_name)

    if preset is None:
        available = ", ".join(sorted(PRESETS.keys()))
        console.print(
            f"[bold red]Unknown preset:[/bold red] [yellow]{preset_name}[/yellow]"
        )
        console.print(f"[dim]Available presets: {available}[/dim]")
        raise typer.Exit(1)

    # Always show what we are about to run
    console.print(f"\n[bold cyan]Workflow:[/bold cyan] {preset.name}")
    console.print(f"[dim]{preset.description}[/dim]")

    # Merge preset scan_kwargs with any CLI overrides
    merged_kwargs: dict[str, Any] = dict(preset.scan_kwargs)
    if verbose:
        merged_kwargs["verbose"] = True

    opts_display = ", ".join(f"--{k.replace('_', '-')} {v}" for k, v in merged_kwargs.items())
    console.print(f"[dim]Options: {opts_display}[/dim]\n")

    if dry_run:
        console.print(
            "[yellow]Dry-run mode — scan not executed.[/yellow]"
        )
        return

    # Import scan_command here to avoid circular imports at module load time
    from warden.cli.commands.scan import scan_command

    # Build the full kwargs dict scan_command() expects, using safe defaults
    # for every parameter not covered by the preset.
    scan_defaults: dict[str, Any] = {
        "paths": paths or None,
        "frames": None,
        "format": "text",
        "output": None,
        "verbose": False,
        "level": None,
        "no_ai": False,
        "quick_start": False,
        "memory_profile": False,
        "ci": False,
        "diff": False,
        "base": "main",
        "fail_on_severity": "critical",
        "no_update_baseline": False,
        "cost_report": False,
        "auto_fix": False,
        "dry_run": False,
        "force": False,
        "no_preflight": False,
        "benchmark": False,
        "contract_mode": False,
        "resume": False,
        "provider": None,
    }
    scan_defaults.update(merged_kwargs)

    try:
        scan_command(**scan_defaults)
    except SystemExit as exc:
        raise typer.Exit(int(exc.code) if exc.code is not None else 0)
