"""
Warden CLI - AI Code Guardian
Main entry point for the command-line interface

Usage:
    warden init                 # Initialize project configuration
    warden validate <file>       # Validate single file
    warden scan <directory>      # Scan directory
    warden report               # Generate report
    warden config show          # Show configuration
    warden providers list       # List installed AST providers
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

from warden.cli.commands import scan, report, infrastructure, validate, init,rules, frame
from warden.cli import providers

app = typer.Typer(
    name="warden",
    help="Warden - AI Code Guardian for comprehensive code validation",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()

# Register commands
app.add_typer(init.app, name="init", help="Initialize Warden configuration for a project")
app.add_typer(validate.app, name="validate", help="Run validation strategies on code files")
app.add_typer(scan.app, name="scan", help="Scan entire project or directory")
app.add_typer(report.app, name="report", help="Generate validation reports")
app.add_typer(infrastructure.app, name="infrastructure", help="Infrastructure management (Git hooks, CI templates, Docker)")
app.add_typer(rules.app, name="rules", help="Manage custom validation rules")
app.add_typer(frame.app, name="frame", help="Manage custom validation frames")
app.add_typer(providers.app, name="providers", help="Manage AST providers for different programming languages")


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


@app.command()
def ink(
    socket_path: Optional[str] = typer.Option(
        None,
        "--socket",
        "-s",
        help="Unix socket path for IPC (default: stdio)"
    ),
):
    """Launch Ink-based interactive CLI with IPC bridge"""
    import asyncio
    import subprocess
    from pathlib import Path

    console.print("[cyan]Starting Warden Ink CLI...[/cyan]")

    # Check if Node CLI exists
    project_root = Path(__file__).parent.parent.parent.parent
    cli_dir = project_root / "cli"

    if not cli_dir.exists():
        console.print("[red]Error: Ink CLI not found at cli/[/red]")
        console.print("[yellow]Please run: npm install in the cli directory[/yellow]")
        raise typer.Exit(1)

    # Start IPC server
    async def run_bridge():
        from warden.cli_bridge.server import run_ipc_server

        transport = "socket" if socket_path else "stdio"
        console.print(f"[dim]Starting IPC bridge (transport: {transport})...[/dim]")

        try:
            await run_ipc_server(
                transport=transport,
                socket_path=socket_path or "/tmp/warden-ipc.sock"
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down IPC bridge...[/yellow]")
        except Exception as e:
            console.print(f"[red]IPC bridge error: {e}[/red]")
            raise typer.Exit(1)

    # Run the bridge
    try:
        asyncio.run(run_bridge())
    except KeyboardInterrupt:
        console.print("\n[cyan]Ink CLI stopped.[/cyan]")


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
