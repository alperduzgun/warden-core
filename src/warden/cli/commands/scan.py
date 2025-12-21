"""
Scan Command - Scan entire project or directory
Modern CLI design inspired by QwenCode and Claude Code
"""

import asyncio
import sys
from pathlib import Path
from typing import List, Optional
from datetime import datetime

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TaskProgressColumn, TimeElapsedColumn, TimeRemainingColumn
)
from rich.table import Table
from rich.tree import Tree
from rich import box

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from warden.pipeline.application.enhanced_orchestrator import EnhancedPipelineOrchestrator
from warden.pipeline.domain.models import PipelineConfig, FrameRules
# Built-in frames are dynamically loaded via FrameRegistry
# No need to import explicitly (registry will handle discovery)
from warden.rules.infrastructure.yaml_loader import RulesYAMLLoader
from warden.rules.domain.models import CustomRule, CustomRuleViolation
from warden.shared.infrastructure.logging import get_logger

app = typer.Typer()
console = Console()
logger = get_logger(__name__)


async def load_custom_rules(rules_path: Path) -> tuple[list[CustomRule], dict[str, FrameRules]]:
    """
    Load custom rules from .warden/rules.yaml

    Args:
        rules_path: Path to rules.yaml file

    Returns:
        Tuple of (global_rules, frame_rules_dict)
    """
    if not rules_path.exists():
        logger.info("no_custom_rules_file", path=str(rules_path))
        return [], {}

    try:
        config = await RulesYAMLLoader.load_from_file(rules_path)

        # Extract global rules (rules referenced in global_rules section)
        # Build a lookup map
        rule_lookup = {rule.id: rule for rule in config.rules if rule.enabled}

        # Get only the global rules specified in global_rules section
        global_rules = [rule_lookup[rule_id] for rule_id in config.global_rules if rule_id in rule_lookup]

        # Get frame_rules from config (already parsed by loader)
        frame_rules = config.frame_rules

        logger.info(
            "custom_rules_loaded",
            path=str(rules_path),
            global_count=len(global_rules),
            frame_count=len(frame_rules),
        )

        return global_rules, frame_rules

    except Exception as e:
        logger.error("rules_loading_failed", path=str(rules_path), error=str(e))
        console.print(f"[yellow]Warning: Failed to load custom rules from {rules_path}: {e}[/yellow]")
        return [], {}


def determine_language(file_path: str) -> str:
    """Determine programming language from file extension"""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".java": "java",
        ".go": "go",
        ".cs": "csharp",
        ".dart": "dart",
        ".rs": "rust",
        ".cpp": "cpp",
        ".c": "c",
    }
    ext = Path(file_path).suffix.lower()
    return ext_map.get(ext, "unknown")


def discover_files(
    directory: Path,
    extensions: List[str],
    exclude_dirs: Optional[List[str]] = None
) -> List[Path]:
    """
    Discover files in directory with given extensions
    Respects common ignore patterns (node_modules, .git, __pycache__, etc.)
    """
    if exclude_dirs is None:
        exclude_dirs = [
            "node_modules", ".git", "__pycache__", "venv", ".venv",
            "dist", "build", ".next", ".nuxt", "target", "bin", "obj"
        ]

    files = []
    for ext in extensions:
        for file in directory.rglob(f"*{ext}"):
            # Check if file is in excluded directory
            if any(excluded in file.parts for excluded in exclude_dirs):
                continue
            if file.is_file():
                files.append(file)

    return sorted(files)


