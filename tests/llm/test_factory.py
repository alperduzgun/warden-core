"""Test LLM client factory"""

import pytest
from warden.llm.factory import LlmClientFactory
from warden.llm.config import LlmConfiguration, ProviderConfig
from warden.llm.types import LlmProvider
from warden.llm.providers.anthropic import AnthropicClient
from warden.llm.providers.deepseek import DeepSeekClient


def test_factory_create_anthropic_client():
    """Test creating Anthropic client"""
    config = LlmConfiguration()
    config.anthropic = ProviderConfig(
        api_key="sk-test-key-1234567890",
        default_model="claude-3-5-sonnet"
    )

    factory = LlmClientFactory(config)
    client = factory.create_client(LlmProvider.ANTHROPIC)

    assert isinstance(client, AnthropicClient)
    assert client.provider == LlmProvider.ANTHROPIC


def test_factory_create_deepseek_client():
    """Test creating DeepSeek client"""
    config = LlmConfiguration()
    config.deepseek = ProviderConfig(
        api_key="sk-test-key-1234567890",
        default_model="deepseek-coder"
    )

    factory = LlmClientFactory(config)
    client = factory.create_client(LlmProvider.DEEPSEEK)

    assert isinstance(client, DeepSeekClient)
    assert client.provider == LlmProvider.DEEPSEEK


def test_factory_create_client_not_configured():
    """Test error when provider not configured"""
    config = LlmConfiguration()
    factory = LlmClientFactory(config)

    with pytest.raises(ValueError, match="not configured"):
        factory.create_client(LlmProvider.ANTHROPIC)


def test_factory_create_default_client():
    """Test creating default client"""
    config = LlmConfiguration(default_provider=LlmProvider.DEEPSEEK)
    config.deepseek = ProviderConfig(
        api_key="sk-test-key-1234567890",
        default_model="deepseek-coder"
    )

    factory = LlmClientFactory(config)
    client = factory.create_default_client()

    assert client.provider == LlmProvider.DEEPSEEK
