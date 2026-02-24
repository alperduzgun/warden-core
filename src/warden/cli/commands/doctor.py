from pathlib import Path

import typer
from rich.console import Console

from warden.services.package_manager.doctor import WardenDoctor

app = typer.Typer(help="Warden Doctor - Diagnostic tool for project health.")
console = Console()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """
    Run diagnostics on the current Warden project.
    """
    if ctx.invoked_subcommand is None:
        doctor()


@app.command()
def doctor(
    fix: bool = typer.Option(False, "--fix", help="Attempt to fix detected issues automatically"),
) -> None:
    """
    Verify project health and readiness.

    Use --fix to attempt automatic repair (e.g. pull missing Ollama models).
    """
    console.print("[bold cyan]🩺 Warden Doctor[/bold cyan] - Running diagnostics...")

    doc = WardenDoctor(Path.cwd())
    success = doc.run_all()

    if fix:
        console.print("\n[bold blue]🔧 --fix: attempting repairs...[/bold blue]")
        fixed = doc.fix_env()
        if fixed:
            console.print("[green]✓ Issues resolved. Re-running checks...[/green]\n")
            success = doc.run_all()

    if success:
        console.print("\n[bold green]✅ Your project is healthy and ready for a scan![/bold green]")
        console.print("[dim](Warnings may limit some advanced features, but core scanning is operational)[/dim]")
    else:
        console.print("\n[bold red]⛔ Critical issues found. Please fix the errors above to proceed.[/bold red]")
        if not fix:
            console.print("[dim]💡 Try running: warden doctor --fix[/dim]")
        raise typer.Exit(1)
