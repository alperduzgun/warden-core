"""Provider/external service healer — fast-path diagnosis without LLM."""

from __future__ import annotations

from warden.self_healing.models import DiagnosticResult, ErrorCategory
from warden.self_healing.registry import HealerRegistry
from warden.self_healing.strategies.base import IHealerStrategy


class ProviderHealer(IHealerStrategy):
    """Provides fast-path diagnosis for external service and timeout errors."""

    @property
    def name(self) -> str:
        return "provider_healer"

    @property
    def handles(self) -> list[ErrorCategory]:
        return [
            ErrorCategory.EXTERNAL_SERVICE,
            ErrorCategory.TIMEOUT,
            ErrorCategory.PERMISSION_ERROR,
            ErrorCategory.PROVIDER_UNAVAILABLE,
        ]

    @property
    def priority(self) -> int:
        return 100

    async def can_heal(self, error: Exception, category: ErrorCategory) -> bool:
        return category in self.handles

    async def heal(self, error: Exception, context: str = "") -> DiagnosticResult:
        category = _infer_category(error)

        if category == ErrorCategory.TIMEOUT:
            return DiagnosticResult(
                diagnosis="Operation timed out. This is typically a network or service availability issue.",
                suggested_action="Check your network connection and LLM provider status. Run 'warden doctor'.",
                error_category=category,
                strategy_used=self.name,
            )

        if category == ErrorCategory.PERMISSION_ERROR:
            return DiagnosticResult(
                diagnosis="Permission denied. Check file/directory permissions.",
                suggested_action="Ensure you have read/write access to the project directory.",
                error_category=category,
                strategy_used=self.name,
            )

        if category == ErrorCategory.PROVIDER_UNAVAILABLE:
            return DiagnosticResult(
                diagnosis="LLM provider is unavailable. No configured provider could be reached.",
                suggested_action="Run 'warden doctor' to check provider status. Consider switching providers.",
                error_category=category,
                strategy_used=self.name,
            )

        # EXTERNAL_SERVICE default
        return DiagnosticResult(
            diagnosis="External service error detected. An API or service Warden depends on is unavailable.",
            suggested_action="Run 'warden doctor' to check provider status and configuration.",
            error_category=category,
            strategy_used=self.name,
        )


def _infer_category(error: Exception) -> ErrorCategory:
    """Infer the specific category from the error for diagnosis message."""
    if isinstance(error, PermissionError):
        return ErrorCategory.PERMISSION_ERROR

    error_str = str(error).lower()
    error_type = type(error).__name__

    if "timed out" in error_str or "timeout" in error_type.lower():
        return ErrorCategory.TIMEOUT

    if "provider" in error_str and "unavailable" in error_str:
        return ErrorCategory.PROVIDER_UNAVAILABLE

    return ErrorCategory.EXTERNAL_SERVICE


HealerRegistry.register(ProviderHealer())
