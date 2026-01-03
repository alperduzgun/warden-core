"""
Warden CLI
==========

The main entry point for the Warden Python CLI.
Provides commands for scanning, serving, and launching the interactive chat.
"""

import asyncio
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Optional, List
from datetime import datetime

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

# Internal imports
from warden.cli_bridge.bridge import WardenBridge
from warden.services.ipc_entry import main as ipc_main
from warden.services.grpc_entry import main as grpc_main

# Initialize Typer app
app = typer.Typer(
    name="warden",
    help="AI Code Guardian - Secure your code before production",
    add_completion=False,
    no_args_is_help=True
)

# Sub-app for server commands
serve_app = typer.Typer(name="serve", help="Start Warden backend services")
app.add_typer(serve_app, name="serve")

console = Console()


def _check_node_cli_installed() -> bool:
    """Check if warden-cli (Node.js) is installed and available."""
    # check for global executable
    if shutil.which("warden-cli"):
        return True
    
    # check if we are in dev environment where ../cli might exist
    # (This is a heuristic for local dev)
    dev_cli_path = Path(__file__).parents[2] / "cli"
    if dev_cli_path.exists() and (dev_cli_path / "package.json").exists():
        return True
        
    return False


@app.command()
def version():
    """Show Warden version info."""
    # from warden.config.config_manager import ConfigManager
    # Try to get version from package metadata if possible, else hardcode for now
    version = "0.1.0" 
    
    table = Table(show_header=False, box=None)
    table.add_row("Warden Core", f"[bold green]v{version}[/bold green]")
    table.add_row("Python", sys.version.split()[0])
    table.add_row("Platform", sys.platform)
    
    console.print(Panel(table, title="[bold blue]Warden[/bold blue]", expand=False))


@app.command()
def chat(
    ctx: typer.Context,
    dev: bool = typer.Option(False, "--dev", help="Run in dev mode (npm run start:raw)")
):
    """
    Launch the interactive AI Chat interface (Node.js required).
    
    This delegates to the 'warden-cli' executable or local dev script.
    """
    console.print("[bold blue]🚀 Launching Warden AI Chat...[/bold blue]")

    # 1. Check for local dev environment
    # This logic assumes we are running from src/warden/cli.py
    # so project root is 3 levels up -> warden-core/
    repo_root = Path(__file__).parents[2] 
    cli_dir = repo_root / "cli"

    if dev and cli_dir.exists():
        console.print("[dim]Using local dev version...[/dim]")
        try:
            # We need to install dependencies first if not node_modules
            if not (cli_dir / "node_modules").exists():
                console.print("[yellow]📦 Installing CLI dependencies...[/yellow]")
                subprocess.run(["npm", "install"], cwd=cli_dir, check=True)

            cmd = ["npm", "run", "start:raw"]
            subprocess.run(cmd, cwd=cli_dir)
            return
        except Exception as e:
            console.print(f"[bold red]Failed to launch dev CLI:[/bold red] {e}")
            raise typer.Exit(1)

    # 2. Check for globally installed binary
    if shutil.which("warden-cli"):
        try:
            subprocess.run(["warden-cli"] + ctx.args)
            return
        except KeyboardInterrupt:
            return
    
    # 3. Check for npx
    if shutil.which("npx"):
        try:
            console.print("[dim]warden-cli not found, trying npx @warden/cli...[/dim]")
            # Note: This assumes package is published as @warden/cli
            subprocess.run(["npx", "-y", "@warden/cli"] + ctx.args)
            return
        except KeyboardInterrupt:
            return

    console.print("[bold red]❌ Error:[/bold red] Warden Interactive CLI (Node.js) not found.")
    console.print("Please install it running: [green]npm install -g @warden/cli[/green]")
    raise typer.Exit(1)


@app.command()
def scan(
    path: str = typer.Argument(".", help="Path to scan (file or directory)"),
    frames: Optional[List[str]] = typer.Option(None, "--frame", "-f", help="Specific frames to run"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed logs"),
):
    """
    Run the full Warden pipeline on a file or directory.
    """
    # We defer import to avoid slow startup for other commands
    from warden.shared.infrastructure.logging import get_logger
    
    # Run async scan function
    try:
        exit_code = asyncio.run(_run_scan_async(path, frames, verbose))
        if exit_code != 0:
            raise typer.Exit(exit_code)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Scan interrupted by user[/yellow]")
        raise typer.Exit(130)


async def _run_scan_async(path: str, frames: Optional[List[str]], verbose: bool) -> int:
    """Async implementation of scan command."""
    
    console.print(f"[bold cyan]🛡️  Warden Scanner[/bold cyan]")
    console.print(f"[dim]Scanning: {path}[/dim]\n")

    # Initialize bridge
    bridge = WardenBridge(project_root=Path.cwd())
    
    # Setup stats tracking
    stats = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "total": 0
    }

    try:
        # Execute pipeline with streaming
        async for event in bridge.execute_pipeline_stream(
            file_path=path,
            frames=frames,
            verbose=verbose
        ):
            event_type = event.get("type")
            
            if event_type == "progress":
                evt = event['event']
                data = event.get('data', {})

                if evt == "phase_started":
                    console.print(f"[bold blue]▶ Phase:[/bold blue] {data.get('phase')}")
                
                elif evt == "frame_completed":
                    stats["total"] += 1
                    status = data.get('status', 'unknown')
                    name = data.get('frame_name', 'Unknown')
                    
                    if status == "passed":
                        stats["passed"] += 1
                        icon = "✅"
                        style = "green"
                    elif status == "failed":
                        stats["failed"] += 1
                        icon = "❌"
                        style = "red"
                    else:
                        stats["skipped"] += 1
                        icon = "⏭️"
                        style = "yellow"
                        
                    console.print(f"  {icon} [{style}]{name}[/{style}] ({data.get('duration', 0):.2f}s) - {data.get('issues_found', 0)} issues")

            elif event_type == "result":
                # Final results
                res = event['data']
                
                # Check critical findings
                critical = res.get('critical_findings', 0)
                
                table = Table(title="Scan Results")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="magenta")
                
                table.add_row("Total Frames", str(res.get('total_frames', 0)))
                table.add_row("Passed", f"[green]{res.get('frames_passed', 0)}[/green]")
                table.add_row("Failed", f"[red]{res.get('frames_failed', 0)}[/red]")
                table.add_row("Total Issues", str(res.get('total_findings', 0)))
                table.add_row("Critical Issues", f"[{'red' if critical > 0 else 'green'}]{critical}[/]")
                
                console.print("\n", table)
                
                if res.get('status') == 'success':
                    console.print(f"\n[bold green]✨ Scan Succeeded![/bold green]")
                    return 0
                else:
                    console.print(f"\n[bold red]💥 Scan Failed![/bold red]")
                    return 1

        return 0
        
    except Exception as e:
        console.print(f"[bold red]Error during scan:[/bold red] {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return 1


@serve_app.command("ipc")
def serve_ipc():
    """Start the IPC server (used by CLI/GUI integration)."""
    try:
        asyncio.run(ipc_main())
    except KeyboardInterrupt:
        pass


@serve_app.command("grpc")
def serve_grpc(port: int = typer.Option(50051, help="Port to listen on")):
    """Start the gRPC server (for C#/.NET integration)."""
    try:
        asyncio.run(grpc_main(port))
    except KeyboardInterrupt:
        pass


def main():
    """Entry point for setuptools."""
    app()


if __name__ == "__main__":
    app()
