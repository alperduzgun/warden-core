"""Test LLM configuration"""

import pytest
from warden.llm.config import ProviderConfig, LlmConfiguration, create_default_config
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
    config = ProviderConfig(
        api_key="sk-1234567890abcdef",
        default_model="test-model"
    )

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
        default_provider=LlmProvider.DEEPSEEK,
        fallback_providers=[LlmProvider.QWENCODE, LlmProvider.ANTHROPIC]
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
    config = ProviderConfig(
        api_key="sk-1234567890abcdef",
        default_model="test-model"
    )

    str_repr = str(config)

    assert "sk-1234567890abcdef" not in str_repr
    assert "***cdef" in str_repr  # Last 4 chars shown
