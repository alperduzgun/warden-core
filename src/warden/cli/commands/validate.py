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
from warden.pipeline.domain.models import PipelineConfig
from warden.validation.domain.frame import CodeFile
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

    # Register all validation frames
    frames = [
        SecurityFrame(),
        ChaosFrame(),
        ArchitecturalConsistencyFrame(),
    ]

    # Create code file object
    code_file = CodeFile(
        path=file_path,
        content=content,
        language=language,
        framework=None,
        size_bytes=len(content.encode('utf-8')),
    )

    # Create pipeline config and orchestrator
    config = PipelineConfig(
        fail_fast=True,
        enable_discovery=False,
        enable_build_context=False,
        enable_suppression=False,
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    # Run validation frames
    console.print(f"\n[cyan]Running {len(frames)} validation frames...[/cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=False
    ) as progress:
        task = progress.add_task("[cyan]Validating...", total=None)

        # Execute frames on the code file
        result = await orchestrator.execute([code_file])

        progress.update(task, completed=True)

    # Display results
    console.print("\n")

    # Create summary table
    summary_table = create_validation_summary_table(
        total_frames=result.total_frames,
        passed_frames=result.frames_passed,
        failed_frames=result.frames_failed,
        blocker_failures=0,  # Count blocker issues
        duration_ms=result.duration * 1000  # Convert to ms
    )
    console.print(summary_table)

    # Show frame details if verbose
    if verbose:
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
    if result.frames_failed == 0:
        console.print(Panel(
            "[green bold]All validation frames passed![/green bold]",
            border_style="green"
        ))
        sys.exit(0)
    elif result.critical_findings > 0:
        console.print(Panel(
            f"[red bold]BLOCKER: {result.critical_findings} critical issue(s) found![/red bold]\n"
            "[yellow]Fix blocker issues before proceeding.[/yellow]",
            border_style="red"
        ))
        sys.exit(1)
    else:
        console.print(Panel(
            f"[yellow]Warning: {result.frames_failed} frame(s) failed[/yellow]",
            border_style="yellow"
        ))
        sys.exit(0)


if __name__ == "__main__":
    app()
