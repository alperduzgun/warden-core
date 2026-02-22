"""ImportError / ModuleNotFoundError healer — pip install missing packages."""

from __future__ import annotations

import importlib
import re
import subprocess
import sys

from warden.self_healing.classifier import ErrorClassifier
from warden.self_healing.models import DiagnosticResult, ErrorCategory
from warden.self_healing.registry import HealerRegistry
from warden.self_healing.strategies.base import IHealerStrategy
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Known import-name to pip-name mappings
IMPORT_TO_PIP: dict[str, str] = {
    "tiktoken": "tiktoken",
    "sentence_transformers": "sentence-transformers",
    "chromadb": "chromadb",
    "grpc": "grpcio",
    "qdrant_client": "qdrant-client",
    "yaml": "pyyaml",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "jose": "python-jose",
    "jwt": "PyJWT",
    "magic": "python-magic",
    "gi": "pygobject",
    "attr": "attrs",
    "dateutil": "python-dateutil",
    "lxml": "lxml",
    "numpy": "numpy",
    "pandas": "pandas",
    "torch": "torch",
    "transformers": "transformers",
}


class ImportHealer(IHealerStrategy):
    """Heals ImportError/ModuleNotFoundError by pip-installing missing packages."""

    @property
    def name(self) -> str:
        return "import_healer"

    @property
    def handles(self) -> list[ErrorCategory]:
        return [ErrorCategory.IMPORT_ERROR, ErrorCategory.MODULE_NOT_FOUND]

    @property
    def priority(self) -> int:
        return 200

    async def can_heal(self, error: Exception, category: ErrorCategory) -> bool:
        module_name = ErrorClassifier.extract_module_name(error)
        return module_name is not None

    async def heal(self, error: Exception, context: str = "") -> DiagnosticResult:
        module_name = ErrorClassifier.extract_module_name(error)
        if not module_name:
            return DiagnosticResult(
                diagnosis="Could not extract module name from error.",
                error_category=ErrorCategory.IMPORT_ERROR,
                strategy_used=self.name,
            )

        # 1. Fast path: static mapping
        pip_name = IMPORT_TO_PIP.get(module_name)

        # 2. LLM path: ask LLM for the correct pip package name
        if pip_name is None:
            pip_name = await _ask_llm_pip_name(module_name)
            if pip_name:
                logger.info("llm_resolved_pip_name", module=module_name, pip_name=pip_name)

        # 3. Fallback: assume module name == pip name
        if pip_name is None:
            pip_name = module_name

        installed = _try_pip_install(pip_name)

        if installed:
            return DiagnosticResult(
                fixed=True,
                diagnosis=f"Auto-installed missing package: {pip_name}",
                packages_installed=[pip_name],
                should_retry=True,
                error_category=ErrorCategory.IMPORT_ERROR,
                strategy_used=self.name,
            )

        return DiagnosticResult(
            diagnosis=f"Failed to install {pip_name}.",
            suggested_action=f"Try manually: pip install {pip_name}",
            error_category=ErrorCategory.IMPORT_ERROR,
            strategy_used=self.name,
        )


_PIP_NAME_PROMPT = """What is the correct pip package name to install the Python module "{module_name}"?
Respond with ONLY the pip package name, nothing else. Example: pyyaml
If you don't know, respond with: UNKNOWN"""


async def _ask_llm_pip_name(module_name: str) -> str | None:
    """Ask the LLM fast tier for the pip package name of a Python module."""
    try:
        import asyncio

        from warden.llm.factory import create_client

        client = create_client()

        if not await client.is_available_async():
            return None

        prompt = _PIP_NAME_PROMPT.format(module_name=module_name)

        response = await asyncio.wait_for(
            client.complete_async(
                prompt,
                system_prompt="You are a Python package resolution assistant. Respond with only the pip package name.",
                use_fast_tier=True,
            ),
            timeout=8.0,
        )

        if response and response.content:
            raw = response.content.strip()
            # Reject multi-word responses — valid pip names are single tokens
            if " " in raw or "\n" in raw:
                logger.debug("llm_pip_name_multi_word_rejected", raw=raw[:50])
                return None
            # Validate: must look like a valid pip package name (2+ chars, starts with letter)
            if raw and raw != "UNKNOWN" and len(raw) >= 2 and re.match(r"^[a-zA-Z][a-zA-Z0-9_\-\[\].]*$", raw):
                return raw

    except Exception as e:
        logger.debug("llm_pip_name_resolution_failed", module=module_name, error=str(e))

    return None


def _try_pip_install(pip_name: str) -> bool:
    """Attempt to pip install a package. Returns True on success."""
    if not pip_name or not pip_name.strip():
        logger.warning("rejected_empty_package_name")
        return False

    if not re.match(r"^[a-zA-Z0-9_\-\[\].]+$", pip_name):
        logger.warning("rejected_unsafe_package_name", pip_name=pip_name)
        return False

    logger.info("self_healing_pip_install", pip_name=pip_name)

    try:
        from rich.console import Console

        console = Console()
        console.print(f"[dim]Self-healing: installing {pip_name}...[/dim]")
    except ImportError:
        console = None

    try:
        from warden.services.dependencies.dependency_manager import DependencyManager

        mgr = DependencyManager()
        cmd = [sys.executable, "-m", "pip", "install", pip_name, "--quiet"]
        if not mgr.is_venv:
            cmd.append("--break-system-packages")

        result = subprocess.run(cmd, capture_output=True, timeout=120)

        if result.returncode == 0:
            importlib.invalidate_caches()
            logger.info("self_healing_package_installed", pip_name=pip_name)
            if console:
                console.print(f"[green]Self-healing: installed {pip_name}[/green]")
            return True

        stderr = result.stderr.decode("utf-8", errors="replace")[:200]
        logger.error("self_healing_install_failed", pip_name=pip_name, stderr=stderr)
        return False

    except subprocess.TimeoutExpired:
        logger.error("self_healing_install_timeout", pip_name=pip_name, timeout_s=120)
        return False
    except Exception as e:
        logger.error("self_healing_install_error", pip_name=pip_name, error=str(e))
        return False


HealerRegistry.register(ImportHealer())
