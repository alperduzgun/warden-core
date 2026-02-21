"""ModelNotFoundError healer — auto-pull Ollama models."""

from __future__ import annotations

import re
import subprocess

from warden.self_healing.models import DiagnosticResult, ErrorCategory
from warden.self_healing.registry import HealerRegistry
from warden.self_healing.strategies.base import IHealerStrategy
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Pattern to extract model name from error messages
_MODEL_PATTERNS = [
    re.compile(r"model ['\"]?([a-zA-Z0-9_.:\-/]+)['\"]? not found", re.IGNORECASE),
    re.compile(r"unknown model[:\s]+['\"]?([a-zA-Z0-9_.:\-/]+)['\"]?", re.IGNORECASE),
    re.compile(r"pull.*model[:\s]+['\"]?([a-zA-Z0-9_.:\-/]+)['\"]?", re.IGNORECASE),
    re.compile(r"404.*['\"]?([a-zA-Z0-9_.:\-/]+)['\"]?", re.IGNORECASE),
]


class ModelHealer(IHealerStrategy):
    """Heals ModelNotFoundError by running `ollama pull <model>`."""

    @property
    def name(self) -> str:
        return "model_healer"

    @property
    def handles(self) -> list[ErrorCategory]:
        return [ErrorCategory.MODEL_NOT_FOUND]

    @property
    def priority(self) -> int:
        return 200

    async def can_heal(self, error: Exception, category: ErrorCategory) -> bool:
        return _extract_model_name(error) is not None

    async def heal(self, error: Exception, context: str = "") -> DiagnosticResult:
        model_name = _extract_model_name(error)
        if not model_name:
            return DiagnosticResult(
                diagnosis="Could not extract model name from error.",
                error_category=ErrorCategory.MODEL_NOT_FOUND,
                strategy_used=self.name,
            )

        pulled = _try_ollama_pull(model_name)
        if pulled:
            return DiagnosticResult(
                fixed=True,
                diagnosis=f"Auto-pulled missing model: {model_name}",
                models_pulled=[model_name],
                should_retry=True,
                error_category=ErrorCategory.MODEL_NOT_FOUND,
                strategy_used=self.name,
            )

        return DiagnosticResult(
            diagnosis=f"Failed to pull model {model_name}.",
            suggested_action=f"Try manually: ollama pull {model_name}",
            error_category=ErrorCategory.MODEL_NOT_FOUND,
            strategy_used=self.name,
        )


def _extract_model_name(error: Exception) -> str | None:
    """Extract model name from error message."""
    error_msg = str(error)
    for pattern in _MODEL_PATTERNS:
        match = pattern.search(error_msg)
        if match:
            return match.group(1)

    # Check if error has a model attribute (some custom exceptions)
    model = getattr(error, "model", None) or getattr(error, "model_name", None)
    if model and isinstance(model, str):
        return model

    return None


def _try_ollama_pull(model_name: str) -> bool:
    """Attempt to pull an Ollama model. Returns True on success."""
    if not model_name or not model_name.strip():
        logger.warning("rejected_empty_model_name")
        return False

    # Reject leading dash (--flag injection) and path traversal (..)
    if model_name.startswith("-") or ".." in model_name:
        logger.warning("rejected_unsafe_model_name", model_name=model_name)
        return False

    if not re.match(r"^[a-zA-Z0-9_.:\-/]+$", model_name):
        logger.warning("rejected_unsafe_model_name", model_name=model_name)
        return False

    logger.info("self_healing_ollama_pull", model_name=model_name)

    try:
        from rich.console import Console

        console = Console()
        console.print(f"[dim]Self-healing: pulling model {model_name}...[/dim]")
    except ImportError:
        console = None

    try:
        result = subprocess.run(  # noqa: S603, S607
            ["ollama", "pull", model_name],
            capture_output=True,
            timeout=60,
        )

        if result.returncode == 0:
            logger.info("self_healing_model_pulled", model_name=model_name)
            if console:
                console.print(f"[green]Self-healing: pulled {model_name}[/green]")
            return True

        stderr = result.stderr.decode("utf-8", errors="replace")[:200]
        logger.error("self_healing_pull_failed", model_name=model_name, stderr=stderr)
        return False

    except FileNotFoundError:
        logger.error("ollama_not_installed")
        return False
    except subprocess.TimeoutExpired:
        logger.error("self_healing_pull_timeout", model_name=model_name, timeout_s=60)
        return False
    except Exception as e:
        logger.error("self_healing_pull_error", model_name=model_name, error=str(e))
        return False


HealerRegistry.register(ModelHealer())
