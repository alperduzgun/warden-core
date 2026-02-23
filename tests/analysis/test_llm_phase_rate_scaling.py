"""
Tests for LLMPhaseBase provider detection and rate limit auto-scaling.

Ensures local providers (Ollama, Claude Code, localhost endpoints) get
relaxed rate limits, while cloud providers keep their configured limits.
This catches the class of bugs where is_local detection fails and a
local provider gets throttled by cloud-tier rate limits.
"""

from unittest.mock import Mock

import pytest

from warden.analysis.application.llm_phase_base import LLMPhaseBase, LLMPhaseConfig
from warden.llm.rate_limiter import RateLimitConfig, RateLimiter
from warden.llm.types import LlmProvider


# ---------------------------------------------------------------------------
# Concrete subclass for testing (LLMPhaseBase is abstract)
# ---------------------------------------------------------------------------


class _TestablePhase(LLMPhaseBase):
    """Minimal concrete subclass to test LLMPhaseBase init logic."""

    @property
    def phase_name(self) -> str:
        return "test_phase"

    def get_system_prompt(self) -> str:
        return "test"

    def format_user_prompt(self, context):
        return "test"

    def parse_llm_response(self, response):
        return response


def _mock_llm(provider: str, endpoint: str = "") -> Mock:
    """Create a mock LLM service with given provider and endpoint."""
    llm = Mock()
    llm.provider = provider
    llm.endpoint = endpoint
    llm.config = None
    return llm


# ---------------------------------------------------------------------------
# Provider detection tests
# ---------------------------------------------------------------------------


class TestProviderDetection:
    """Verify is_local detection for various provider types."""

    def test_claude_code_detected_as_local(self):
        """CLAUDE_CODE provider → is_local=True, tpm=1M."""
        llm = _mock_llm(provider="CLAUDE_CODE")
        phase = _TestablePhase(
            config=LLMPhaseConfig(enabled=True, tpm_limit=1000, rpm_limit=6),
            llm_service=llm,
        )
        assert phase.is_local is True
        assert phase.config.tpm_limit == 1_000_000

    def test_ollama_detected_as_local(self):
        """OLLAMA provider → is_local=True, tpm=1M."""
        llm = _mock_llm(provider="OLLAMA")
        phase = _TestablePhase(
            config=LLMPhaseConfig(enabled=True, tpm_limit=1000, rpm_limit=6),
            llm_service=llm,
        )
        assert phase.is_local is True
        assert phase.config.tpm_limit == 1_000_000

    def test_localhost_endpoint_detected_as_local(self):
        """localhost:8080 endpoint → is_local=True regardless of provider name."""
        llm = _mock_llm(provider="CUSTOM", endpoint="http://localhost:8080")
        phase = _TestablePhase(
            config=LLMPhaseConfig(enabled=True, tpm_limit=1000, rpm_limit=6),
            llm_service=llm,
        )
        assert phase.is_local is True
        assert phase.config.tpm_limit == 1_000_000

    def test_cloud_provider_keeps_config_limits(self):
        """openai/groq provider → is_local=False, config limits unchanged."""
        llm = _mock_llm(provider="OPENAI", endpoint="https://api.openai.com")
        phase = _TestablePhase(
            config=LLMPhaseConfig(enabled=True, tpm_limit=1000, rpm_limit=6),
            llm_service=llm,
        )
        assert phase.is_local is False
        assert phase.config.tpm_limit == 1000  # Unchanged
        assert phase.config.rpm_limit == 6  # Unchanged

    def test_groq_not_detected_as_local(self):
        """groq provider → is_local=False."""
        llm = _mock_llm(provider="GROQ", endpoint="https://api.groq.com")
        phase = _TestablePhase(
            config=LLMPhaseConfig(enabled=True, tpm_limit=2000, rpm_limit=10),
            llm_service=llm,
        )
        assert phase.is_local is False
        assert phase.config.tpm_limit == 2000


# ---------------------------------------------------------------------------
# Rate limiter config propagation
# ---------------------------------------------------------------------------


class TestRateLimiterConfigPropagation:
    """Verify that is_local detection actually updates the active rate limiter."""

    def test_rate_limiter_config_actually_updated(self):
        """is_local=True → rate_limiter.config.tpm reflects 1M, not the original."""
        original_tpm = 1000
        cfg = RateLimitConfig(tpm=original_tpm, rpm=6)
        shared_limiter = RateLimiter(cfg)

        llm = _mock_llm(provider="OLLAMA")
        phase = _TestablePhase(
            config=LLMPhaseConfig(enabled=True, tpm_limit=original_tpm, rpm_limit=6),
            llm_service=llm,
            rate_limiter=shared_limiter,
        )

        # The shared limiter's config should now reflect the local override
        assert shared_limiter.config.tpm == 1_000_000
        assert shared_limiter.config.rpm == 100

    def test_cloud_provider_does_not_modify_shared_limiter(self):
        """Cloud provider must NOT modify the shared rate limiter config."""
        cfg = RateLimitConfig(tpm=2000, rpm=10)
        shared_limiter = RateLimiter(cfg)

        llm = _mock_llm(provider="GROQ", endpoint="https://api.groq.com")
        phase = _TestablePhase(
            config=LLMPhaseConfig(enabled=True, tpm_limit=2000, rpm_limit=10),
            llm_service=llm,
            rate_limiter=shared_limiter,
        )

        assert shared_limiter.config.tpm == 2000  # Unchanged
        assert shared_limiter.config.rpm == 10  # Unchanged

    def test_ipv6_localhost_detected_as_local(self):
        """::1 (IPv6 localhost) → is_local=True."""
        llm = _mock_llm(provider="CUSTOM", endpoint="http://[::1]:11434")
        phase = _TestablePhase(
            config=LLMPhaseConfig(enabled=True, tpm_limit=1000, rpm_limit=6),
            llm_service=llm,
        )
        assert phase.is_local is True

    def test_127_0_0_1_detected_as_local(self):
        """127.0.0.1 → is_local=True."""
        llm = _mock_llm(provider="CUSTOM", endpoint="http://127.0.0.1:11434")
        phase = _TestablePhase(
            config=LLMPhaseConfig(enabled=True, tpm_limit=1000, rpm_limit=6),
            llm_service=llm,
        )
        assert phase.is_local is True
