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

from warden.core.pipeline.orchestrator import PipelineOrchestrator
from warden.core.analysis.analyzer import CodeAnalyzer
from warden.core.analysis.classifier import CodeClassifier
from warden.core.validation.executor import FrameExecutor
from warden.core.validation.frames.security import SecurityFrame
from warden.core.validation.frames.chaos import ChaosEngineeringFrame
from warden.core.validation.frames.fuzz import FuzzTestingFrame
from warden.core.validation.frames.property import PropertyTestingFrame
from warden.core.validation.frames.architectural import ArchitecturalConsistencyFrame
from warden.core.validation.frames.stress import StressTestingFrame

app = typer.Typer()
console = Console()


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
):
    """
    Scan entire project or directory

    Example:
        warden scan                          # Scan current directory for Python files
        warden scan ./src                    # Scan src directory
        warden scan -e .py -e .js            # Scan Python and JavaScript files
        warden scan --blocker-only           # Only check critical/high severity issues
        warden scan --max-files 50 -v        # Scan max 50 files with verbose output
    """
    asyncio.run(scan_directory(directory, extensions, exclude, blocker_only, verbose, max_files))


async def scan_directory(
    directory: str,
    extensions: List[str],
    exclude: List[str],
    blocker_only: bool,
    verbose: bool,
    max_files: int
):
    """Async scan logic"""

    dir_path = Path(directory).resolve()

    # Check if directory exists
    if not dir_path.exists():
        console.print(f"[red]Error:[/red] Directory not found: {directory}")
        raise typer.Exit(code=1)

    # Display header
    console.print(Panel.fit(
        f"[bold cyan]Warden Project Scan[/bold cyan]\n"
        f"[dim]Directory:[/dim] {dir_path}\n"
        f"[dim]Extensions:[/dim] {', '.join(extensions)}\n"
        f"[dim]Started:[/dim] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
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

    # Initialize components
    analyzer = CodeAnalyzer()
    classifier = CodeClassifier()

    # Register all validation frames
    frames = [
        SecurityFrame(),
        ChaosEngineeringFrame(),
        FuzzTestingFrame(),
        PropertyTestingFrame(),
        ArchitecturalConsistencyFrame(),
        StressTestingFrame(),
    ]
    executor = FrameExecutor(frames)

    orchestrator = PipelineOrchestrator(
        analyzer=analyzer,
        classifier=classifier,
        frame_executor=executor
    )

    # Track results
    file_results = []
    total_issues = 0
    critical_issues = 0
    high_issues = 0
    scores = []
    failed_count = 0

    start_time = datetime.now()

    # Scan files with progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console
    ) as progress:

        task = progress.add_task("[cyan]Scanning files...", total=len(files))

        for file_path in files:
            try:
                # Read file
                content = file_path.read_text()
                language = determine_language(str(file_path))

                # Update progress
                progress.update(
                    task,
                    description=f"[cyan]Scanning[/cyan] [blue]{file_path.name}[/blue]"
                )

                # Run pipeline
                result = await orchestrator.execute(
                    file_path=str(file_path),
                    file_content=content,
                    language=language
                )

                # Track results
                if result.success and result.analysis_result:
                    score = result.analysis_result.get("score", 0)
                    scores.append(score)

                    file_result = {
                        "file": str(file_path),
                        "score": score,
                        "total_issues": 0,
                        "blocker_failures": 0,
                        "critical_issues": 0,
                        "high_issues": 0,
                    }

                    if result.validation_summary:
                        # validation_summary has "results" array with JSON objects
                        frame_results = result.validation_summary.get("results", [])
                        blocker_failures_list = result.validation_summary.get("blockerFailures", [])

                        file_result["total_issues"] = sum(
                            len(fr.get("issues", [])) for fr in frame_results
                        )
                        file_result["blocker_failures"] = len(blocker_failures_list)

                        # Count critical and high issues
                        for frame_result in frame_results:
                            priority = frame_result.get("priority", "medium")
                            issues = frame_result.get("issues", [])

                            if priority.lower() == "critical":
                                file_result["critical_issues"] += len(issues)
                                critical_issues += len(issues)
                            elif priority.lower() == "high":
                                file_result["high_issues"] += len(issues)
                                high_issues += len(issues)

                        total_issues += file_result["total_issues"]

                    file_results.append(file_result)

                    # Show quick result if verbose
                    if verbose:
                        score_color = "green" if score >= 7 else "yellow" if score >= 5 else "red"
                        console.print(
                            f"  [{score_color}]{score:.1f}/10[/{score_color}] "
                            f"[dim]{file_path.relative_to(dir_path)}[/dim]"
                        )

                else:
                    failed_count += 1

            except Exception as e:
                failed_count += 1
                if verbose:
                    console.print(f"  [red]Failed:[/red] {file_path.name} - {str(e)}")

            progress.advance(task)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Display results
    console.print("\n")

    # Summary table
    avg_score = sum(scores) / len(scores) if scores else 0
    summary_table = create_scan_summary_table(
        total_files=len(files),
        analyzed_files=len(file_results),
        failed_files=failed_count,
        avg_score=avg_score,
        total_issues=total_issues,
        critical_issues=critical_issues,
        high_issues=high_issues,
        duration_sec=duration
    )
    console.print(summary_table)

    # Top issues table (if any issues found)
    if file_results and total_issues > 0:
        console.print()
        issues_table = create_file_results_table(file_results, limit=10)
        console.print(issues_table)

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
