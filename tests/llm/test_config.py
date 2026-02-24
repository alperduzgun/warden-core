"""Test LLM configuration"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from warden.llm.config import (
    DEFAULT_MODELS,
    LlmConfiguration,
    ProviderConfig,
    _check_codex_availability,
    _SINGLE_TIER_PROVIDERS,
    create_default_config,
    load_llm_config_async,
)
from warden.llm.types import LlmProvider


def test_provider_config_validation():
    """Test ProviderConfig validation"""
    config = ProviderConfig()

    errors = config.validate("TestProvider")

    assert len(errors) > 0
    assert any("API key" in error for error in errors)
    assert any("Default model" in error for error in errors)


def test_provider_config_valid():
    """Test valid ProviderConfig"""
    config = ProviderConfig(api_key="sk-1234567890abcdef", default_model="test-model")

    errors = config.validate("TestProvider")

    assert len(errors) == 0


def test_llm_configuration_get_provider_config():
    """Test getting provider configuration"""
    config = LlmConfiguration()
    config.anthropic.api_key = "test-key"
    config.anthropic.default_model = "claude-3-5-sonnet"

    provider_config = config.get_provider_config(LlmProvider.ANTHROPIC)

    assert provider_config is not None
    assert provider_config.api_key == "test-key"


def test_llm_configuration_providers_chain():
    """Test provider chain (default + fallbacks)"""
    config = LlmConfiguration(
        default_provider=LlmProvider.DEEPSEEK, fallback_providers=[LlmProvider.QWENCODE, LlmProvider.ANTHROPIC]
    )

    chain = config.get_all_providers_chain()

    assert len(chain) == 3
    assert chain[0] == LlmProvider.DEEPSEEK
    assert chain[1] == LlmProvider.QWENCODE
    assert chain[2] == LlmProvider.ANTHROPIC


def test_create_default_config():
    """Test default configuration creation"""
    config = create_default_config()

    assert config.default_provider == LlmProvider.DEEPSEEK
    assert LlmProvider.QWENCODE in config.fallback_providers
    assert config.anthropic.default_model == "claude-3-5-sonnet-20241022"


def test_provider_config_str_masks_api_key():
    """Test API key masking in string representation"""
    config = ProviderConfig(api_key="sk-1234567890abcdef", default_model="test-model")

    str_repr = str(config)

    assert "sk-1234567890abcdef" not in str_repr
    assert "***cdef" in str_repr  # Last 4 chars shown


# ---------------------------------------------------------------------------
# Regression tests for bugs #1, #2, #4
# ---------------------------------------------------------------------------


class TestDefaultModelsCodex:
    """Bug #1 – DEFAULT_MODELS was missing CODEX, causing validate() false errors."""

    def test_codex_in_default_models(self):
        assert LlmProvider.CODEX in DEFAULT_MODELS, "CODEX must have a default model entry"

    def test_codex_validate_no_error(self):
        """ProviderConfig for codex must pass validate() with no errors."""
        cfg = ProviderConfig(
            enabled=True,
            default_model=DEFAULT_MODELS[LlmProvider.CODEX],
        )
        errors = cfg.validate("codex")
        assert errors == [], f"Unexpected validation errors: {errors}"

    def test_create_default_config_sets_codex_model(self):
        """create_default_config must set codex.default_model."""
        config = create_default_config()
        assert config.codex.default_model is not None
        assert config.codex.default_model != ""


class TestCheckCodexAvailability:
    """Bug #2 – Codex availability check must run 'codex --version', not just shutil.which."""

    def test_returns_false_when_not_on_path(self):
        with patch("shutil.which", return_value=None):
            result = asyncio.run(_check_codex_availability())
        assert result is False

    def test_returns_true_when_version_succeeds(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"1.0.0", b""))
        with (
            patch("shutil.which", return_value="/usr/bin/codex"),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = asyncio.run(_check_codex_availability())
        assert result is True

    def test_returns_false_when_version_fails(self):
        """Binary on PATH but codex --version exits non-zero → treat as unavailable."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
        with (
            patch("shutil.which", return_value="/usr/bin/codex"),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = asyncio.run(_check_codex_availability())
        assert result is False

    def test_returns_false_on_timeout(self):
        """Slow binary should time out and return False, not block."""

        async def _slow_communicate():
            await asyncio.sleep(10)

        mock_proc = AsyncMock()
        mock_proc.communicate = _slow_communicate
        with (
            patch("shutil.which", return_value="/usr/bin/codex"),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = asyncio.run(_check_codex_availability())
        assert result is False


class TestSingleTierFastTierCleared:
    """Bug #4 – fast_tier_providers must be empty when primary is a CLI-tool provider."""

    def test_single_tier_providers_constant(self):
        assert LlmProvider.CODEX in _SINGLE_TIER_PROVIDERS
        assert LlmProvider.CLAUDE_CODE in _SINGLE_TIER_PROVIDERS

    def _make_config(self, primary: LlmProvider) -> LlmConfiguration:
        cfg = LlmConfiguration(default_provider=primary)
        cfg.fast_tier_providers = [LlmProvider.OLLAMA, primary]
        return cfg

    @pytest.mark.asyncio
    async def test_codex_primary_clears_fast_tier(self, monkeypatch):
        """load_llm_config_async must clear fast_tier when primary is Codex."""
        monkeypatch.setenv("WARDEN_LLM_PROVIDER", "codex")
        # Codex available, Claude Code not, Ollama not
        with (
            patch("warden.llm.config._check_codex_availability", return_value=True),
            patch("warden.llm.config._check_claude_code_availability", return_value=False),
            patch("warden.llm.config._check_ollama_availability", return_value=False),
        ):
            config = await load_llm_config_async()
        assert config.default_provider == LlmProvider.CODEX
        assert config.fast_tier_providers == [], (
            f"fast_tier_providers must be empty for single-tier provider, got {config.fast_tier_providers}"
        )

    @pytest.mark.asyncio
    async def test_claude_code_primary_clears_fast_tier(self, monkeypatch):
        """load_llm_config_async must clear fast_tier when primary is Claude Code."""
        monkeypatch.setenv("WARDEN_LLM_PROVIDER", "claude_code")
        with (
            patch("warden.llm.config._check_codex_availability", return_value=False),
            patch("warden.llm.config._check_claude_code_availability", return_value=True),
            patch("warden.llm.config._check_ollama_availability", return_value=False),
        ):
            config = await load_llm_config_async()
        assert config.default_provider == LlmProvider.CLAUDE_CODE
        assert config.fast_tier_providers == []

    @pytest.mark.asyncio
    async def test_explicit_provider_restricts_fast_tier(self, monkeypatch):
        """When a provider is explicitly set, fast tier is restricted to that provider only.
        Auto-pilot must NOT silently add Ollama, Claude Code, or Codex to the fast tier.
        """
        monkeypatch.setenv("WARDEN_LLM_PROVIDER", "groq")
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_1234567890abcdef")
        with (
            patch("warden.llm.config._check_codex_availability", return_value=False),
            patch("warden.llm.config._check_claude_code_availability", return_value=False),
            patch("warden.llm.config._check_ollama_availability", return_value=True),
        ):
            config = await load_llm_config_async()
        assert config.default_provider == LlmProvider.GROQ
        # fast_tier_providers contains only the primary (factory will skip it → no fast clients)
        assert config.fast_tier_providers == [LlmProvider.GROQ]
        assert LlmProvider.OLLAMA not in config.fast_tier_providers
        assert LlmProvider.CLAUDE_CODE not in config.fast_tier_providers
