"""Test LLM client factory"""

import logging
import pytest
from warden.llm.factory import SINGLE_TIER_PROVIDERS, create_client, create_provider_client
from warden.llm.config import LlmConfiguration, ProviderConfig
from warden.llm.types import LlmProvider
from warden.llm.providers.anthropic import AnthropicClient
from warden.llm.providers.deepseek import DeepSeekClient
from warden.llm.providers.orchestrated import OrchestratedLlmClient


def test_factory_create_anthropic_client():
    """Test creating Anthropic client"""
    config = ProviderConfig(
        api_key="sk-test-key-1234567890",
        default_model="claude-3-5-sonnet",
        enabled=True
    )
    
    client = create_provider_client(LlmProvider.ANTHROPIC, config)

    assert isinstance(client, AnthropicClient)
    assert client.provider == LlmProvider.ANTHROPIC


def test_factory_create_deepseek_client():
    """Test creating DeepSeek client"""
    config = ProviderConfig(
        api_key="sk-test-key-1234567890",
        default_model="deepseek-coder",
        enabled=True
    )

    client = create_provider_client(LlmProvider.DEEPSEEK, config)

    assert isinstance(client, DeepSeekClient)
    assert client.provider == LlmProvider.DEEPSEEK


def test_factory_create_client_with_config():
    """Test creating client with explicit configuration"""
    config = LlmConfiguration(default_provider=LlmProvider.DEEPSEEK)
    config.deepseek = ProviderConfig(
        api_key="sk-test-key-1234567890",
        default_model="deepseek-coder",
        enabled=True
    )

    client = create_client(config)

    assert client.provider == LlmProvider.DEEPSEEK


def test_factory_create_client_disabled_provider():
    """Test error when provider disabled or missing key"""
    config = ProviderConfig(
        api_key="",  # Missing key
        enabled=True
    )

    with pytest.raises(ValueError, match="not configured"):
        create_provider_client(LlmProvider.ANTHROPIC, config)


class TestSingleTierProviders:
    """Single-tier mode: CLI-tool providers route all requests through one client."""

    def test_single_tier_providers_constant(self):
        """SINGLE_TIER_PROVIDERS must contain exactly CODEX and CLAUDE_CODE."""
        assert LlmProvider.CODEX in SINGLE_TIER_PROVIDERS
        assert LlmProvider.CLAUDE_CODE in SINGLE_TIER_PROVIDERS

    def _make_config(self, provider: LlmProvider) -> LlmConfiguration:
        cfg = LlmConfiguration(default_provider=provider)
        prov_cfg = ProviderConfig(enabled=True, default_model="test-model")
        setattr(cfg, provider.value, prov_cfg)
        # Guard: config must pass validation before being handed to the factory
        errors = cfg.validate()
        assert errors == [], f"Test config has validation errors: {errors}"
        return cfg

    def test_codex_single_provider_adds_emergency_fallback(self):
        """When provider is Codex, available fast providers are added as emergency fallback."""
        config = self._make_config(LlmProvider.CODEX)
        config.fast_tier_providers = [LlmProvider.OLLAMA]
        ollama_cfg = ProviderConfig(enabled=True, default_model="qwen")
        config.ollama = ollama_cfg

        client = create_client(config)

        assert isinstance(client, OrchestratedLlmClient)
        assert len(client.fast_clients) == 1, "Codex should have Ollama as emergency fallback"
        assert client.fast_clients[0].provider == LlmProvider.OLLAMA

    def test_claude_code_single_provider_adds_emergency_fallback(self):
        """When provider is Claude Code, available fast providers are added as emergency fallback."""
        config = self._make_config(LlmProvider.CLAUDE_CODE)
        config.fast_tier_providers = [LlmProvider.OLLAMA]
        ollama_cfg = ProviderConfig(enabled=True, default_model="qwen")
        config.ollama = ollama_cfg

        client = create_client(config)

        assert isinstance(client, OrchestratedLlmClient)
        assert len(client.fast_clients) == 1, "Claude Code should have Ollama as emergency fallback"
        assert client.fast_clients[0].provider == LlmProvider.OLLAMA

    def test_single_provider_no_fallback_when_disabled(self):
        """When fast providers are disabled, single-tier has no fallback."""
        config = self._make_config(LlmProvider.CLAUDE_CODE)
        config.fast_tier_providers = [LlmProvider.OLLAMA]
        config.ollama = ProviderConfig(enabled=False, default_model="qwen")

        client = create_client(config)

        assert isinstance(client, OrchestratedLlmClient)
        assert client.fast_clients == [], "No fallback when providers are disabled"

    def test_single_provider_no_fallback_when_unconfigured(self):
        """When no fast providers are configured at all, single-tier has no fallback."""
        config = self._make_config(LlmProvider.CODEX)
        config.fast_tier_providers = []

        client = create_client(config)

        assert isinstance(client, OrchestratedLlmClient)
        assert client.fast_clients == [], "No fallback when no fast providers configured"

    def test_non_cli_provider_still_builds_fast_tier(self):
        """Regular providers (Groq, Anthropic…) still get a fast tier when available."""
        config = LlmConfiguration(default_provider=LlmProvider.DEEPSEEK)
        config.deepseek = ProviderConfig(api_key="sk-xxx", enabled=True, default_model="deepseek-coder")
        config.fast_tier_providers = [LlmProvider.OLLAMA]
        config.ollama = ProviderConfig(enabled=True, default_model="qwen")

        client = create_client(config)

        assert isinstance(client, OrchestratedLlmClient)
        # Ollama fast client should have been added
        assert len(client.fast_clients) == 1

    def test_single_tier_no_misleading_log(self, caplog):
        """Bug #3 – single-tier providers must NOT log 'slower, higher cost'."""
        config = self._make_config(LlmProvider.CODEX)
        config.fast_tier_providers = []

        with caplog.at_level(logging.WARNING):
            create_client(config)

        for record in caplog.records:
            assert "slower" not in record.message.lower(), (
                "Single-tier providers must not emit 'slower' warning"
            )
            assert "higher cost" not in record.message.lower(), (
                "Single-tier providers must not emit 'higher cost' warning"
            )

    def test_primary_provider_skipped_from_fast_tier(self):
        """Primary provider is not duplicated in the fast tier even if listed there."""
        config = LlmConfiguration(default_provider=LlmProvider.DEEPSEEK)
        config.deepseek = ProviderConfig(api_key="sk-xxx", enabled=True, default_model="deepseek-coder")
        # fast_tier_providers includes the primary — should be skipped
        config.fast_tier_providers = [LlmProvider.DEEPSEEK]

        client = create_client(config)

        assert isinstance(client, OrchestratedLlmClient)
        assert client.fast_clients == [], "Primary provider must not race against itself in fast tier"


