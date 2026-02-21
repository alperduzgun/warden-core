"""Tests for HealerRegistry."""

from __future__ import annotations

from warden.self_healing.models import DiagnosticResult, ErrorCategory
from warden.self_healing.registry import HealerRegistry
from warden.self_healing.strategies.base import IHealerStrategy


class DummyHealer(IHealerStrategy):
    def __init__(self, name: str, handles: list[ErrorCategory], priority: int = 100):
        self._name = name
        self._handles = handles
        self._priority = priority

    @property
    def name(self) -> str:
        return self._name

    @property
    def handles(self) -> list[ErrorCategory]:
        return self._handles

    @property
    def priority(self) -> int:
        return self._priority

    async def can_heal(self, error, category):
        return True

    async def heal(self, error, context=""):
        return DiagnosticResult(fixed=True, strategy_used=self._name)


class TestHealerRegistry:
    def test_register_and_get(self):
        HealerRegistry.clear()
        healer = DummyHealer("test_healer", [ErrorCategory.UNKNOWN])
        HealerRegistry.register(healer)
        assert HealerRegistry.get("test_healer") is healer
        HealerRegistry.clear()

    def test_get_nonexistent_returns_none(self):
        HealerRegistry.clear()
        assert HealerRegistry.get("nonexistent") is None
        HealerRegistry.clear()

    def test_get_for_category_sorted_by_priority(self):
        HealerRegistry.clear()
        low = DummyHealer("low", [ErrorCategory.UNKNOWN], priority=50)
        high = DummyHealer("high", [ErrorCategory.UNKNOWN], priority=200)
        HealerRegistry.register(low)
        HealerRegistry.register(high)

        result = HealerRegistry.get_for_category(ErrorCategory.UNKNOWN)
        assert [s.name for s in result] == ["high", "low"]
        HealerRegistry.clear()

    def test_get_for_category_filters_correctly(self):
        HealerRegistry.clear()
        import_h = DummyHealer("imp", [ErrorCategory.IMPORT_ERROR])
        timeout_h = DummyHealer("tout", [ErrorCategory.TIMEOUT])
        HealerRegistry.register(import_h)
        HealerRegistry.register(timeout_h)

        result = HealerRegistry.get_for_category(ErrorCategory.IMPORT_ERROR)
        assert len(result) == 1
        assert result[0].name == "imp"
        HealerRegistry.clear()

    def test_clear_removes_all(self):
        HealerRegistry.clear()
        HealerRegistry.register(DummyHealer("x", [ErrorCategory.UNKNOWN]))
        assert len(HealerRegistry.all()) == 1
        HealerRegistry.clear()
        assert len(HealerRegistry.all()) == 0

    def test_all_returns_registered(self):
        HealerRegistry.clear()
        HealerRegistry.register(DummyHealer("a", [ErrorCategory.UNKNOWN]))
        HealerRegistry.register(DummyHealer("b", [ErrorCategory.TIMEOUT]))
        assert len(HealerRegistry.all()) == 2
        HealerRegistry.clear()
