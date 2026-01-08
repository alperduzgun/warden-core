"""
Warden CLI
==========

The main entry point for the Warden Python CLI.
Provides commands for scanning, serving, and launching the interactive chat.
"""

import typer
from rich.console import Console

# Command Logic Imports
from warden.cli.commands.version import version_command
from warden.cli.commands.chat import chat_command
from warden.cli.commands.status import status_command
from warden.cli.commands.scan import scan_command
from warden.cli.commands.init import init_command
from warden.cli.commands.serve import serve_app
from warden.cli.commands.search import search_command, index_command
from warden.cli.commands.install import install as install_command
from warden.cli.commands.doctor import doctor as doctor_command
from warden.cli.commands.update import update_command

# Initialize Typer app
app = typer.Typer(
    name="warden",
    help="AI Code Guardian - Secure your code before production",
    add_completion=False,
    no_args_is_help=True
)

# Register Sub-Apps
app.add_typer(serve_app, name="serve")

# Register Top-Level Commands
app.command(name="version")(version_command)
app.command(name="chat")(chat_command)
app.command(name="status")(status_command)
app.command(name="scan")(scan_command)
app.command(name="init")(init_command)
app.command(name="search")(search_command)
app.command(name="index")(index_command)
app.command(name="install")(install_command)
app.command(name="doctor")(doctor_command)
app.command(name="update")(update_command)

def main():
    """Entry point for setuptools."""
    try:
        app()
    except Exception as e:
        console = Console()
        console.print(f"[bold red]💥 Fatal Error:[/bold red] {e}")
        # Only print trace text if verbose/debug encoded in env or args, 
        # but since Typer handles args, we might just exit. 
        # For now, clean exit is better than crash.
        raise typer.Exit(1)

if __name__ == "__main__":
    app()
