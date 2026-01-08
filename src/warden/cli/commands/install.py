import typer
import yaml
from pathlib import Path
from rich.console import Console
from warden.services.package_manager.fetcher import FrameFetcher
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)
console = Console()

app = typer.Typer(help="Warden Package Manager - Install frames and rules.")

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
) -> None:
    """
    Install dependencies defined in warden.yaml.
    """
    if ctx.invoked_subcommand is None:
        install()

@app.command()
def install(
    force_update: bool = typer.Option(False, "--force-update", "-U", help="Force update dependencies, ignoring warden.lock")
) -> None:
    """
    Install all dependencies from warden.yaml.
    """
    config_path = Path.cwd() / "warden.yaml"
    if not config_path.exists():
        # Check for .warden/config.yaml as fallback (deprecated for dependencies)
        config_path = Path.cwd() / ".warden" / "config.yaml"
        if not config_path.exists():
            console.print("[red]Error: warden.yaml not found. Run 'warden init' first.[/red]")
            raise typer.Exit(1)

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    dependencies = config.get("dependencies", {})
    if not dependencies:
        console.print("[yellow]No dependencies found in warden.yaml[/yellow]")
        return

    warden_dir = Path.cwd() / ".warden"
    
    # Pass force_update flag to fetcher (no lockfile deletion needed)
    try:
        fetcher = FrameFetcher(warden_dir, force_update=force_update)
    except Exception as e:
        console.print(f"[red]Failed to initialize package manager: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"Installing {len(dependencies)} dependencies...")
    
    # Use fetch_all for atomic installation (transaction pattern)
    with console.status("[bold green]Fetching dependencies...[/bold green]"):
        try:
            success = fetcher.fetch_all(dependencies)
        except Exception as e:
            console.print(f"\n[red]Installation failed: {e}[/red]")
            raise typer.Exit(1)
    
    if not success:
        console.print("\n[red]Installation failed. Check logs for details.[/red]")
        raise typer.Exit(1)
    
    # Build results for summary (all succeeded if we got here)
    results = [(name, "Success", "green") for name in dependencies.keys()]

    # Rich Summary Panel
    from rich.panel import Panel
    from rich.table import Table

    summary_table = Table(show_header=False, box=None)
    for name, status, color in results:
        summary_table.add_row(name, f"[{color}]{status}[/{color}]")

    panel = Panel(
        summary_table,
        title="[bold]Installation Summary[/bold]",
        subtitle=f"[bold green]{len(dependencies)}/{len(dependencies)} packages installed[/bold green]",
        expand=False,
        border_style="cyan"
    )
    console.print("\n", panel)
    console.print("[bold green]✨ All packages installed successfully![/bold green]")
