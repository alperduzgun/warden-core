"""
Warden Refresh Command.

Regenerates project intelligence for CI optimization without running a full init.
"""

import asyncio
import typer
from pathlib import Path
from rich.console import Console

console = Console()


async def _refresh_intelligence_async(root: Path, force: bool = False) -> bool:
    """
    Refresh project intelligence.

    Args:
        root: Project root directory.
        force: Force regeneration even if intelligence is recent.

    Returns:
        True if intelligence was regenerated, False otherwise.
    """
    from warden.analysis.services.intelligence_loader import IntelligenceLoader
    from warden.analysis.services.intelligence_saver import IntelligenceSaver
    from warden.analysis.application.project_purpose_detector import ProjectPurposeDetector
    from warden.analysis.domain.intelligence import SecurityPosture
    from datetime import datetime, timedelta, timezone

    # Check if intelligence exists and is recent
    loader = IntelligenceLoader(root)
    saver = IntelligenceSaver(root)

    if not force and saver.exists():
        last_modified = saver.get_last_modified()
        if last_modified:
            age = datetime.now(timezone.utc) - last_modified
            if age < timedelta(hours=24):
                console.print(f"[dim]Intelligence is recent ({age.seconds // 3600}h old). Use --force to regenerate.[/dim]")
                return False

    # Get all code files for analysis
    code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.cpp', '.c', '.h'}
    files = [
        f for f in root.rglob("*")
        if f.is_file()
        and f.suffix in code_extensions
        and "node_modules" not in str(f)
        and ".venv" not in str(f)
        and ".git" not in str(f)
        and "__pycache__" not in str(f)
    ]

    if not files:
        console.print("[yellow]No code files found.[/yellow]")
        return False

    console.print(f"[dim]Analyzing {len(files)} files...[/dim]")

    # Load existing intelligence for comparison
    old_modules = {}
    if loader.load():
        old_modules = {name: info.risk_level.value for name, info in loader.get_module_map().items()}

    # Detect project purpose and modules
    detector = ProjectPurposeDetector(root)
    purpose, architecture, module_map = await detector.detect_async(files, [])

    # Determine security posture
    security_posture = SecurityPosture.STANDARD
    if purpose:
        purpose_lower = purpose.lower()
        if any(kw in purpose_lower for kw in ["payment", "banking", "crypto", "auth"]):
            security_posture = SecurityPosture.STRICT
        elif any(kw in purpose_lower for kw in ["healthcare", "medical", "pii", "gdpr"]):
            security_posture = SecurityPosture.PARANOID

    # Save intelligence
    success = saver.save(
        purpose=purpose,
        architecture=architecture,
        security_posture=security_posture,
        module_map=module_map,
        project_name=root.name
    )

    if success:
        # Show what changed
        new_modules = {name: info.risk_level.value for name, info in module_map.items()}
        added = set(new_modules.keys()) - set(old_modules.keys())
        removed = set(old_modules.keys()) - set(new_modules.keys())
        changed = {
            k for k in new_modules.keys() & old_modules.keys()
            if new_modules[k] != old_modules[k]
        }

        if added or removed or changed:
            console.print("[bold]Changes detected:[/bold]")
            if added:
                console.print(f"  [green]+ {len(added)} new modules[/green]")
            if removed:
                console.print(f"  [red]- {len(removed)} removed modules[/red]")
            if changed:
                console.print(f"  [yellow]~ {len(changed)} risk level changes[/yellow]")
        else:
            console.print("[dim]No significant changes detected.[/dim]")

        # Risk distribution
        risk_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        for info in module_map.values():
            risk_counts[info.risk_level.value] = risk_counts.get(info.risk_level.value, 0) + 1

        console.print(f"\n[green]✓ Intelligence refreshed![/green]")
        console.print(f"[dim]Modules: {len(module_map)} | Posture: {security_posture.value}[/dim]")
        console.print(f"[dim]Risk: P0={risk_counts['P0']}, P1={risk_counts['P1']}, P2={risk_counts['P2']}, P3={risk_counts['P3']}[/dim]")
        return True

    return False


def refresh_command(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", "-f", help="Force regeneration even if recent"),
    intelligence: bool = typer.Option(True, "--intelligence/--no-intelligence", help="Refresh intelligence"),
    baseline: bool = typer.Option(False, "--baseline", "-b", help="Also refresh baseline (runs scan)"),
) -> None:
    """
    Refresh Warden intelligence and optionally baseline.

    This command regenerates the project intelligence used by CI scans
    without running a full initialization. Use this when your codebase
    structure has changed significantly.

    Examples:
        warden refresh              # Refresh intelligence only
        warden refresh --force      # Force refresh even if recent
        warden refresh --baseline   # Also update baseline (slow)
    """
    console.print("[bold cyan]🔄 Warden Refresh[/bold cyan]\n")

    root = Path.cwd()
    warden_dir = root / ".warden"

    if not warden_dir.exists():
        console.print("[red]Error: Warden not initialized. Run 'warden init' first.[/red]")
        raise typer.Exit(1)

    # Refresh intelligence
    if intelligence:
        console.print("[bold blue]🧠 Refreshing Intelligence...[/bold blue]")
        try:
            refreshed = asyncio.run(_refresh_intelligence_async(root, force))
            if not refreshed and not force:
                console.print("[dim]Tip: Use --force to regenerate anyway.[/dim]")
        except Exception as e:
            console.print(f"[red]Intelligence refresh failed: {e}[/red]")

    # Refresh baseline if requested
    if baseline:
        console.print("\n[bold blue]📉 Refreshing Baseline...[/bold blue]")
        console.print("[dim]Running scan to update baseline...[/dim]")
        try:
            from warden.cli.commands.init import _create_baseline_async
            config_path = warden_dir / "config.yaml"
            asyncio.run(_create_baseline_async(root, config_path))
        except Exception as e:
            console.print(f"[red]Baseline refresh failed: {e}[/red]")

    console.print("\n[green]✨ Refresh complete![/green]")
