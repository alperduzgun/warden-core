"""
Warden CLI - AI Code Guardian
Main entry point for the command-line interface

Usage:
    warden validate <file>       # Validate single file
    warden scan <directory>      # Scan directory
    warden report               # Generate report
    warden config show          # Show configuration
"""

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from warden.cli.commands import scan, report, infrastructure, validate

app = typer.Typer(
    name="warden",
    help="Warden - AI Code Guardian for comprehensive code validation",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()

# Register commands
app.add_typer(validate.app, name="validate", help="Run validation strategies on code files")
app.add_typer(scan.app, name="scan", help="Scan entire project or directory")
app.add_typer(report.app, name="report", help="Generate validation reports")
app.add_typer(infrastructure.app, name="infrastructure", help="Infrastructure management (Git hooks, CI templates, Docker)")


@app.command()
def version():
    """Show Warden version information"""
    console.print(Panel.fit(
        "[bold cyan]Warden Core[/bold cyan]\n"
        "[dim]Version:[/dim] 0.1.0\n"
        "[dim]Python Backend - Phase 1 & 2 Complete[/dim]\n",
        title="About Warden",
        border_style="cyan"
    ))


@app.command()
def config(
    show: bool = typer.Option(False, "--show", help="Show current configuration")
):
    """Manage Warden configuration"""
    if show:
        console.print("[yellow]Configuration management coming soon...[/yellow]")
    else:
        console.print("[yellow]Use --show to display current configuration[/yellow]")


@app.command()
def chat():
    """Start Warden TUI - Modern terminal interface"""
    from warden.tui import WardenTUI

    app_instance = WardenTUI()
    app_instance.run()


def main():
    """Main entry point"""
    # If no arguments, start Textual TUI
    if len(sys.argv) == 1:
        console.print("[cyan]🛡️  Starting Warden TUI...[/cyan]")
        console.print("[dim]Use 'warden --help' for command-line options[/dim]\n")
        chat()
    else:
        app()


if __name__ == "__main__":
    main()