class TestSmartTierProviderRouting:
    """Regression tests for issue #365: smart_tier_provider routes smart client to a different provider."""

    def _base_config(self) -> LlmConfiguration:
        """Base config with DeepSeek as default provider."""
        cfg = LlmConfiguration(default_provider=LlmProvider.DEEPSEEK)
        cfg.deepseek = ProviderConfig(
            api_key="sk-deepseek-key-1234567890",
            default_model="deepseek-coder",
            enabled=True,
        )
        cfg.fast_tier_providers = []
        return cfg

    def test_smart_tier_routes_to_different_provider(self):
        """Regression #365: smart_tier_provider=GROQ causes smart_client to be a Groq client,
        not the default_provider client.

        This test FAILS if factory always creates smart_client from default_provider
        and ignores smart_tier_provider.
        """
        config = self._base_config()
        config.groq = ProviderConfig(
            api_key="gsk-groq-key-1234567890",
            default_model="llama-3.3-70b-versatile",
            enabled=True,
        )
        config.smart_tier_provider = LlmProvider.GROQ

        client = create_client(config)

        assert isinstance(client, OrchestratedLlmClient)
        assert client.smart_client.provider == LlmProvider.GROQ, (
            "smart_client must use the smart_tier_provider (Groq), not the default_provider (DeepSeek)"
        )
        assert client.smart_client.provider != LlmProvider.DEEPSEEK, (
            "smart_client must NOT be DeepSeek when smart_tier_provider=GROQ is configured"
        )

    def test_smart_tier_fallback_when_unavailable(self):
        """Regression #365: when smart_tier_provider is set but that provider is disabled,
        smart_client falls back to the default_provider.

        This test FAILS if factory blindly uses smart_tier_provider without checking availability.
        """
        config = self._base_config()
        # Groq is set as smart_tier_provider but disabled — no api_key
        config.groq = ProviderConfig(
            api_key=None,
            default_model="llama-3.3-70b-versatile",
            enabled=False,
        )
        config.smart_tier_provider = LlmProvider.GROQ

        client = create_client(config)

        assert isinstance(client, OrchestratedLlmClient)
        assert client.smart_client.provider == LlmProvider.DEEPSEEK, (
            "smart_client must fall back to default_provider when smart_tier_provider is unavailable"
        )

    def test_smart_tier_model_override(self):
        """Regression #365: smart_tier_model is reflected in the orchestrated client's smart_model.

        This test FAILS if factory ignores smart_tier_model when building OrchestratedLlmClient.
        """
        config = self._base_config()
        config.groq = ProviderConfig(
            api_key="gsk-groq-key-1234567890",
            default_model="llama-3.3-70b-versatile",
            enabled=True,
        )
        config.smart_tier_provider = LlmProvider.GROQ
        config.smart_tier_model = "qwen-qwq-32b"

        client = create_client(config)

        assert isinstance(client, OrchestratedLlmClient)
        assert client.smart_model == "qwen-qwq-32b", (
            "OrchestratedLlmClient.smart_model must reflect smart_tier_model when set"
        )

    def test_no_smart_tier_uses_default_provider(self):
        """Regression #365: when smart_tier_provider is None, smart_client is created from
        default_provider as before.

        This is the baseline — ensures the happy path is not broken.
        """
        config = self._base_config()
        config.smart_tier_provider = None

        client = create_client(config)

        assert isinstance(client, OrchestratedLlmClient)
        assert client.smart_client.provider == LlmProvider.DEEPSEEK, (
            "smart_client must use default_provider when smart_tier_provider is None"
        )
