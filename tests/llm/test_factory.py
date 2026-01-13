"""Test LLM client factory"""

import pytest
from warden.llm.factory import create_client, create_provider_client
from warden.llm.config import LlmConfiguration, ProviderConfig
from warden.llm.types import LlmProvider
from warden.llm.providers.anthropic import AnthropicClient
from warden.llm.providers.deepseek import DeepSeekClient


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
