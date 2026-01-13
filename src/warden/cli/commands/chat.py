import typer
import shutil
import subprocess
import sys
from pathlib import Path
from rich.console import Console

console = Console()

def chat_command(
    ctx: typer.Context,
    dev: bool = typer.Option(False, "--dev", help="Run in dev mode (npm run start:raw)")
):
    """
    Launch the interactive AI Chat interface (Node.js required).
    
    This delegates to the 'warden-cli' executable or local dev script.
    """
    console.print("[bold blue]🚀 Launching Warden AI Chat...[/bold blue]")

    # 1. Check for local dev environment
    # This logic assumes we are running from src/warden/cli/commands/chat.py
    # so project root is 4 levels up -> warden-core/
    # (src/warden/cli/commands/chat.py -> parents[0]=commands, [1]=cli, [2]=warden, [3]=src, [4]=warden-core)
    
    # Actually logic in main.py was parents[2] because it was src/warden/main.py.
    # Here parents[4] is safe if cwd() is unreliable, but usually we refer to relative path from file.
    
    # Let's double check path logic.
    # main.py: Path(__file__).parents[2] / "cli"
    #   src/warden/main.py -> parents[0]=warden, parents[1]=src, parents[2]=warden-core.
    #   Wait, parents[0] is the dir main.py is in?
    #   Path("src/warden/main.py").parents[0] -> src/warden
    #   parents[1] -> src
    #   parents[2] -> . (root)
    
    # chat.py: src/warden/cli/commands/chat.py
    #   parents[0] -> commands
    #   parents[1] -> cli
    #   parents[2] -> warden
    #   parents[3] -> src
    #   parents[4] -> . (root)
    
    repo_root = Path(__file__).parents[4] 
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