def create_scan_summary_table(
    total_files: int,
    analyzed_files: int,
    failed_files: int,
    avg_score: float,
    total_issues: int,
    critical_issues: int,
    high_issues: int,
    duration_sec: float
) -> Table:
    """Create a beautiful scan summary table"""
    table = Table(title="Scan Summary", box=box.ROUNDED, show_header=False)
    table.add_column("Metric", style="cyan bold", width=20)
    table.add_column("Value", style="white")

    table.add_row("Total Files", f"{total_files}")
    table.add_row("Analyzed", f"[green]{analyzed_files}[/green]")
    table.add_row("Failed", f"[red]{failed_files}[/red]")
    table.add_row("Average Score", f"[bold]{avg_score:.1f}/10[/bold]")
    table.add_row("Total Issues", f"{total_issues}")
    table.add_row("Critical Issues", f"[red bold]{critical_issues}[/red bold]")
    table.add_row("High Issues", f"[yellow]{high_issues}[/yellow]")
    table.add_row("Duration", f"{duration_sec:.2f}s")
    table.add_row("Files/Second", f"{analyzed_files / max(duration_sec, 0.001):.1f}")

    return table


def create_file_results_table(file_results: list, limit: int = 10) -> Table:
    """Create a table showing top file issues"""
    table = Table(
        title=f"Top {min(limit, len(file_results))} Files with Issues",
        box=box.ROUNDED
    )
    table.add_column("File", style="cyan", width=50)
    table.add_column("Score", width=10)
    table.add_column("Issues", width=10)
    table.add_column("Blockers", width=10)

    # Sort by number of blocker issues, then by total issues
    sorted_results = sorted(
        file_results,
        key=lambda x: (x.get("blocker_failures", 0), x.get("total_issues", 0)),
        reverse=True
    )

    for result in sorted_results[:limit]:
        score = result.get("score", 0)
        score_color = "green" if score >= 7 else "yellow" if score >= 5 else "red"

        file_path = str(Path(result["file"]).relative_to(Path.cwd()))

        table.add_row(
            file_path,
            f"[{score_color}]{score:.1f}/10[/{score_color}]",
            f"{result.get('total_issues', 0)}",
            f"[red]{result.get('blocker_failures', 0)}[/red]"
        )

    return table


