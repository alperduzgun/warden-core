import sys
import subprocess
import importlib.metadata
import asyncio
from typing import List, Optional
from rich.console import Console
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)
console = Console()

class DependencyManager:
    """
    Manages runtime dependencies with resilience and safety checks.
    Follows 'Fail Fast' and 'Strict' principles.
    """

    @property
    def is_venv(self) -> bool:
        """Check if running inside a virtual environment."""
        return (hasattr(sys, 'real_prefix') or 
                (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))

    def is_installed(self, package_name: str) -> bool:
        """Check if a package is installed via importlib."""
        try:
            importlib.metadata.version(package_name)
            return True
        except importlib.metadata.PackageNotFoundError:
            return False

    async def install_packages(self, packages: List[str], timeout: int = 60) -> bool:
        """
        idempotently install packages.
        Returns True if all packages are installed (either previously or just now).
        """
        missing = [pkg for pkg in packages if not self.is_installed(pkg)]
        
        if not missing:
            logger.debug("all_dependencies_met", packages=packages)
            return True

        # Safety Check: PEP 668
        if not self.is_venv:
            logger.warning("system_python_detected", action="block_install")
            console.print("[yellow]⚠️  System detected (PEP 668). Cannot auto-install dependencies.[/yellow]")
            console.print(f"[dim]Missing: {', '.join(missing)}[/dim]")
            console.print(f"\n[bold]Please run manually:[/bold] [cyan]pip install {' '.join(missing)} --break-system-packages[/cyan]\n")
            return False

        logger.info("installing_dependencies", packages=missing)
        
        try:
            # Run pip install in subprocess with timeout
            # asyncio.to_thread is not enough for subprocess timeout control, usage of asyncio.create_subprocess_exec is better
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", *missing,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                logger.error("dependency_install_timeout", packages=missing, timeout=timeout)
                console.print(f"[red]❌ Installation timed out after {timeout}s[/red]")
                return False

            if process.returncode != 0:
                logger.error("dependency_install_failed", return_code=process.returncode, stderr=stderr.decode())
                console.print(f"[red]❌ Installation failed[/red]")
                return False

            logger.info("dependency_install_success", packages=missing)
            return True

        except Exception as e:
            logger.error("dependency_manager_error", error=str(e))
            console.print(f"[red]Installation error: {e}[/red]")
            return False
