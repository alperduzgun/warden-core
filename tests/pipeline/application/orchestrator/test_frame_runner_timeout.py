"""
Tests for per-file dynamic timeout in FrameRunner (#99).

Covers:
1. calculate_per_file_timeout — proportional timeout formula
2. FrameRunner timeout handling — finding creation on timeout
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.pipeline.application.orchestrator.frame_runner import (
    FrameRunner,
    _FILE_BYTES_PER_SECOND,
    _FILE_TIMEOUT_LOCAL_S,
    _FILE_TIMEOUT_MAX_S,
    _FILE_TIMEOUT_MIN_S,
    calculate_per_file_timeout,
)
from warden.pipeline.domain.models import PipelineConfig

from .conftest import make_code_file, make_context, make_pipeline


# ---------------------------------------------------------------------------
# calculate_per_file_timeout — unit tests
# ---------------------------------------------------------------------------


class TestCalculatePerFileTimeout:
    """Tests for the standalone timeout calculation function."""

    def test_empty_file_returns_minimum(self):
        """A zero-byte file should get the minimum timeout."""
        assert calculate_per_file_timeout(0) == _FILE_TIMEOUT_MIN_S

    def test_small_file_returns_minimum(self):
        """Files smaller than min*bytes_per_second should clamp to minimum."""
        # 1 KB file: 1000 / 10_000 = 0.1s -> clamped to min (5s)
        assert calculate_per_file_timeout(1_000) == _FILE_TIMEOUT_MIN_S

    def test_proportional_timeout(self):
        """Medium files should get a proportional timeout."""
        # 300 KB: 300_000 / 10_000 = 30s (between min=5 and max=300)
        result = calculate_per_file_timeout(300_000)
        assert result == 30.0

    def test_large_file_capped_at_maximum(self):
        """Files larger than max*bytes_per_second should be capped."""
        # 3.1 MB: 3_100_000 / 10_000 = 310s -> capped to max (300s)
        result = calculate_per_file_timeout(3_100_000)
        assert result == _FILE_TIMEOUT_MAX_S

    def test_exact_formula(self):
        """Verify the exact formula: max(MIN, min(size/bps, MAX))."""
        size = 200_000
        expected = max(_FILE_TIMEOUT_MIN_S, min(size / _FILE_BYTES_PER_SECOND, _FILE_TIMEOUT_MAX_S))
        assert calculate_per_file_timeout(size) == expected

    def test_local_provider_uses_higher_floor(self):
        """Ollama/local providers should use the higher timeout floor."""
        result = calculate_per_file_timeout(100, provider="ollama")
        assert result == _FILE_TIMEOUT_LOCAL_S

    def test_local_provider_claude_code(self):
        result = calculate_per_file_timeout(100, provider="claude_code")
        assert result == _FILE_TIMEOUT_LOCAL_S

    def test_local_provider_codex(self):
        result = calculate_per_file_timeout(100, provider="codex")
        assert result == _FILE_TIMEOUT_LOCAL_S

    def test_cloud_provider_uses_standard_floor(self):
        result = calculate_per_file_timeout(100, provider="openai")
        assert result == _FILE_TIMEOUT_MIN_S

    def test_explicit_min_overrides_provider(self):
        """Explicit min_timeout should override provider-based floor."""
        result = calculate_per_file_timeout(100, provider="ollama", min_timeout=3.0)
        assert result == 3.0

    def test_explicit_max_timeout(self):
        """Custom max_timeout should cap the result."""
        result = calculate_per_file_timeout(1_000_000, max_timeout=20.0)
        assert result == 20.0

    def test_custom_bytes_per_second(self):
        """Custom bytes_per_second changes proportional calculation."""
        # 100_000 / 50_000 = 2s -> clamped to min (5s)
        result = calculate_per_file_timeout(100_000, bytes_per_second=50_000)
        assert result == _FILE_TIMEOUT_MIN_S

        # 500_000 / 50_000 = 10s -> between min and max
        result = calculate_per_file_timeout(500_000, bytes_per_second=50_000)
        assert result == 10.0

    def test_env_var_overrides_floor(self):
        """WARDEN_FILE_TIMEOUT_MIN env var should override the floor."""
        with patch.dict(os.environ, {"WARDEN_FILE_TIMEOUT_MIN": "15"}):
            result = calculate_per_file_timeout(100)
            assert result == 15.0

    def test_env_var_overrides_local_provider(self):
        """Env var takes precedence even for local providers."""
        with patch.dict(os.environ, {"WARDEN_FILE_TIMEOUT_MIN": "8"}):
            result = calculate_per_file_timeout(100, provider="ollama")
            assert result == 8.0

    def test_zero_bytes_per_second_returns_minimum(self):
        """Zero throughput should not cause division error."""
        result = calculate_per_file_timeout(100_000, bytes_per_second=0)
        assert result == _FILE_TIMEOUT_MIN_S

    def test_negative_file_size_returns_minimum(self):
        """Negative size (edge case) should still return minimum."""
        result = calculate_per_file_timeout(-1)
        assert result == _FILE_TIMEOUT_MIN_S

    def test_provider_case_insensitive(self):
        """Provider matching should be case-insensitive."""
        assert calculate_per_file_timeout(100, provider="OLLAMA") == _FILE_TIMEOUT_LOCAL_S
        assert calculate_per_file_timeout(100, provider="Ollama") == _FILE_TIMEOUT_LOCAL_S


# ---------------------------------------------------------------------------
# Default constant values
# ---------------------------------------------------------------------------


class TestDefaultConstants:
    """Verify the module-level constants match issue #99 defaults."""

    def test_min_timeout(self):
        assert _FILE_TIMEOUT_MIN_S == 5.0

    def test_max_timeout(self):
        assert _FILE_TIMEOUT_MAX_S == 300.0

    def test_bytes_per_second(self):
        assert _FILE_BYTES_PER_SECOND == 10_000


