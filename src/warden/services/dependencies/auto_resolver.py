"""
Generic runtime dependency auto-resolver.

Provides utilities for any phase/frame/executor to check and auto-install
missing Python packages at runtime. Reuses the existing DependencyManager.
"""

from __future__ import annotations

import importlib
import sys

from warden.self_healing.strategies.import_healer import IMPORT_TO_PIP
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Derive pip-name -> import-name map from the canonical IMPORT_TO_PIP
# (single source of truth in import_healer.py)
PACKAGE_MAP: dict[str, str] = {v: k for k, v in IMPORT_TO_PIP.items()}


def _is_importable(import_name: str) -> bool:
    """Check if a module can be imported without actually importing it."""
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False


def _resolve_import_name(pip_name: str) -> str:
    """Get the Python import name for a pip package name."""
    return PACKAGE_MAP.get(pip_name, pip_name.replace("-", "_"))


def require_package(pip_name: str, import_name: str | None = None) -> bool:
    """
    Check if a package is available, auto-install if missing.

    Args:
        pip_name: The pip install name (e.g. "sentence-transformers")
        import_name: The Python import name if different (e.g. "sentence_transformers").
                     Auto-resolved from PACKAGE_MAP if not provided.

    Returns:
        True if the package is available (was already installed or just installed).
    """
    resolved_import = import_name or _resolve_import_name(pip_name)

    if _is_importable(resolved_import):
        return True

    logger.info("package_missing_attempting_install", pip_name=pip_name)

    try:
        from rich.console import Console

        console = Console()
        console.print(f"[dim]Installing missing dependency: {pip_name}...[/dim]")
    except ImportError:
        console = None

    try:
        from warden.services.dependencies.dependency_manager import DependencyManager

        mgr = DependencyManager()

        # Synchronous check+install using subprocess directly
        # (require_package is called from sync contexts often)
        import subprocess

        cmd = [sys.executable, "-m", "pip", "install", pip_name, "--quiet"]
        if not mgr.is_venv:
            cmd.append("--break-system-packages")

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=120,
        )

        if result.returncode == 0:
            # Invalidate import caches so the freshly installed package is found
            importlib.invalidate_caches()
            logger.info("package_auto_installed", pip_name=pip_name)
            if console:
                console.print(f"[green]Installed {pip_name}[/green]")
            return True

        stderr = result.stderr.decode("utf-8", errors="replace")[:200]
        logger.error("package_install_failed", pip_name=pip_name, stderr=stderr)
        if console:
            console.print(f"[red]Failed to install {pip_name}[/red]")
        return False

    except Exception as e:
        logger.error("package_install_error", pip_name=pip_name, error=str(e))
        return False


async def resolve_with_llm(error: Exception, context: str = "") -> DiagnosticResult:  # noqa: F821
    """
    Delegate to SelfHealingDiagnostic for LLM-powered resolution.

    Bridge function that keeps auto_resolver as the public API entry point
    while delegating complex diagnosis to the self-healing service.

    Args:
        error: The runtime exception to diagnose.
        context: Optional context string describing what was happening.

    Returns:
        DiagnosticResult with diagnosis and fix status.
    """
    from warden.self_healing import DiagnosticResult, SelfHealingOrchestrator

    try:
        diagnostic = SelfHealingOrchestrator()
        return await diagnostic.diagnose_and_fix(error, context=context)
    except Exception as e:
        logger.error("resolve_with_llm_failed", error=str(e))
        return DiagnosticResult(
            diagnosis=f"Self-healing unavailable: {e}",
            suggested_action="Run 'warden doctor' to check your setup.",
        )


def ensure_dependencies(packages: list[str], context: str = "") -> list[str]:
    """
    Check and auto-install missing packages. Returns list of still-missing packages.

    Args:
        packages: List of pip package names to ensure are installed.
        context: Optional context string for log messages (e.g. "scan command").

    Returns:
        List of package names that are still missing after install attempts.
    """
    still_missing: list[str] = []

    for pip_name in packages:
        import_name = _resolve_import_name(pip_name)
        if _is_importable(import_name):
            continue

        if context:
            logger.info("dependency_missing_for_context", pip_name=pip_name, context=context)

        if not require_package(pip_name, import_name):
            still_missing.append(pip_name)

    return still_missing