@app.command()
def run(
    directory: str = typer.Argument(".", help="Directory to scan (default: current directory)"),
    config: str = typer.Option(
        ".warden/config.yaml", "--config", "-c",
        help="Path to config file (default: .warden/config.yaml)"
    ),
    extensions: List[str] = typer.Option(
        [".py"], "--ext", "-e",
        help="File extensions to scan (e.g., -e .py -e .js)"
    ),
    exclude: List[str] = typer.Option(
        [], "--exclude", "-x",
        help="Directories to exclude (in addition to defaults)"
    ),
    blocker_only: bool = typer.Option(False, "--blocker-only", help="Only check blocker issues"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
    max_files: int = typer.Option(100, "--max-files", help="Maximum files to scan"),
    rules_config: str = typer.Option(
        ".warden/rules.yaml",
        "--rules",
        "-r",
        help="Path to custom rules config file"
    ),
):
    """
    Scan entire project or directory

    Example:
        warden scan                          # Scan current directory for Python files
        warden scan ./src                    # Scan src directory
        warden scan -e .py -e .js            # Scan Python and JavaScript files
        warden scan --config custom.yaml     # Use custom config file
        warden scan --blocker-only           # Only check critical/high severity issues
        warden scan --max-files 50 -v        # Scan max 50 files with verbose output
        warden scan --rules custom_rules.yaml  # Use custom rules config
    """
    asyncio.run(scan_directory(directory, config, extensions, exclude, blocker_only, verbose, max_files, rules_config))


async def scan_directory(
    directory: str,
    config_path: str,
    extensions: List[str],
    exclude: List[str],
    blocker_only: bool,
    verbose: bool,
    max_files: int,
    rules_config: str
):
    """Async scan logic"""

    dir_path = Path(directory).resolve()

    # Check if directory exists
    if not dir_path.exists():
        console.print(f"[red]Error:[/red] Directory not found: {directory}")
        raise typer.Exit(code=1)

    # Load custom rules early
    rules_path = Path(rules_config)
    global_rules, frame_rules = await load_custom_rules(rules_path)

    # Display header
    rules_info = f"\n[dim]Custom Rules:[/dim] {len(global_rules)} loaded" if global_rules else ""
    console.print(Panel.fit(
        f"[bold cyan]Warden Project Scan[/bold cyan]\n"
        f"[dim]Directory:[/dim] {dir_path}\n"
        f"[dim]Extensions:[/dim] {', '.join(extensions)}\n"
        f"[dim]Started:[/dim] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{rules_info}",
        title="Scan Session",
        border_style="cyan"
    ))

    # Discover files
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    ) as progress:
        task = progress.add_task("[cyan]Discovering files...", total=None)

        default_excludes = [
            "node_modules", ".git", "__pycache__", "venv", ".venv",
            "dist", "build", ".next", ".nuxt", "target", "bin", "obj"
        ]
        all_excludes = default_excludes + list(exclude)

        files = discover_files(dir_path, extensions, all_excludes)

        if len(files) > max_files:
            console.print(f"\n[yellow]Warning:[/yellow] Found {len(files)} files, limiting to {max_files}")
            files = files[:max_files]

        progress.update(task, completed=True)

    if not files:
        console.print(f"[yellow]No files found with extensions: {', '.join(extensions)}[/yellow]")
        raise typer.Exit(code=0)

    console.print(f"\n[cyan]Found {len(files)} file(s) to scan[/cyan]\n")

    # Load frames from config file
    frames = []
    config_file = Path(config_path)

    if config_file.exists():
        try:
            import yaml
            with open(config_file) as f:
                config_data = yaml.safe_load(f)

            frame_names = config_data.get('frames', [])
            console.print(f"[cyan]Loading {len(frame_names)} frames from config: {config_path}[/cyan]")

            # Get all available frames (built-in + custom) dynamically
            from warden.validation.infrastructure.frame_registry import get_registry

            registry = get_registry()
            frame_map = registry.get_all_frames_as_dict()

            if verbose:
                console.print(f"[dim]  Discovered {len(frame_map)} frames (built-in + custom)[/dim]")
                console.print(f"[dim]  Available frames: {', '.join(frame_map.keys())}[/dim]")

            for frame_name in frame_names:
                if frame_name in frame_map:
                    frames.append(frame_map[frame_name]())
                    if verbose:
                        console.print(f"  [green]✓[/green] Loaded: {frame_name}")
                else:
                    console.print(f"  [yellow]⚠[/yellow]  Unknown frame: {frame_name} (not found in registry)")

        except Exception as e:
            console.print(f"[yellow]Warning: Failed to load config ({e}), using default frames[/yellow]")
            # Fallback: use registry to get built-in frames
            from warden.validation.infrastructure.frame_registry import get_registry
            registry = get_registry()
            frame_map = registry.get_all_frames_as_dict()
            # Use first 3 built-in frames as default
            default_frame_ids = ['security', 'chaos', 'architectural']
            frames = [frame_map[fid]() for fid in default_frame_ids if fid in frame_map]
    else:
        console.print(f"[yellow]Config not found: {config_path}, using default frames[/yellow]")
        # Fallback: use registry to get built-in frames
        from warden.validation.infrastructure.frame_registry import get_registry
        registry = get_registry()
        frame_map = registry.get_all_frames_as_dict()
        # Use first 3 built-in frames as default
        default_frame_ids = ['security', 'chaos', 'architectural']
        frames = [frame_map[fid]() for fid in default_frame_ids if fid in frame_map]

    if not frames:
        console.print("[red]Error: No frames loaded![/red]")
        raise typer.Exit(code=1)

    # Create pipeline config WITH custom rules
    pipeline_config = PipelineConfig(
        enable_discovery=False,  # We already discovered files manually
        enable_build_context=False,  # Not needed for simple scan
        enable_suppression=False,  # Can be enabled later
        global_rules=global_rules,  # ✅ NEW: Custom rules
        frame_rules=frame_rules,    # ✅ NEW: Frame-specific rules
    )

    # Create CodeFile objects from discovered files
    from warden.validation.domain.frame import CodeFile

    code_files = []
    console.print(f"[cyan]Preparing {len(files)} files for validation...[/cyan]\n")

    for file_path in files:
        try:
            content = file_path.read_text()
            language = determine_language(str(file_path))

            code_file = CodeFile(
                path=str(file_path),
                content=content,
                language=language,
                framework=None,
                size_bytes=len(content.encode('utf-8')),
            )
            code_files.append(code_file)
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to load {file_path.name}: {e}[/yellow]")

    if not code_files:
        console.print("[red]Error: No files could be loaded![/red]")
        raise typer.Exit(code=1)

    # Create enhanced orchestrator with frames
    orchestrator = EnhancedPipelineOrchestrator(
        frames=frames,
        config=pipeline_config
    )

    # Run validation
    start_time = datetime.now()

    console.print(f"[cyan]Running {len(frames)} validation frames on {len(code_files)} files...[/cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=False
    ) as progress:
        task = progress.add_task("[cyan]Validating files...", total=None)

        # Execute all frames on all files
        result = await orchestrator.execute(code_files)

        progress.update(task, completed=True)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Process results
    total_issues = result.total_findings
    file_results = []
    critical_issues = 0
    high_issues = 0
    scores = [7.0] * len(code_files)  # Default score (frames don't provide scores)
    failed_count = 0

    # Extract issues from frame results
    for frame_result in result.frame_results:
        if frame_result.is_blocker and not frame_result.passed:
            critical_issues += frame_result.issues_found
        else:
            # Non-blocker issues counted as high priority
            high_issues += frame_result.issues_found

    # Display results
    console.print("\n")

    # Summary table
    avg_score = sum(scores) / len(scores) if scores else 0
    summary_table = create_scan_summary_table(
        total_files=len(files),
        analyzed_files=len(code_files),
        failed_files=failed_count,
        avg_score=avg_score,
        total_issues=total_issues,
        critical_issues=critical_issues,
        high_issues=high_issues,
        duration_sec=duration
    )
    console.print(summary_table)

    # Show frame results if verbose
    if verbose and result.frame_results:
        console.print("\n[cyan]Frame Results:[/cyan]")
        for frame_result in result.frame_results:
            status_icon = "✓" if frame_result.passed else "✗"
            status_color = "green" if frame_result.passed else "red"
            console.print(
                f"  [{status_color}]{status_icon}[/{status_color}] "
                f"{frame_result.frame_name}: {frame_result.issues_found} issues"
            )

    # Final status
    console.print()
    if critical_issues > 0:
        console.print(Panel(
            f"[red bold]CRITICAL: {critical_issues} critical issue(s) found![/red bold]\n"
            "[yellow]Immediate action required![/yellow]",
            border_style="red"
        ))
        sys.exit(1)
    elif avg_score >= 7 and high_issues == 0:
        console.print(Panel(
            "[green bold]Project quality is excellent![/green bold]\n"
            f"[dim]Average score: {avg_score:.1f}/10[/dim]",
            border_style="green"
        ))
        sys.exit(0)
    elif high_issues > 0:
        console.print(Panel(
            f"[yellow]Warning: {high_issues} high-priority issue(s) found[/yellow]\n"
            f"[dim]Average score: {avg_score:.1f}/10[/dim]",
            border_style="yellow"
        ))
        sys.exit(0)
    else:
        console.print(Panel(
            f"[blue]Scan complete - {total_issues} issue(s) found[/blue]\n"
            f"[dim]Average score: {avg_score:.1f}/10[/dim]",
            border_style="blue"
        ))
        sys.exit(0)


if __name__ == "__main__":
    app()
