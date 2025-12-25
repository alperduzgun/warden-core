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

# Add project root to path for imports (if not already there)
project_root = Path(__file__).parent.parent.parent.parent
project_root_str = str(project_root)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

from warden.cli.commands import scan, report, infrastructure, validate, rules, frame
from warden.cli import providers, init

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
    """Start Warden Interactive CLI - Modern terminal interface (Node.js)"""
    import subprocess
    from pathlib import Path

    # Find warden-cli executable
    project_root = Path(__file__).parent.parent.parent.parent
    cli_executable = project_root / "cli" / "dist" / "cli.js"

    if not cli_executable.exists():
        console.print("[red]Error: Warden CLI not built. Please run:[/red]")
        console.print("[yellow]  cd cli && npm install && npm run build[/yellow]")
        raise typer.Exit(1)

    console.print("[cyan]🛡️  Starting Warden Interactive CLI...[/cyan]")

    try:
        # Run the Node.js CLI
        subprocess.run(["node", str(cli_executable)], check=True)
    except KeyboardInterrupt:
        console.print("\n[cyan]Warden CLI stopped.[/cyan]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error running CLI: {e}[/red]")
        raise typer.Exit(1)


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
    # If no arguments, start Node.js CLI
    if len(sys.argv) == 1:
        console.print("[cyan]🛡️  Starting Warden Interactive CLI...[/cyan]")
        console.print("[dim]Use 'warden --help' for command-line options[/dim]\n")
        chat()
    else:
        app()


if __name__ == "__main__":
    main()
