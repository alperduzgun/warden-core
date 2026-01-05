import shutil
import subprocess
import platform
import typer
from pathlib import Path
from rich.console import Console

console = Console()

class GitHubCli:
    """
    Wrapper for GitHub CLI (gh) operations with resilience and cross-platform support.
    """
    CMD_TIMEOUT = 60  # seconds

    @staticmethod
    def is_installed() -> bool:
        return shutil.which("gh") is not None

    @staticmethod
    def install_interactive() -> bool:
        """
        Interactive installation for gh CLI.
        Returns True if successful, False otherwise.
        """
        system = platform.system().lower()
        console.print(f"[yellow]GitHub CLI (gh) not found on {system}.[/yellow]")
        
        install_cmd = None
        pkg_manager = "Manual"

        if system == "darwin":  # macOS
            if shutil.which("brew"):
                install_cmd = ["brew", "install", "gh"]
                pkg_manager = "Homebrew"
        elif system == "windows":  # Windows
            if shutil.which("winget"):
                install_cmd = ["winget", "install", "--id", "GitHub.cli", "--accept-source-agreements", "--accept-package-agreements"]
                pkg_manager = "WinGet"
            elif shutil.which("choco"):
                install_cmd = ["choco", "install", "gh"]
                pkg_manager = "Chocolatey"
        elif system == "linux":
            if shutil.which("snap"):
                install_cmd = ["snap", "install", "gh"]
                pkg_manager = "Snap"

        if install_cmd:
            if typer.confirm(f"Do you want to install it via {pkg_manager}?", default=True):
                try:
                    console.print(f"[dim]Installing via {pkg_manager}... (Timeout: {GitHubCli.CMD_TIMEOUT * 2}s)[/dim]")
                    subprocess.run(install_cmd, check=True, timeout=GitHubCli.CMD_TIMEOUT * 2)
                    console.print("✅ [green]GitHub CLI installed successfully.[/green]")
                    
                    if not shutil.which("gh"):
                        console.print("[red]Installation appeared successful but 'gh' is not in PATH yet.[/red]")
                        if system == "windows":
                            console.print("[yellow]Hint: You may need to restart your terminal/PowerShell.[/yellow]")
                        return False
                    return True
                except subprocess.TimeoutExpired:
                    console.print(f"[red]Installation timed out.[/red]")
                except subprocess.CalledProcessError:
                    console.print(f"[red]Failed to install gh via {pkg_manager}.[/red]")
                except Exception as e:
                    console.print(f"[red]Error during installation:[/red] {e}")
        
        GitHubCli._print_manual_instructions()
        return False

    @staticmethod
    def _print_manual_instructions():
        console.print("Automatic installation not available. Please install manually:")
        console.print("  [bold]Mac:[/bold] brew install gh")
        console.print("  [bold]Windows:[/bold] winget install GitHub.cli")
        console.print("  [bold]Linux:[/bold] https://cli.github.com/manual/")

    @staticmethod
    def ensure_auth() -> bool:
        """
        Checks auth status, prompts for login if needed.
        """
        try:
            subprocess.run(["gh", "auth", "status"], check=True, capture_output=True, timeout=10)
            return True
        except subprocess.TimeoutExpired:
            console.print("[red]Auth check timed out.[/red]")
            return False
        except subprocess.CalledProcessError:
            console.print("\n[yellow]⚠️  You are not logged into GitHub CLI.[/yellow]")
            if typer.confirm("Do you want to log in now?", default=True):
                try:
                    subprocess.run(["gh", "auth", "login"], check=True)  # Interactive
                    return True
                except Exception:
                    return False
            return False

    @staticmethod
    def download_artifact(artifact_name: str, target_dir: Path) -> bool:
        """
        Downloads an artifact to the target directory.
        Uses chaos principles (timeouts, atomic check).
        """
        try:
            subprocess.run(
                ["gh", "run", "download", "--name", artifact_name, "--dir", str(target_dir)],
                check=True,
                capture_output=True,
                timeout=GitHubCli.CMD_TIMEOUT
            )
            return True
        except subprocess.TimeoutExpired:
            console.print(f"[red]Download timed out after {GitHubCli.CMD_TIMEOUT}s.[/red]")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to download artifact.[/red] (Maybe no successful run yet?)")
        except Exception as e:
            console.print(f"[red]Error downloading artifact:[/red] {e}")
            
        return False
