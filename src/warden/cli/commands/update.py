import typer
import asyncio
from rich.console import Console
from warden.services.package_manager.registry import RegistryClient
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)
console = Console()

def update_command() -> None:
    """
    Update the Warden Hub catalog from remote Git repository.
    """
    registry = RegistryClient()
    
    console.print("[bold cyan]🔄 Updating Warden Hub catalog...[/bold cyan]")
    
    async def run_sync():
        return await registry.sync()
        
    success = asyncio.run(run_sync())
    
    if success:
        console.print("\n[bold green]✨ Catalog updated successfully![/bold green]")
        # Show a summary of available frames
        frames = registry.search()
        core_count = len([f for f in frames if f.get("tier") == "core"])
        optional_count = len(frames) - core_count
        console.print(f"Found [bold]{len(frames)}[/bold] frames ({core_count} core, {optional_count} optional).")
    else:
        console.print("\n[bold red]❌ Failed to update catalog.[/bold red]")
        console.print("Check your internet connection and Git configuration.")
        raise typer.Exit(1)
