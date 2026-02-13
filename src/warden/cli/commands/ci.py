"""
CI Commands for Warden CLI

Provides commands for managing CI/CD workflow files:
- warden ci init: Initialize CI workflows
- warden ci update: Update workflows from templates
- warden ci sync: Sync with current configuration
- warden ci status: Show CI workflow status

Chaos Engineering Principles:
- Fail Fast: Validate inputs early, clear error messages
- Idempotent: Safe to run multiple times
- Observable: Structured output, JSON support
- Defensive: Handle all error cases gracefully
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from warden.services.ci_manager import (
    CURRENT_TEMPLATE_VERSION,
    CIManager,
    CIManagerError,
    CIProvider,
    SecurityError,
    ValidationError,
)
from warden.services.ci_manager.provider_detection import detect_provider

console = Console()

# Create Typer app for CI subcommands
ci_app = typer.Typer(
    name="ci",
    help="Manage CI/CD workflow files",
    no_args_is_help=True,
)


# =============================================================================
# Helper Functions
# =============================================================================


def _get_ci_manager() -> CIManager:
    """
    Get CI manager instance for current directory.

    Raises:
        typer.Exit: If initialization fails
    """
    try:
        return CIManager(project_root=Path.cwd())
    except ValidationError as e:
        console.print(f"[red]Validation Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Failed to initialize CI Manager:[/red] {e}")
        raise typer.Exit(1)


def _parse_provider(provider: str | None) -> CIProvider | None:
    """
    Parse and validate provider string.

    Returns:
        CIProvider if valid, None if empty
    Raises:
        typer.Exit: If provider is invalid
    """
    if not provider:
        return None

    try:
        return CIProvider.from_string(provider)
    except ValidationError as e:
        console.print(f"[red]Invalid provider:[/red] {e}")
        console.print("[dim]Valid options: github, gitlab[/dim]")
        raise typer.Exit(1)


def _print_secrets_hint(llm_provider: str) -> None:
    """Print reminder about CI secrets if using cloud provider."""
    if llm_provider == "ollama":
        return

    key_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "azure": "AZURE_OPENAI_API_KEY",
        "azure_openai": "AZURE_OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }

    if llm_provider in key_map:
        console.print(f"\n[yellow]Remember to add secrets to your CI:[/yellow]")
        console.print(f"  - {key_map[llm_provider]}")


# =============================================================================
# Commands
# =============================================================================


@ci_app.command("init")
def ci_init(
    provider: str | None = typer.Option(None, "--provider", "-p", help="CI provider: github or gitlab"),
    branch: str = typer.Option("main", "--branch", "-b", help="Default branch name"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing workflow files"),
) -> None:
    """
    Initialize CI/CD workflows from templates.

    Creates workflow files for GitHub Actions or GitLab CI.
    Idempotent: existing files are skipped unless --force is used.

    Examples:
        warden ci init --provider github
        warden ci init -p gitlab -b main
        warden ci init --force
    """
    console.print("\n[bold cyan]Initializing CI/CD Workflows[/bold cyan]")

    manager = _get_ci_manager()

    # Auto-detect or prompt for provider
    ci_provider = _parse_provider(provider)

    if not ci_provider:
        detected = detect_provider(manager.project_root)
        if detected:
            ci_provider = detected
            console.print(f"[dim]Detected provider: {ci_provider.value}[/dim]")
        else:
            # Interactive selection only if stdin is a tty
            if sys.stdin.isatty():
                console.print("\n[bold]Select CI Provider:[/bold]")
                console.print("  [1] GitHub Actions")
                console.print("  [2] GitLab CI")

                try:
                    choice = typer.prompt("Choice", default="1")
                    if choice == "1":
                        ci_provider = CIProvider.GITHUB
                    elif choice == "2":
                        ci_provider = CIProvider.GITLAB
                    else:
                        console.print("[red]Invalid choice. Use 1 or 2.[/red]")
                        raise typer.Exit(1)
                except (KeyboardInterrupt, EOFError):
                    console.print("\n[yellow]Cancelled.[/yellow]")
                    raise typer.Exit(0)
            else:
                console.print("[red]No provider specified and no existing CI detected.[/red]")
                console.print("[dim]Use --provider github or --provider gitlab[/dim]")
                raise typer.Exit(1)

    # Initialize
    try:
        result = manager.init(
            provider=ci_provider,
            branch=branch,
            force=force,
        )
    except (ValidationError, SecurityError) as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except CIManagerError as e:
        console.print(f"\n[red]CI Manager Error:[/red] {e}")
        raise typer.Exit(1)

    # Display results
    if result.get("created"):
        console.print(f"\n[bold green]Created {len(result['created'])} workflow(s):[/bold green]")
        for path in result["created"]:
            console.print(f"  [green]+[/green] {path}")

    if result.get("skipped"):
        console.print(f"\n[yellow]Skipped {len(result['skipped'])} existing file(s):[/yellow]")
        for path in result["skipped"]:
            console.print(f"  [dim]-[/dim] {path}")
        console.print("[dim]Use --force to overwrite[/dim]")

    if result.get("errors"):
        console.print(f"\n[red]Errors ({len(result['errors'])}):[/red]")
        for error in result["errors"]:
            console.print(f"  [red]![/red] {error}")
        raise typer.Exit(1)

    # Show workflow summary for GitHub
    if ci_provider == CIProvider.GITHUB and result.get("created"):
        console.print("\n[bold]Workflow Summary:[/bold]")
        console.print("  [cyan]warden-pr.yml[/cyan]      - PR scans (--ci --diff)")
        console.print("  [cyan]warden-nightly.yml[/cyan] - Nightly baseline updates")
        console.print("  [cyan]warden-release.yml[/cyan] - Release security audits")
        console.print("  [cyan]warden.yml[/cyan]         - Main push/PR workflow")

    # Show secrets hint
    llm_provider = manager._get_llm_config().get("provider", "ollama")
    _print_secrets_hint(str(llm_provider))

    console.print("\n[bold green]CI/CD initialization complete![/bold green]")


@ci_app.command("update")
def ci_update(
    no_preserve_custom: bool = typer.Option(
        False, "--no-preserve-custom", help="Overwrite custom sections in workflow files"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be updated without making changes"),
) -> None:
    """
    Update CI workflows from latest templates.

    Preserves custom sections marked with WARDEN-CUSTOM comments unless --no-preserve-custom is used.
    Use --dry-run to preview changes without applying them.

    Examples:
        warden ci update
        warden ci update --dry-run
        warden ci update --no-preserve-custom
    """
    console.print("\n[bold cyan]Updating CI/CD Workflows[/bold cyan]")

    if dry_run:
        console.print("[dim](Dry run - no changes will be made)[/dim]")

    manager = _get_ci_manager()

    try:
        result = manager.update(
            preserve_custom=not no_preserve_custom,
            dry_run=dry_run,
        )
    except CIManagerError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if not result.get("success", False) and "error" in result:
        console.print(f"\n[red]{result['error']}[/red]")
        raise typer.Exit(1)

    # Display results
    if result.get("updated"):
        action = "Would update" if dry_run else "Updated"
        console.print(f"\n[bold green]{action} {len(result['updated'])} workflow(s):[/bold green]")
        for update in result["updated"]:
            path = update["path"]
            old_ver = update.get("old_version") or "?"
            new_ver = update.get("new_version", CURRENT_TEMPLATE_VERSION)
            preserved = update.get("preserved_custom", False)

            status = f"v{old_ver} -> v{new_ver}"
            if preserved:
                status += " [cyan](custom preserved)[/cyan]"

            console.print(f"  [green]+[/green] {path}: {status}")

    if result.get("unchanged"):
        console.print(f"\n[dim]Unchanged ({len(result['unchanged'])} up-to-date):[/dim]")
        for path in result["unchanged"]:
            console.print(f"  [dim]-[/dim] {path}")

    if result.get("errors"):
        console.print(f"\n[red]Errors ({len(result['errors'])}):[/red]")
        for error in result["errors"]:
            console.print(f"  [red]![/red] {error}")
        raise typer.Exit(1)

    if not dry_run:
        console.print("\n[bold green]CI/CD update complete![/bold green]")


@ci_app.command("sync")
def ci_sync() -> None:
    """
    Sync CI workflows with current Warden configuration.

    Updates LLM provider and environment variables without
    changing workflow structure or custom sections.

    Examples:
        warden ci sync
    """
    console.print("\n[bold cyan]Syncing CI/CD Workflows[/bold cyan]")

    manager = _get_ci_manager()

    try:
        result = manager.sync()
    except CIManagerError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if not result.get("success", False) and "error" in result:
        console.print(f"\n[red]{result['error']}[/red]")
        raise typer.Exit(1)

    if result.get("synced"):
        console.print(f"\n[bold green]Synced {len(result['synced'])} workflow(s):[/bold green]")
        for path in result["synced"]:
            console.print(f"  [green]+[/green] {path}")

    if result.get("errors"):
        console.print(f"\n[red]Errors ({len(result['errors'])}):[/red]")
        for error in result["errors"]:
            console.print(f"  [red]![/red] {error}")
        raise typer.Exit(1)

    llm_provider = manager._get_llm_config().get("provider", "ollama")
    console.print(f"\n[dim]CI workflows now use LLM provider: {llm_provider}[/dim]")
    console.print("[bold green]CI/CD sync complete![/bold green]")


@ci_app.command("status")
def ci_status(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Show CI workflow status.

    Displays:
    - Detected CI provider
    - Workflow file status
    - Version information
    - Update availability

    Examples:
        warden ci status
        warden ci status --json
    """
    manager = _get_ci_manager()

    try:
        status_data = manager.to_dict()
    except CIManagerError as e:
        if json_output:
            console.print(json.dumps({"error": str(e)}, indent=2))
        else:
            console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        console.print(json.dumps(status_data, indent=2))
        return

    # Display status
    console.print("\n[bold cyan]CI/CD Workflow Status[/bold cyan]")
    console.print()

    if not status_data.get("is_configured"):
        console.print(
            Panel(
                "[yellow]No CI workflows detected.[/yellow]\n\nRun [bold]warden ci init[/bold] to set up CI/CD.",
                title="Status",
            )
        )
        return

    # Provider info
    provider = status_data.get("provider", "unknown")
    template_ver = status_data.get("template_version", "?")
    needs_update = status_data.get("needs_update", False)

    provider_display = {
        "github": "GitHub Actions",
        "gitlab": "GitLab CI",
    }.get(provider, provider)

    console.print(f"[bold]Provider:[/bold] {provider_display}")
    console.print(f"[bold]Template Version:[/bold] v{template_ver}")

    if needs_update:
        console.print("[yellow]Updates available - run 'warden ci update'[/yellow]")

    console.print()

    # Workflow table
    table = Table(title="Workflows", box=None)
    table.add_column("Workflow", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Version", style="dim")
    table.add_column("Custom", style="magenta")

    workflows = status_data.get("workflows", {})

    for name, wf in workflows.items():
        if wf.get("error"):
            status_icon = f"[red]Error: {wf['error']}[/red]"
        elif not wf.get("exists"):
            status_icon = "[red]Missing[/red]"
        elif wf.get("is_outdated"):
            status_icon = "[yellow]Outdated[/yellow]"
        else:
            status_icon = "[green]Current[/green]"

        version = f"v{wf.get('version')}" if wf.get("version") else "[dim]none[/dim]"

        custom = ""
        if wf.get("has_custom_sections"):
            sections = wf.get("custom_sections", [])
            custom = f"[magenta]{len(sections)} section(s)[/magenta]"

        path = wf.get("path", "")
        display_name = Path(path).name if path else name

        table.add_row(display_name, status_icon, version, custom)

    console.print(table)

    # Show last modified for most recent
    most_recent = None
    most_recent_time = None

    for name, wf in workflows.items():
        if wf.get("last_modified"):
            from datetime import datetime

            try:
                dt = datetime.fromisoformat(wf["last_modified"])
                if most_recent_time is None or dt > most_recent_time:
                    most_recent_time = dt
                    most_recent = wf.get("path")
            except (ValueError, TypeError):
                pass

    if most_recent_time and most_recent:
        console.print(f"\n[dim]Last modified: {most_recent} ({most_recent_time.strftime('%Y-%m-%d %H:%M')})[/dim]")