# ---------------------------------------------------------------------------
# FrameRunner timeout integration — verify finding is created on timeout
# ---------------------------------------------------------------------------


class TestFrameRunnerTimeout:
    """Integration tests for per-file timeout in FrameRunner."""

    @pytest.mark.asyncio
    async def test_timeout_produces_finding(self):
        """When a file times out, a Finding with id=WARDEN-TIMEOUT should be recorded."""
        # Create a frame that hangs forever
        frame = MagicMock()
        frame.frame_id = "test_security"
        frame.name = "Security"
        frame.is_blocker = False
        frame.config = {}

        async def _hang(code_file, **kwargs):
            await asyncio.sleep(999)

        frame.execute_async = AsyncMock(side_effect=_hang)

        # A file with known content
        code_file = make_code_file(path="/tmp/big.py", content="x = 1\n" * 100)
        context = make_context()
        context.file_contexts = {}
        context.ast_cache = {}
        context.frame_results = {}
        pipeline = make_pipeline()
        pipeline.frames_executed = 0
        pipeline.frames_passed = 0
        pipeline.frames_failed = 0

        runner = FrameRunner(config=PipelineConfig())
        # Force a very short timeout so the test completes quickly
        with patch(
            "warden.pipeline.application.orchestrator.frame_runner.calculate_per_file_timeout",
            return_value=0.01,
        ):
            result = await runner.execute_frame_with_rules_async(context, frame, [code_file], pipeline)

        # The frame should still complete (not crash)
        assert result is not None
        # Should have at least one finding from the timeout
        all_findings = result.findings if result.findings else []
        timeout_findings = [f for f in all_findings if f.id == "WARDEN-TIMEOUT"]
        assert len(timeout_findings) >= 1
        tf = timeout_findings[0]
        assert tf.severity == "medium"
        assert "timed out" in tf.message.lower()
        assert "/tmp/big.py" in tf.location
