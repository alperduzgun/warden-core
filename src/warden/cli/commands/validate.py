"""
Validate Command - Run validation strategies on code files
Inspired by QwenCode and Claude Code CLI design
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.syntax import Syntax
from rich import box

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from warden.pipeline.application.orchestrator import PipelineOrchestrator
from warden.analyzers.discovery.analyzer import CodeAnalyzer
from warden.analyzers.discovery.classifier import CodeClassifier
from warden.validation.domain.executor import FrameExecutor
from warden.validation.frames.security import SecurityFrame
from warden.validation.frames.chaos import ChaosFrame
from warden.validation.frames.architectural import ArchitecturalConsistencyFrame

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


def create_validation_summary_table(
    total_frames: int,
    passed_frames: int,
    failed_frames: int,
    blocker_failures: int,
    duration_ms: float
) -> Table:
    """Create a beautiful summary table"""
    table = Table(title="Validation Summary", box=box.ROUNDED, show_header=False)
    table.add_column("Metric", style="cyan bold", width=20)
    table.add_column("Value", style="white")

    table.add_row("Total Frames", f"{total_frames}")
    table.add_row("Passed", f"[green]{passed_frames}[/green]")
    table.add_row("Failed", f"[red]{failed_frames}[/red]")
    table.add_row("Blocker Failures", f"[red bold]{blocker_failures}[/red bold]")
    table.add_row("Duration", f"{duration_ms:.2f}ms")

    return table


def create_frame_results_table(frame_results: list) -> Table:
    """Create a table showing frame execution results"""
    table = Table(title="Frame Results", box=box.ROUNDED)
    table.add_column("Status", width=8)
    table.add_column("Frame", style="cyan", width=30)
    table.add_column("Priority", width=10)
    table.add_column("Duration", width=12)
    table.add_column("Issues", width=8)

    for result in frame_results:
        # result is a dict with camelCase keys
        passed = result.get("passed", False)
        name = result.get("name", "Unknown")
        priority = result.get("priority", "medium")
        execution_time_ms = result.get("executionTimeMs", 0)
        issues = result.get("issues", [])

        status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        priority_color = {
            "critical": "red bold",
            "high": "yellow",
            "medium": "blue",
            "low": "dim"
        }.get(priority.lower(), "white")

        table.add_row(
            status,
            name,
            f"[{priority_color}]{priority.upper()}[/{priority_color}]",
            f"{execution_time_ms:.2f}ms",
            f"{len(issues)}"
        )

    return table


def display_frame_issues(frame_results: list):
    """Display detailed issues from each frame"""
    for result in frame_results:
        # result is a dict with camelCase keys
        passed = result.get("passed", False)
        name = result.get("name", "Unknown")
        issues = result.get("issues", [])

        if not passed and issues:
            console.print(f"\n[red bold]Issues in {name}:[/red bold]")
            for i, issue in enumerate(issues[:5], 1):  # Show max 5 issues
                console.print(f"  {i}. {issue}")
            if len(issues) > 5:
                console.print(f"  [dim]... and {len(issues) - 5} more issues[/dim]")


@app.command()
def run(
    file_path: str = typer.Argument(..., help="Path to the file to validate"),
    format: str = typer.Option("console", "--format", "-f", help="Output format (console, json)"),
    blocker_only: bool = typer.Option(False, "--blocker-only", help="Only check blocker issues"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """
    Run validation strategies on a code file

    Example:
        warden validate myfile.py
        warden validate myfile.py --blocker-only
        warden validate myfile.py --verbose
    """
    asyncio.run(validate_file(file_path, format, blocker_only, verbose))


async def validate_file(
    file_path: str,
    format: str,
    blocker_only: bool,
    verbose: bool
):
    """Async validation logic"""

    # Check if file exists
    if not Path(file_path).exists():
        console.print(f"[red]Error:[/red] File not found: {file_path}")
        raise typer.Exit(code=1)

    # Read file content
    try:
        content = Path(file_path).read_text()
    except Exception as e:
        console.print(f"[red]Error reading file:[/red] {e}")
        raise typer.Exit(code=1)

    language = determine_language(file_path)

    # Display header
    console.print(Panel.fit(
        f"[bold cyan]Warden Code Validation[/bold cyan]\n"
        f"[dim]File:[/dim] {file_path}\n"
        f"[dim]Language:[/dim] {language}\n"
        f"[dim]Size:[/dim] {len(content)} bytes",
        title="Validation Session",
        border_style="cyan"
    ))

    # Initialize components (similar to scan.py)
    analyzer = CodeAnalyzer(llm_factory=None, use_llm=False)  # LLM disabled for validate command
    classifier = CodeClassifier()

    # Register all validation frames
    frames = [
        SecurityFrame(),
        ChaosFrame(),
        ArchitecturalConsistencyFrame(),
    ]
    executor = FrameExecutor(frames)

    # Create orchestrator
    orchestrator = PipelineOrchestrator(
        analyzer=analyzer,
        classifier=classifier,
        frame_executor=executor
    )

    # Run pipeline with progress indicator
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True
    ) as progress:

        task = progress.add_task("[cyan]Running validation pipeline...", total=None)

        result = await orchestrator.execute(
            file_path=file_path,
            file_content=content,
            language=language
        )

        progress.update(task, completed=True)

    # Display results
    console.print()

    if not result.success:
        console.print("[red]Pipeline failed![/red]")
        if result.message:
            console.print(f"[red]Error:[/red] {result.message}")

    # Analysis results
    if result.analysis_result:
        score = result.analysis_result.get("score", 0)
        console.print(f"[cyan]Analysis Score:[/cyan] [bold]{score:.1f}/10[/bold]")
        if verbose and result.analysis_result.get("metrics"):
            console.print(f"[dim]Metrics:[/dim] {result.analysis_result['metrics']}")

    # Classification results
    if result.classification_result and verbose:
        console.print(f"\n[cyan]Recommended Frames:[/cyan]")
        for frame in result.classification_result.get("recommendedFrames", []):
            console.print(f"  - {frame}")

    # Validation results
    if result.validation_summary:
        console.print()

        # Summary table
        total_frames = result.validation_summary.get("totalFrames", 0)
        passed_frames = result.validation_summary.get("passedFrames", 0)
        failed_frames = result.validation_summary.get("failedFrames", 0)
        blocker_failures_list = result.validation_summary.get("blockerFailures", [])
        duration_ms = result.validation_summary.get("durationMs", 0)

        summary_table = create_validation_summary_table(
            total_frames=total_frames,
            passed_frames=passed_frames,
            failed_frames=failed_frames,
            blocker_failures=len(blocker_failures_list),
            duration_ms=duration_ms
        )
        console.print(summary_table)

        # Frame results table (results is array of JSON objects)
        frame_results = result.validation_summary.get("results", [])
        if frame_results:
            console.print()
            frame_table = create_frame_results_table(frame_results)
            console.print(frame_table)

            # Display detailed issues
            if verbose or len(blocker_failures_list) > 0:
                display_frame_issues(frame_results)

    # Final status
    console.print()
    if result.success and result.validation_summary:
        failed_frames = result.validation_summary.get("failedFrames", 0)
        blocker_failures_list = result.validation_summary.get("blockerFailures", [])

        if failed_frames == 0:
            console.print(Panel(
                "[green bold]All validation frames passed![/green bold]",
                border_style="green"
            ))
            sys.exit(0)
        elif len(blocker_failures_list) > 0:
            console.print(Panel(
                f"[red bold]BLOCKER: {len(blocker_failures_list)} critical issue(s) found![/red bold]\n"
                "[yellow]Pipeline stopped. Fix blocker issues before proceeding.[/yellow]",
                border_style="red"
            ))
            sys.exit(1)
        else:
            console.print(Panel(
                f"[yellow]Warning: {failed_frames} frame(s) failed[/yellow]",
                border_style="yellow"
            ))
            sys.exit(0)
    else:
        console.print(Panel(
            "[red]Validation pipeline failed![/red]",
            border_style="red"
        ))
        sys.exit(1)


if __name__ == "__main__":
    app()
