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

    def test_codex_single_provider_mode_has_empty_fast_clients(self):
        """When provider is Codex, fast_clients must be empty."""
        config = self._make_config(LlmProvider.CODEX)
        # Inject a fake fast-tier so we can confirm it is ignored
        config.fast_tier_providers = [LlmProvider.OLLAMA]
        ollama_cfg = ProviderConfig(enabled=True, default_model="qwen")
        config.ollama = ollama_cfg

        client = create_client(config)

        assert isinstance(client, OrchestratedLlmClient)
        assert client.fast_clients == [], "Codex must use single-provider mode (no fast clients)"

    def test_claude_code_single_provider_mode_has_empty_fast_clients(self):
        """When provider is Claude Code, fast_clients must be empty."""
        config = self._make_config(LlmProvider.CLAUDE_CODE)
        config.fast_tier_providers = [LlmProvider.OLLAMA]
        ollama_cfg = ProviderConfig(enabled=True, default_model="qwen")
        config.ollama = ollama_cfg

        client = create_client(config)

        assert isinstance(client, OrchestratedLlmClient)
        assert client.fast_clients == [], "Claude Code must use single-provider mode (no fast clients)"

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
