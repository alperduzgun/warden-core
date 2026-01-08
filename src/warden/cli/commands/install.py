import typer
import yaml
from typing import Optional, List, Tuple
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
    frame_id: Optional[str] = typer.Argument(None, help="Specific frame ID to install from the Hub"),
    force_update: bool = typer.Option(False, "--force-update", "-U", help="Force update dependencies, ignoring warden.lock")
) -> None:
    """
    Install dependencies from warden.yaml or a specific frame from the Hub.
    """
    warden_dir = Path.cwd() / ".warden"
    
    try:
        fetcher = FrameFetcher(warden_dir, force_update=force_update)
    except Exception as e:
        console.print(f"[red]Failed to initialize package manager: {e}[/red]")
        raise typer.Exit(1)

    installed_items = []

    if frame_id:
        # Install specific frame
        console.print(f"Installing [bold cyan]{frame_id}[/bold cyan] from Warden Hub...")
        with console.status(f"[bold green]Fetching {frame_id}...[/bold green]"):
            success = fetcher.fetch(frame_id, "latest")
            if success:
                fetcher._commit_lock_updates()
                installed_items.append(frame_id)
    else:
        # Install all from warden.yaml
        config_path = Path.cwd() / "warden.yaml"
        if not config_path.exists():
            config_path = Path.cwd() / ".warden" / "config.yaml"
            if not config_path.exists():
                console.print("[red]Error: warden.yaml not found. Run 'warden init' first.[/red]")
                raise typer.Exit(1)

        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        dependencies = config.get("dependencies", {})
        console.print(f"Installing {len(dependencies)} dependencies...")
        
        with console.status("[bold green]Fetching dependencies...[/bold green]"):
            success = fetcher.fetch_all(dependencies)
            if success:
                installed_items.extend(dependencies.keys())
    
    if not success:
        console.print("\n[red]Installation failed. Check logs for details.[/red]")
        raise typer.Exit(1)
    
    console.print("\n[bold green]✨ Done![/bold green]")

    # Rich Summary Panel
    if installed_items:
        from rich.panel import Panel
        from rich.table import Table

        summary_table = Table(show_header=False, box=None)
        for name in installed_items:
            summary_table.add_row(name, "[green]Success[/green]")

        panel = Panel(
            summary_table,
            title="[bold]Installation Summary[/bold]",
            subtitle=f"[bold green]{len(installed_items)} packages installed[/bold green]",
            expand=False,
            border_style="cyan"
        )
        console.print("\n", panel)
    
    console.print("[bold green]✨ All requested packages installed successfully![/bold green]")
