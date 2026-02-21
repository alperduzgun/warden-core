"""Tests for SelfHealingOrchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.self_healing.models import DiagnosticResult, ErrorCategory
from warden.self_healing.orchestrator import SelfHealingOrchestrator, reset_heal_attempts


class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_import_error_static_fix(self, tmp_path):
        orch = SelfHealingOrchestrator(project_root=tmp_path)
        err = ModuleNotFoundError("No module named 'tiktoken'")

        with patch(
            "warden.self_healing.strategies.import_healer._try_pip_install",
            return_value=True,
        ):
            result = await orch.diagnose_and_fix(err, context="scan")

        assert result.fixed is True
        assert result.should_retry is True
        assert result.strategy_used == "import_healer"

    @pytest.mark.asyncio
    async def test_timeout_error_fast_path(self, tmp_path):
        orch = SelfHealingOrchestrator(project_root=tmp_path)
        err = TimeoutError("connection timed out")

        result = await orch.diagnose_and_fix(err)

        assert result.fixed is False
        assert result.error_category == ErrorCategory.TIMEOUT
        assert result.strategy_used == "provider_healer"

    @pytest.mark.asyncio
    async def test_external_service_error(self, tmp_path):
        orch = SelfHealingOrchestrator(project_root=tmp_path)
        err = ConnectionRefusedError("Connection refused")

        result = await orch.diagnose_and_fix(err)

        assert result.fixed is False
        assert result.error_category == ErrorCategory.EXTERNAL_SERVICE
        assert result.strategy_used == "provider_healer"

    @pytest.mark.asyncio
    async def test_permission_error(self, tmp_path):
        orch = SelfHealingOrchestrator(project_root=tmp_path)
        err = PermissionError("Permission denied")

        result = await orch.diagnose_and_fix(err)

        assert result.fixed is False
        assert result.error_category == ErrorCategory.PERMISSION_ERROR
        assert result.strategy_used == "provider_healer"

    @pytest.mark.asyncio
    async def test_unknown_error_llm_fallback(self, tmp_path):
        orch = SelfHealingOrchestrator(project_root=tmp_path)
        err = RuntimeError("something strange")

        with patch(
            "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
            return_value="The error is caused by a corrupted cache.",
        ):
            result = await orch.diagnose_and_fix(err)

        assert "corrupted cache" in result.diagnosis
        assert result.strategy_used == "llm_healer"

    @pytest.mark.asyncio
    async def test_unknown_error_llm_suggests_package(self, tmp_path):
        orch = SelfHealingOrchestrator(project_root=tmp_path)
        err = RuntimeError("something that needs a package")

        with (
            patch(
                "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
                return_value="INSTALL: some-tool",
            ),
            patch(
                "warden.self_healing.strategies.llm_healer._try_pip_install",
                return_value=True,
            ),
        ):
            result = await orch.diagnose_and_fix(err)

        assert result.fixed is True
        assert "some-tool" in result.packages_installed

    @pytest.mark.asyncio
    async def test_llm_unavailable_fallback(self, tmp_path):
        orch = SelfHealingOrchestrator(project_root=tmp_path)
        err = RuntimeError("unknown failure")

        with patch(
            "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
            return_value=None,
        ):
            result = await orch.diagnose_and_fix(err)

        assert result.fixed is False
        assert "RuntimeError" in result.diagnosis

    @pytest.mark.asyncio
    async def test_max_attempts_protection(self, tmp_path):
        orch = SelfHealingOrchestrator(max_attempts=1, project_root=tmp_path)
        err = ModuleNotFoundError("No module named 'tiktoken'")

        with patch(
            "warden.self_healing.strategies.import_healer._try_pip_install",
            return_value=False,
        ):
            with patch(
                "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
                return_value=None,
            ):
                await orch.diagnose_and_fix(err)
                result2 = await orch.diagnose_and_fix(err)

        assert "Max healing attempts" in result2.diagnosis

    @pytest.mark.asyncio
    async def test_different_errors_separate_counters(self, tmp_path):
        orch = SelfHealingOrchestrator(max_attempts=1, project_root=tmp_path)
        err1 = ModuleNotFoundError("No module named 'pkg_a'")
        err2 = ModuleNotFoundError("No module named 'pkg_b'")

        with patch(
            "warden.self_healing.strategies.import_healer._try_pip_install",
            return_value=False,
        ):
            with patch(
                "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
                return_value=None,
            ):
                r1 = await orch.diagnose_and_fix(err1)
                r2 = await orch.diagnose_and_fix(err2)

        assert "Max healing attempts" not in r1.diagnosis
        assert "Max healing attempts" not in r2.diagnosis

    @pytest.mark.asyncio
    async def test_cache_stores_result(self, tmp_path):
        orch = SelfHealingOrchestrator(project_root=tmp_path)
        err = ModuleNotFoundError("No module named 'tiktoken'")

        with patch(
            "warden.self_healing.strategies.import_healer._try_pip_install",
            return_value=True,
        ):
            await orch.diagnose_and_fix(err)

        # Cache file should exist
        cache_file = tmp_path / ".warden" / "cache" / "healing_cache.json"
        assert cache_file.exists()

    @pytest.mark.asyncio
    async def test_metrics_tracked(self, tmp_path):
        orch = SelfHealingOrchestrator(project_root=tmp_path)
        err = TimeoutError("timed out")

        await orch.diagnose_and_fix(err)

        metrics = orch.get_metrics()
        assert metrics.total_attempts == 1

    @pytest.mark.asyncio
    async def test_reset_attempts(self, tmp_path):
        orch = SelfHealingOrchestrator(max_attempts=1, project_root=tmp_path)
        err = RuntimeError("test")

        with patch(
            "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
            return_value=None,
        ):
            await orch.diagnose_and_fix(err)
            orch.reset_attempts()
            r = await orch.diagnose_and_fix(err)

        assert "Max healing attempts" not in r.diagnosis

    @pytest.mark.asyncio
    async def test_llm_fallback_exception_logged(self, tmp_path):
        """When LLM fallback raises, the exception is logged (not silenced)."""
        orch = SelfHealingOrchestrator(project_root=tmp_path)
        # Use an import error where import_healer fails, triggering LLM fallback
        err = ModuleNotFoundError("No module named 'nonexistent'")

        with (
            patch(
                "warden.self_healing.strategies.import_healer._try_pip_install",
                return_value=False,
            ),
            patch(
                "warden.self_healing.strategies.llm_healer.LLMHealer.heal",
                side_effect=RuntimeError("LLM crashed"),
            ),
            patch(
                "warden.self_healing.orchestrator.logger"
            ) as mock_logger,
        ):
            result = await orch.diagnose_and_fix(err)

        # The result should still be returned (not crash)
        assert result is not None
        # The debug logger should have been called with the fallback failure
        debug_calls = [
            c for c in mock_logger.debug.call_args_list
            if c.args and c.args[0] == "llm_fallback_failed"
        ]
        assert len(debug_calls) >= 1

    @pytest.mark.asyncio
    async def test_strategy_exception_tries_next(self, tmp_path):
        """When a strategy raises, orchestrator catches and tries the next one."""
        orch = SelfHealingOrchestrator(project_root=tmp_path)
        err = ModuleNotFoundError("No module named 'tiktoken'")

        with (
            patch(
                "warden.self_healing.strategies.import_healer.ImportHealer.heal",
                side_effect=RuntimeError("strategy boom"),
            ),
            patch(
                "warden.self_healing.strategies.llm_healer._ask_llm_diagnosis",
                return_value="INSTALL: tiktoken",
            ),
            patch(
                "warden.self_healing.strategies.llm_healer._try_pip_install",
                return_value=True,
            ),
        ):
            result = await orch.diagnose_and_fix(err)

        # LLM fallback should have kicked in and fixed it
        assert result.fixed is True
        assert result.strategy_used == "llm_healer"
