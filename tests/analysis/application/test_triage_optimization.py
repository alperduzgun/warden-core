"""Tests for 4-layer triage optimization.

Covers:
- TestTriageBypass:          Codex/Claude Code → heuristic-only, Groq/Ollama → LLM triage
- TestImprovedHeuristics:    Extended safe-file detection
- TestTriageCache:           Miss / hit / invalidation / disk persistence / eviction / corruption
- TestAdaptiveBatchSizing:   Provider-aware batch sizes
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from warden.analysis.application.triage_cache import TriageCacheManager
from warden.analysis.application.triage_service import TriageService
from warden.analysis.domain.triage_heuristics import is_heuristic_safe
from warden.analysis.domain.triage_models import RiskScore, TriageDecision, TriageLane
from warden.validation.domain.frame import CodeFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_code_file(path: str, content: str = "", line_count: int = 100, language: str = "python") -> CodeFile:
    """Create a minimal CodeFile for testing."""
    return CodeFile(
        path=path,
        content=content or ("x = 1\n" * line_count),
        language=language,
        line_count=line_count,
    )


def _make_llm_client(provider: str = "groq") -> MagicMock:
    """Create a mock LLM client with a given provider string."""
    client = MagicMock()
    client.provider = provider
    client.endpoint = ""
    client._endpoint = ""
    return client


# ===========================================================================
# STEP 2: Improved Heuristics
# ===========================================================================


class TestImprovedHeuristics:
    """Verify the shared ``is_heuristic_safe`` function."""

    @pytest.mark.parametrize(
        "path",
        [
            "src/__init__.py",
            "src/__main__.py",
            "tests/conftest.py",
            "src/_version.py",
            "setup.py",
            "pyproject.toml",
        ],
    )
    def test_safe_filenames(self, path: str) -> None:
        cf = _make_code_file(path, content="a" * 500, line_count=50)
        assert is_heuristic_safe(cf) is True

    @pytest.mark.parametrize(
        "path",
        [
            "types.pyi",
            "py.typed",
            "settings.toml",
            "setup.cfg",
            "config.ini",
        ],
    )
    def test_safe_extensions(self, path: str) -> None:
        cf = _make_code_file(path, content="a" * 500, line_count=50)
        assert is_heuristic_safe(cf) is True

    @pytest.mark.parametrize(
        "path",
        [
            "lib/__pycache__/module.cpython-311.pyc",
            "env/lib/python3.11/site-packages/pkg/core.py",
            ".git/objects/ab/1234",
        ],
    )
    def test_safe_directories(self, path: str) -> None:
        cf = _make_code_file(path, content="a" * 500, line_count=50)
        assert is_heuristic_safe(cf) is True

    def test_small_file_is_safe(self) -> None:
        cf = _make_code_file("src/app.py", content="x = 1", line_count=1)
        assert is_heuristic_safe(cf) is True

    def test_large_auth_file_is_not_safe(self) -> None:
        cf = _make_code_file("src/auth.py", content="x = 1\n" * 200, line_count=200)
        assert is_heuristic_safe(cf) is False

    def test_large_service_file_is_not_safe(self) -> None:
        cf = _make_code_file("src/payment_service.py", content="x = 1\n" * 200, line_count=200)
        assert is_heuristic_safe(cf) is False

    def test_config_keyword_in_name_is_safe(self) -> None:
        cf = _make_code_file("src/app_config.py", content="x = 1\n" * 200, line_count=200)
        assert is_heuristic_safe(cf) is True

    def test_settings_keyword_in_name_is_safe(self) -> None:
        cf = _make_code_file("src/settings.py", content="x = 1\n" * 200, line_count=200)
        assert is_heuristic_safe(cf) is True


# ===========================================================================
# STEP 3: Triage Cache
# ===========================================================================


class TestTriageCache:
    """Test TriageCacheManager: miss, hit, invalidation, persistence, eviction."""

    def _make_cache(self, tmp_path: Path) -> TriageCacheManager:
        return TriageCacheManager(tmp_path, max_entries=10)

    def _make_decision(self, path: str = "src/a.py") -> TriageDecision:
        return TriageDecision(
            file_path=path,
            lane=TriageLane.MIDDLE,
            risk_score=RiskScore(score=5.0, confidence=0.8, reasoning="test", category="logic"),
            processing_time_ms=10.0,
        )

    def test_cache_miss(self, tmp_path: Path) -> None:
        cache = self._make_cache(tmp_path)
        assert cache.get("src/a.py", "content_v1") is None

    def test_cache_hit(self, tmp_path: Path) -> None:
        cache = self._make_cache(tmp_path)
        decision = self._make_decision()
        cache.put("src/a.py", "content_v1", decision)

        result = cache.get("src/a.py", "content_v1")
        assert result is not None
        assert result.lane == TriageLane.MIDDLE
        assert result.is_cached is True

    def test_cache_invalidation_on_content_change(self, tmp_path: Path) -> None:
        cache = self._make_cache(tmp_path)
        decision = self._make_decision()
        cache.put("src/a.py", "content_v1", decision)

        # Different content → miss
        assert cache.get("src/a.py", "content_v2") is None

    def test_disk_persistence(self, tmp_path: Path) -> None:
        cache1 = self._make_cache(tmp_path)
        cache1.put("src/a.py", "content_v1", self._make_decision())
        cache1.flush()

        # New instance loads from disk
        cache2 = self._make_cache(tmp_path)
        result = cache2.get("src/a.py", "content_v1")
        assert result is not None
        assert result.lane == TriageLane.MIDDLE

    def test_lru_eviction(self, tmp_path: Path) -> None:
        cache = self._make_cache(tmp_path)  # max_entries=10

        # Fill beyond capacity
        for i in range(15):
            d = self._make_decision(f"src/f{i}.py")
            cache.put(f"src/f{i}.py", f"content_{i}", d)

        # Should have evicted oldest entries, keeping <= 10
        assert cache.size <= 10

    def test_corrupt_cache_file(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / ".warden" / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "triage_cache.json").write_text("NOT JSON {{{{")

        # Should not raise, just start empty
        cache = self._make_cache(tmp_path)
        assert cache.size == 0

    def test_cache_key_deterministic(self) -> None:
        k1 = TriageCacheManager.cache_key("src/a.py", "hello world")
        k2 = TriageCacheManager.cache_key("src/a.py", "hello world")
        assert k1 == k2

    def test_cache_key_differs_for_different_content(self) -> None:
        k1 = TriageCacheManager.cache_key("src/a.py", "hello world")
        k2 = TriageCacheManager.cache_key("src/a.py", "goodbye world")
        assert k1 != k2


# ===========================================================================
# STEP 4: Adaptive Batch Sizing
# ===========================================================================


class TestAdaptiveBatchSizing:
    """Verify provider-aware batch size selection."""

    def test_ollama_batch_size(self) -> None:
        client = _make_llm_client("ollama")
        svc = TriageService(client)
        assert svc._requested_batch_size == 5

    def test_groq_batch_size(self) -> None:
        client = _make_llm_client("groq")
        svc = TriageService(client)
        assert svc._requested_batch_size == 15

    def test_openai_batch_size(self) -> None:
        client = _make_llm_client("openai")
        svc = TriageService(client)
        assert svc._requested_batch_size == 15

    def test_codex_batch_size(self) -> None:
        client = _make_llm_client("codex")
        svc = TriageService(client)
        assert svc._requested_batch_size == 25

    def test_claude_code_batch_size(self) -> None:
        client = _make_llm_client("claude_code")
        svc = TriageService(client)
        assert svc._requested_batch_size == 25

    def test_unknown_provider_defaults_to_5(self) -> None:
        client = _make_llm_client("unknown_provider")
        svc = TriageService(client)
        assert svc._requested_batch_size == 5

    def test_orchestrated_client_uses_fast_tier_provider(self) -> None:
        """OrchestratedLlmClient should use fast_clients for batch size (triage uses fast tier)."""
        smart = _make_llm_client("groq")       # smart tier = Groq (15)
        fast = _make_llm_client("ollama")       # fast tier = Ollama (5)

        wrapper = MagicMock()
        wrapper.provider = "groq"               # .provider returns smart provider
        wrapper._smart_client = smart
        wrapper.fast_clients = [fast]            # fast tier has Ollama

        svc = TriageService(wrapper)
        # Must pick Ollama (5), not Groq (15) — triage uses fast tier
        assert svc._requested_batch_size == 5

    def test_orchestrated_client_no_fast_tier_falls_to_smart(self) -> None:
        """When no fast clients exist, use smart provider for batch size."""
        smart = _make_llm_client("groq")

        wrapper = MagicMock()
        wrapper.provider = "groq"
        wrapper._smart_client = smart
        wrapper.fast_clients = []               # no fast tier

        svc = TriageService(wrapper)
        # Falls back to smart provider (Groq = 15)
        assert svc._requested_batch_size == 15


# ===========================================================================
# STEP 1: Single-Tier Triage Bypass
# ===========================================================================


class TestTriageBypass:
    """Verify PipelinePhaseRunner bypasses LLM triage for CLI-tool providers."""

    def _make_runner(self, provider: str = "codex") -> Any:
        from warden.pipeline.application.orchestrator.pipeline_phase_runner import PipelinePhaseRunner

        config = MagicMock()
        config.enable_pre_analysis = False
        config.use_llm = True
        config.analysis_level = MagicMock()
        config.analysis_level.name = "STANDARD"
        config.enable_analysis = False
        config.enable_validation = False
        config.enable_issue_validation = False
        config.enable_fortification = False
        config.enable_cleaning = False

        # Make analysis_level != BASIC
        from warden.pipeline.domain.enums import AnalysisLevel
        config.analysis_level = AnalysisLevel.STANDARD

        # Mock LLM service with inner provider
        inner_client = MagicMock()
        inner_client.provider = provider

        llm_service = MagicMock()
        llm_service._smart_client = inner_client

        runner = PipelinePhaseRunner(
            config=config,
            phase_executor=MagicMock(),
            frame_executor=MagicMock(),
            post_processor=MagicMock(),
            llm_service=llm_service,
        )
        return runner

    def test_detects_codex_as_single_tier(self) -> None:
        runner = self._make_runner("codex")
        assert runner._is_single_tier_provider() is True

    def test_detects_claude_code_as_single_tier(self) -> None:
        runner = self._make_runner("claude_code")
        assert runner._is_single_tier_provider() is True

    def test_groq_is_not_single_tier(self) -> None:
        runner = self._make_runner("groq")
        assert runner._is_single_tier_provider() is False

    def test_ollama_is_not_single_tier(self) -> None:
        runner = self._make_runner("ollama")
        assert runner._is_single_tier_provider() is False

    def test_heuristic_triage_assigns_lanes(self) -> None:
        runner = self._make_runner("codex")
        context = MagicMock()
        context.triage_decisions = {}
        context.add_phase_result = MagicMock()

        files = [
            _make_code_file("src/__init__.py", content="", line_count=0),        # safe
            _make_code_file("src/auth.py", content="x = 1\n" * 200, line_count=200),  # not safe
        ]

        runner._apply_heuristic_triage(context, files)

        decisions = context.triage_decisions
        assert len(decisions) == 2

        # __init__.py → FAST
        init_decision = decisions["src/__init__.py"]
        assert init_decision["lane"] == TriageLane.FAST

        # auth.py → MIDDLE
        auth_decision = decisions["src/auth.py"]
        assert auth_decision["lane"] == TriageLane.MIDDLE

    def test_heuristic_triage_records_phase_result(self) -> None:
        runner = self._make_runner("codex")
        context = MagicMock()
        context.triage_decisions = {}

        files = [_make_code_file("src/app.py", content="x = 1\n" * 200, line_count=200)]
        runner._apply_heuristic_triage(context, files)

        context.add_phase_result.assert_called_once()
        call_args = context.add_phase_result.call_args
        assert call_args[0][0] == "TRIAGE"
        assert call_args[0][1]["mode"] == "heuristic_bypass"


# ===========================================================================
# Integration: TriageService with cache
# ===========================================================================


class TestTriageServiceCacheIntegration:
    """Test that TriageService uses cache correctly during batch assessment."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_llm(self, tmp_path: Path) -> None:
        cache = TriageCacheManager(tmp_path, max_entries=100)
        client = _make_llm_client("groq")
        client.send_async = AsyncMock()

        svc = TriageService(client, cache=cache)

        # Pre-populate cache for auth.py
        auth_file = _make_code_file("src/auth.py", content="x = 1\n" * 200, line_count=200)
        cached_decision = TriageDecision(
            file_path="src/auth.py",
            lane=TriageLane.DEEP,
            risk_score=RiskScore(score=9.0, confidence=0.9, reasoning="cached", category="auth"),
            processing_time_ms=1.0,
        )
        cache.put("src/auth.py", auth_file.content, cached_decision)

        # A safe file + cached file = no LLM calls needed
        init_file = _make_code_file("src/__init__.py", content="", line_count=0)

        decisions = await svc.batch_assess_risk_async([init_file, auth_file])

        assert len(decisions) == 2
        assert decisions["src/__init__.py"].lane == TriageLane.FAST
        assert decisions["src/auth.py"].lane == TriageLane.DEEP
        assert decisions["src/auth.py"].is_cached is True

        # No LLM calls were made
        client.send_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_calls_llm(self, tmp_path: Path) -> None:
        cache = TriageCacheManager(tmp_path, max_entries=100)
        client = _make_llm_client("groq")

        # Mock LLM response
        response = MagicMock()
        response.success = True
        response.content = json.dumps({
            "src/payment.py": {"score": 8.0, "confidence": 0.9, "reasoning": "payment logic", "category": "finance"},
        })
        client.send_async = AsyncMock(return_value=response)

        svc = TriageService(client, cache=cache)

        payment_file = _make_code_file("src/payment.py", content="def pay():\n    pass\n" * 50, line_count=100)
        decisions = await svc.batch_assess_risk_async([payment_file])

        assert len(decisions) == 1
        assert decisions["src/payment.py"].lane == TriageLane.DEEP

        # LLM was called
        client.send_async.assert_called_once()

        # Cache should now have the entry
        cached = cache.get("src/payment.py", payment_file.content)
        assert cached is not None
