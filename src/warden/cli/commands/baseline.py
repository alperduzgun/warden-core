"""
Warden Baseline Commands.

Commands for managing and inspecting the baseline.
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()

# Create sub-app for baseline commands
baseline_app = typer.Typer(
    name="baseline",
    help="Manage Warden baseline and technical debt",
    no_args_is_help=True
)


@baseline_app.command(name="debt")
def debt_command(
    module: str = typer.Option(None, "--module", "-m", help="Show debt for a specific module"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed debt items"),
    warn_days: int = typer.Option(7, "--warn-days", help="Days after which to show warning (default: 7)"),
) -> None:
    """
    Show technical debt report.

    Displays debt items (unresolved findings) organized by module,
    with age tracking and severity warnings.

    Examples:
        warden baseline debt              # Show all debt
        warden baseline debt --module auth  # Show debt for auth module
        warden baseline debt --verbose    # Show detailed debt items
    """
    from warden.cli.commands.helpers.baseline_manager import BaselineManager

    console.print("[bold cyan]📊 Technical Debt Report[/bold cyan]\n")

    root = Path.cwd()
    baseline_mgr = BaselineManager(root)

    if not baseline_mgr.is_module_based():
        console.print("[yellow]No module-based baseline found.[/yellow]")
        console.print("[dim]Run 'warden scan --update-baseline' to create one.[/dim]")
        return

    # Get debt report
    report = baseline_mgr.get_debt_report()

    # Filter by module if specified
    modules = report.get("modules", {})
    if module:
        if module not in modules:
            console.print(f"[yellow]Module '{module}' not found in baseline.[/yellow]")
            available = list(modules.keys())
            if available:
                console.print(f"[dim]Available modules: {', '.join(available)}[/dim]")
            return
        modules = {module: modules[module]}

    # Summary table
    table = Table(title="Debt by Module")
    table.add_column("Module", style="cyan")
    table.add_column("Debt Items", justify="right")
    table.add_column("Oldest (days)", justify="right")
    table.add_column("Status", style="dim")

    total_debt = 0
    for mod_name, mod_data in sorted(modules.items()):
        debt_count = mod_data.get("debt_count", 0)
        oldest_age = mod_data.get("oldest_debt_age_days", 0)
        total_debt += debt_count

        # Determine status
        if oldest_age >= 30:
            status = "[red]⚠️  CRITICAL[/red]"
        elif oldest_age >= 14:
            status = "[yellow]⚠️  Warning[/yellow]"
        elif oldest_age >= warn_days:
            status = "[dim]📋 Attention[/dim]"
        else:
            status = "[green]✓ OK[/green]"

        table.add_row(
            mod_name,
            str(debt_count),
            str(oldest_age) if oldest_age > 0 else "-",
            status
        )

    console.print(table)
    console.print(f"\n[bold]Total Debt Items:[/bold] {total_debt}")

    # Show warnings
    warnings = report.get("warnings", [])
    if warnings:
        console.print("\n[bold yellow]Warnings:[/bold yellow]")
        for w in warnings:
            level = w.get("level", "info")
            color = {"critical": "red", "warning": "yellow", "info": "dim"}.get(level, "dim")
            console.print(f"  [{color}]• {w['message']}[/{color}]")

    # Show detailed debt items if verbose
    if verbose:
        console.print("\n[bold]Debt Items Detail:[/bold]")
        for mod_name, mod_data in sorted(modules.items()):
            items = mod_data.get("debt_items", [])
            if not items:
                continue

            console.print(f"\n[cyan]{mod_name}[/cyan] ({len(items)} items)")
            for item in items[:10]:  # Limit to first 10
                rule = item.get("rule_id", "unknown")
                path = item.get("file_path", "unknown")
                severity = item.get("severity", "medium")
                first_seen = item.get("first_seen", "unknown")

                sev_color = {
                    "critical": "red",
                    "high": "yellow",
                    "medium": "blue",
                    "low": "dim"
                }.get(str(severity).lower(), "dim")

                console.print(f"  [{sev_color}]• {rule}[/{sev_color}] at {path}")
                console.print(f"    [dim]First seen: {first_seen[:10] if first_seen != 'unknown' else 'unknown'}[/dim]")

            if len(items) > 10:
                console.print(f"  [dim]... and {len(items) - 10} more[/dim]")


@baseline_app.command(name="migrate")
def migrate_command(
    force: bool = typer.Option(False, "--force", "-f", help="Force migration even if already migrated"),
) -> None:
    """
    Migrate from legacy baseline.json to module-based structure.

    Converts the old single-file baseline format to the new
    per-module baseline structure with debt tracking.
    """
    from warden.cli.commands.helpers.baseline_manager import BaselineManager

    console.print("[bold cyan]🔄 Baseline Migration[/bold cyan]\n")

    root = Path.cwd()
    baseline_mgr = BaselineManager(root)

    # Check if already module-based
    if baseline_mgr.is_module_based() and not force:
        console.print("[yellow]Already using module-based baseline.[/yellow]")
        console.print("[dim]Use --force to re-migrate from legacy baseline.[/dim]")
        return

    # Check if legacy baseline exists
    legacy_path = root / ".warden" / "baseline.json"
    if not legacy_path.exists():
        console.print("[yellow]No legacy baseline.json found.[/yellow]")
        console.print("[dim]Run 'warden scan --update-baseline' to create a new baseline.[/dim]")
        return

    # Load intelligence module map if available
    module_map = None
    try:
        from warden.analysis.services.intelligence_loader import IntelligenceLoader
        intel_loader = IntelligenceLoader(root)
        if intel_loader.load():
            module_map = {
                name: {"path": info.path, "risk_level": info.risk_level.value}
                for name, info in intel_loader.get_module_map().items()
            }
            console.print(f"[dim]Using intelligence module map ({len(module_map)} modules)[/dim]")
    except (ValueError, TypeError, KeyError):  # Graceful CLI degradation
        pass

    # Perform migration
    success = baseline_mgr.migrate_from_legacy(module_map)

    if success:
        console.print("[green]✓ Migration completed successfully![/green]")
        modules = baseline_mgr.list_modules()
        console.print(f"[dim]Created {len(modules)} module baselines[/dim]")
    else:
        console.print("[red]Migration failed.[/red]")


@baseline_app.command(name="status")
def status_command() -> None:
    """
    Show baseline status and health.

    Displays information about the current baseline structure,
    module count, and overall health.
    """
    from warden.cli.commands.helpers.baseline_manager import BaselineManager

    console.print("[bold cyan]📋 Baseline Status[/bold cyan]\n")

    root = Path.cwd()
    baseline_mgr = BaselineManager(root)

    # Check baseline type
    if baseline_mgr.is_module_based():
        console.print("[green]✓ Using module-based baseline (v2.0)[/green]")

        # Load meta
        meta = baseline_mgr.load_meta()
        if meta:
            console.print(f"\n[bold]Metadata:[/bold]")
            console.print(f"  Created: {meta.created_at or 'unknown'}")
            console.print(f"  Updated: {meta.updated_at or 'unknown'}")
            console.print(f"  Modules: {len(meta.modules)}")
            console.print(f"  Total Findings: {meta.total_findings}")
            console.print(f"  Total Debt: {meta.total_debt}")
            if meta.migrated_from_legacy:
                console.print(f"  [dim]Migrated from legacy format[/dim]")

        # List modules
        modules = baseline_mgr.list_modules()
        if modules:
            console.print(f"\n[bold]Modules ({len(modules)}):[/bold]")
            for mod in sorted(modules)[:10]:
                mod_baseline = baseline_mgr.load_module_baseline(mod)
                if mod_baseline:
                    findings = len(mod_baseline.findings)
                    debt = mod_baseline.debt_count
                    console.print(f"  • {mod}: {findings} findings, {debt} debt")
            if len(modules) > 10:
                console.print(f"  [dim]... and {len(modules) - 10} more[/dim]")
    else:
        # Check legacy baseline
        legacy_path = root / ".warden" / "baseline.json"
        if legacy_path.exists():
            console.print("[yellow]Using legacy baseline format (v1.0)[/yellow]")
            console.print("[dim]Run 'warden baseline migrate' to upgrade to v2.0[/dim]")

            # Show basic info
            data = baseline_mgr.load_baseline()
            if data:
                fps = baseline_mgr.get_fingerprints()
                console.print(f"\n[bold]Legacy Baseline:[/bold]")
                console.print(f"  Known Fingerprints: {len(fps)}")
        else:
            console.print("[yellow]No baseline found.[/yellow]")
            console.print("[dim]Run 'warden scan --update-baseline' to create one.[/dim]")


# Export for main.py registration
def baseline_command():
    """Placeholder for typer sub-app registration."""
    pass
