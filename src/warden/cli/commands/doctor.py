import typer
from pathlib import Path
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
def doctor() -> None:
    """
    Verify project health and readiness.
    """
    console.print("[bold cyan]🩺 Warden Doctor[/bold cyan] - Running diagnostics...")
    
    doc = WardenDoctor(Path.cwd())
    success = doc.run_all()
    
    if success:
        console.print("\n[bold green]✅ Your project is healthy and ready for a scan![/bold green]")
        console.print("[dim](Warnings may limit some advanced features, but core scanning is operational)[/dim]")
    else:
        console.print("\n[bold red]⛔ Critical issues found. Please fix the errors above to proceed.[/bold red]")
        raise typer.Exit(1)
