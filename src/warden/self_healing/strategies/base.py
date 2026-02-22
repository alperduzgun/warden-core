"""Abstract base class for healer strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod

from warden.self_healing.models import DiagnosticResult, ErrorCategory


class IHealerStrategy(ABC):
    """Strategy interface for self-healing error handlers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique strategy identifier, e.g. 'import_healer'."""

    @property
    @abstractmethod
    def handles(self) -> list[ErrorCategory]:
        """Error categories this strategy can handle."""

    @property
    def priority(self) -> int:
        """Higher = runs first. Default 100."""
        return 100

    @abstractmethod
    async def can_heal(self, error: Exception, category: ErrorCategory) -> bool:
        """Quick check whether this strategy applies to the error."""

    @abstractmethod
    async def heal(self, error: Exception, context: str = "") -> DiagnosticResult:
        """Attempt to fix the error. Returns a DiagnosticResult."""
