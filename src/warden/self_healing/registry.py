"""Strategy registry for healer lookup by error category."""

from __future__ import annotations

from typing import TYPE_CHECKING

from warden.self_healing.models import ErrorCategory

if TYPE_CHECKING:
    from warden.self_healing.strategies.base import IHealerStrategy


class HealerRegistry:
    """Central registry mapping error categories to healer strategies."""

    _strategies: dict[str, IHealerStrategy] = {}

    @classmethod
    def register(cls, strategy: IHealerStrategy) -> None:
        """Register a strategy instance by its name."""
        cls._strategies[strategy.name] = strategy

    @classmethod
    def get_for_category(cls, category: ErrorCategory) -> list[IHealerStrategy]:
        """Return matching strategies sorted by priority descending."""
        matching = [s for s in cls._strategies.values() if category in s.handles]
        return sorted(matching, key=lambda s: s.priority, reverse=True)

    @classmethod
    def get(cls, name: str) -> IHealerStrategy | None:
        """Look up a strategy by name."""
        return cls._strategies.get(name)

    @classmethod
    def all(cls) -> list[IHealerStrategy]:
        """Return all registered strategies."""
        return list(cls._strategies.values())

    @classmethod
    def clear(cls) -> None:
        """Remove all registered strategies. Useful for testing."""
        cls._strategies = {}
