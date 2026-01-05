import sys
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from warden.cli.utils import get_installed_version

console = Console()

def version_command():
    """Show Warden version info."""
    version = get_installed_version()
    
    table = Table(show_header=False, box=None)
    table.add_row("Warden Core", f"[bold green]v{version}[/bold green]")
    table.add_row("Python", sys.version.split()[0])
    table.add_row("Platform", sys.platform)
    
    console.print(Panel(table, title="[bold blue]Warden[/bold blue]", expand=False))
