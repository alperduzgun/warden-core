"""Tests for ProviderHealer strategy."""

from __future__ import annotations

import pytest

from warden.self_healing.models import ErrorCategory
from warden.self_healing.strategies.provider_healer import ProviderHealer


class TestProviderHealer:
    def setup_method(self):
        self.healer = ProviderHealer()

    def test_name(self):
        assert self.healer.name == "provider_healer"

    def test_handles(self):
        assert ErrorCategory.EXTERNAL_SERVICE in self.healer.handles
        assert ErrorCategory.TIMEOUT in self.healer.handles
        assert ErrorCategory.PERMISSION_ERROR in self.healer.handles
        assert ErrorCategory.PROVIDER_UNAVAILABLE in self.healer.handles

    def test_priority(self):
        assert self.healer.priority == 100

    @pytest.mark.asyncio
    async def test_can_heal_timeout(self):
        assert await self.healer.can_heal(TimeoutError(), ErrorCategory.TIMEOUT) is True

    @pytest.mark.asyncio
    async def test_can_heal_unknown_false(self):
        assert await self.healer.can_heal(Exception(), ErrorCategory.UNKNOWN) is False

    @pytest.mark.asyncio
    async def test_heal_timeout(self):
        err = TimeoutError("connection timed out")
        result = await self.healer.heal(err)
        assert result.fixed is False
        assert "timed out" in result.diagnosis.lower()
        assert result.strategy_used == "provider_healer"

    @pytest.mark.asyncio
    async def test_heal_permission_error(self):
        err = PermissionError("Permission denied")
        result = await self.healer.heal(err)
        assert "Permission denied" in result.diagnosis
        assert result.strategy_used == "provider_healer"

    @pytest.mark.asyncio
    async def test_heal_external_service(self):
        err = ConnectionRefusedError("Connection refused")
        result = await self.healer.heal(err)
        assert "External service" in result.diagnosis
        assert result.strategy_used == "provider_healer"

    @pytest.mark.asyncio
    async def test_heal_provider_unavailable(self):
        err = Exception("provider ollama unavailable")
        result = await self.healer.heal(err)
        assert "unavailable" in result.diagnosis.lower()
        assert result.strategy_used == "provider_healer"
