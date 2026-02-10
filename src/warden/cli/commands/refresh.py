"""
Warden Refresh Command.

Regenerates project intelligence for CI optimization without running a full init.
"""

import asyncio
import typer
from pathlib import Path
from typing import Optional, Set
from rich.console import Console

console = Console()


async def _refresh_intelligence_async(
    root: Path,
    force: bool = False,
    module: Optional[str] = None,
    quick: bool = False
) -> bool:
    """
    Refresh project intelligence.

    Args:
        root: Project root directory.
        force: Force regeneration even if intelligence is recent.
        module: Specific module to refresh (None = all modules).
        quick: Quick mode - only analyze new/modified files.

    Returns:
        True if intelligence was regenerated, False otherwise.
    """
    from warden.analysis.services.intelligence_loader import IntelligenceLoader
    from warden.analysis.services.intelligence_saver import IntelligenceSaver
    from warden.analysis.application.project_purpose_detector import ProjectPurposeDetector
    from warden.analysis.domain.intelligence import SecurityPosture, ModuleInfo, RiskLevel
    from datetime import datetime, timedelta, timezone

    # Check if intelligence exists and is recent
    loader = IntelligenceLoader(root)
    saver = IntelligenceSaver(root)

    if not force and not quick and not module and saver.exists():
        last_modified = saver.get_last_modified()
        if last_modified:
            age = datetime.now(timezone.utc) - last_modified
            if age < timedelta(hours=24):
                console.print(f"[dim]Intelligence is recent ({age.seconds // 3600}h old). Use --force to regenerate.[/dim]")
                return False

    # Get all code files for analysis
    code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.cpp', '.c', '.h', '.dart'}
    all_files = [
        f for f in root.rglob("*")
        if f.is_file()
        and f.suffix in code_extensions
        and "node_modules" not in str(f)
        and ".venv" not in str(f)
        and ".git" not in str(f)
        and ".warden" not in str(f)
        and "__pycache__" not in str(f)
    ]

    if not all_files:
        console.print("[yellow]No code files found.[/yellow]")
        return False

    # Filter files based on module or quick mode
    files = all_files
    existing_file_set: Set[str] = set()

    # Load existing intelligence for comparison and filtering
    old_modules = {}
    if loader.load():
        old_modules = {name: info for name, info in loader.get_module_map().items()}
        intel = loader._intelligence
        if intel:
            # Track existing files for quick mode
            for mod_info in intel.modules.values():
                existing_file_set.add(mod_info.path)

    # Filter by module if specified
    if module:
        console.print(f"[dim]Filtering for module: {module}[/dim]")
        files = [
            f for f in all_files
            if module in str(f.relative_to(root))
        ]
        if not files:
            console.print(f"[yellow]No files found for module '{module}'[/yellow]")
            return False

    # Quick mode: only analyze new files not in existing intelligence
    if quick and existing_file_set:
        existing_paths = set()
        for mod_info in old_modules.values():
            mod_path = mod_info.path
            for f in all_files:
                rel_path = str(f.relative_to(root))
                if rel_path.startswith(mod_path):
                    existing_paths.add(str(f))

        new_files = [f for f in files if str(f) not in existing_paths]

        if not new_files:
            console.print("[dim]No new files found. Use --force for full refresh.[/dim]")
            return False

        console.print(f"[dim]Quick mode: analyzing {len(new_files)} new files (skipping {len(files) - len(new_files)} existing)[/dim]")
        files = new_files

    console.print(f"[dim]Analyzing {len(files)} files...[/dim]")

    # Detect project purpose and modules for the filtered files
    detector = ProjectPurposeDetector(root)
    purpose, architecture, new_module_map = await detector.detect_async(files, {})

    # For module-specific or quick refresh, merge with existing modules
    old_modules_dict = {name: info.risk_level.value for name, info in old_modules.items()}
    merged_module_map = {}

    if module or quick:
        # Start with existing modules
        merged_module_map = dict(old_modules)

        # Update/add the newly analyzed modules
        for name, info in new_module_map.items():
            merged_module_map[name] = info

        # Use existing purpose and posture if available
        if loader._intelligence:
            purpose = purpose or loader._intelligence.purpose
            architecture = architecture or ""
    else:
        # Full refresh - use new modules only
        merged_module_map = new_module_map

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
        module_map=merged_module_map,
        project_name=root.name
    )

    if success:
        # Show what changed
        new_modules_dict = {name: info.risk_level.value for name, info in merged_module_map.items()}
        added = set(new_modules_dict.keys()) - set(old_modules_dict.keys())
        removed = set(old_modules_dict.keys()) - set(new_modules_dict.keys()) if not (module or quick) else set()
        changed = {
            k for k in new_modules_dict.keys() & old_modules_dict.keys()
            if new_modules_dict[k] != old_modules_dict[k]
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
        for info in merged_module_map.values():
            risk_counts[info.risk_level.value] = risk_counts.get(info.risk_level.value, 0) + 1

        console.print(f"\n[green]✓ Intelligence refreshed![/green]")
        console.print(f"[dim]Modules: {len(merged_module_map)} | Posture: {security_posture.value}[/dim]")
        console.print(f"[dim]Risk: P0={risk_counts['P0']}, P1={risk_counts['P1']}, P2={risk_counts['P2']}, P3={risk_counts['P3']}[/dim]")
        return True

    return False


def refresh_command(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", "-f", help="Force regeneration even if recent"),
    no_intelligence: bool = typer.Option(False, "--no-intelligence", help="Skip intelligence refresh"),
    baseline: bool = typer.Option(False, "--baseline", "-b", help="Also refresh baseline (runs scan)"),
    module: Optional[str] = typer.Option(None, "--module", "-m", help="Refresh only specific module"),
    quick: bool = typer.Option(False, "--quick", "-q", help="Quick mode: only analyze new files"),
) -> None:
    """
    Refresh Warden intelligence and optionally baseline.

    This command regenerates the project intelligence used by CI scans
    without running a full initialization. Use this when your codebase
    structure has changed significantly.

    Examples:
        warden refresh                  # Refresh intelligence only
        warden refresh --force          # Force refresh even if recent
        warden refresh --no-intelligence # Skip intelligence refresh
        warden refresh --module auth    # Refresh only auth module
        warden refresh --quick          # Only analyze new files
        warden refresh --baseline       # Also update baseline (slow)
    """
    console.print("\n[bold cyan]🔄 Warden Refresh[/bold cyan]")

    root = Path.cwd()
    warden_dir = root / ".warden"

    if not warden_dir.exists():
        console.print("[red]Error: Warden not initialized. Run 'warden init' first.[/red]")
        raise typer.Exit(1)

    # Show mode
    mode_info = []
    if module:
        mode_info.append(f"module={module}")
    if quick:
        mode_info.append("quick")
    if force:
        mode_info.append("force")
    if mode_info:
        console.print(f"[dim]Mode: {', '.join(mode_info)}[/dim]\n")

    # Refresh intelligence
    if not no_intelligence:
        console.print("[bold blue]🧠 Refreshing Intelligence...[/bold blue]")
        try:
            refreshed = asyncio.run(_refresh_intelligence_async(root, force, module, quick))
            if not refreshed and not force and not quick:
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
