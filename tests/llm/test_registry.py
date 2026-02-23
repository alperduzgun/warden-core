"""
Tests for LLM Provider Registry

Verifies registry-based factory pattern implementation.

Note: Due to Python's module import caching, provider self-registration
happens once per process. Tests work with this by ensuring providers
are registered before testing functionality.
"""

import pytest
from warden.llm.registry import ProviderRegistry
from warden.llm.types import LlmProvider
from warden.llm.config import ProviderConfig
from warden.llm.factory import _ensure_providers_registered


@pytest.fixture(scope="module", autouse=True)
def setup_registry():
    """Ensure providers are registered before any tests run"""
    _ensure_providers_registered()


def test_ensure_providers_registered():
    """_ensure_providers_registered should register all providers"""
    # Verify all providers are registered
    registered = set(ProviderRegistry.available())
    expected = {
        LlmProvider.ANTHROPIC,
        LlmProvider.DEEPSEEK,
        LlmProvider.QWENCODE,
        LlmProvider.OPENAI,
        LlmProvider.AZURE_OPENAI,
        LlmProvider.GROQ,
        LlmProvider.OLLAMA,
        LlmProvider.GEMINI,
        LlmProvider.CLAUDE_CODE,
        LlmProvider.CODEX,
    }

    assert registered == expected


def test_ensure_providers_idempotent():
    """Multiple calls to _ensure_providers_registered should be safe"""
    count_first = len(ProviderRegistry.available())

    _ensure_providers_registered()
    count_second = len(ProviderRegistry.available())

    assert count_first == count_second == 10


def test_registry_is_registered():
    """is_registered should return correct status"""
    assert ProviderRegistry.is_registered(LlmProvider.ANTHROPIC)
    assert ProviderRegistry.is_registered(LlmProvider.OLLAMA)
    assert ProviderRegistry.is_registered(LlmProvider.AZURE_OPENAI)


def test_registry_available_count():
    """Registry should have all 10 providers available"""
    assert len(ProviderRegistry.available()) == 10


def test_registry_create_anthropic():
    """Registry should create Anthropic client"""
    config = ProviderConfig(enabled=True, api_key="test-key", default_model="claude-3-5-sonnet-20241022")

    from warden.llm.providers.anthropic import AnthropicClient

    client = ProviderRegistry.create(LlmProvider.ANTHROPIC, config)

    assert isinstance(client, AnthropicClient)
    assert client.provider == LlmProvider.ANTHROPIC


def test_registry_create_ollama():
    """Registry should create Ollama client"""
    config = ProviderConfig(enabled=True, endpoint="http://localhost:11434", default_model="qwen2.5-coder:3b")

    from warden.llm.providers.ollama import OllamaClient

    client = ProviderRegistry.create(LlmProvider.OLLAMA, config)

    assert isinstance(client, OllamaClient)
    assert client.provider == LlmProvider.OLLAMA


def test_registry_create_openai():
    """Registry should create OpenAI client (not Azure)"""
    config = ProviderConfig(enabled=True, api_key="test-key", default_model="gpt-4o")

    from warden.llm.providers.openai import OpenAIClient

    client = ProviderRegistry.create(LlmProvider.OPENAI, config)

    assert isinstance(client, OpenAIClient)
    assert client.provider == LlmProvider.OPENAI


def test_registry_create_azure_openai():
    """Registry should create Azure OpenAI client with correct provider"""
    config = ProviderConfig(
        enabled=True, api_key="test-key", endpoint="https://test.openai.azure.com", default_model="gpt-4o"
    )

    from warden.llm.providers.openai import OpenAIClient

    client = ProviderRegistry.create(LlmProvider.AZURE_OPENAI, config)

    assert isinstance(client, OpenAIClient)
    assert client.provider == LlmProvider.AZURE_OPENAI


def test_registry_create_all_providers():
    """Verify we can create all registered providers"""
    providers_configs = {
        LlmProvider.ANTHROPIC: ProviderConfig(enabled=True, api_key="test"),
        LlmProvider.DEEPSEEK: ProviderConfig(enabled=True, api_key="test"),
        LlmProvider.QWENCODE: ProviderConfig(enabled=True, api_key="test"),
        LlmProvider.OPENAI: ProviderConfig(enabled=True, api_key="test"),
        LlmProvider.AZURE_OPENAI: ProviderConfig(
            enabled=True, api_key="test", endpoint="https://test.openai.azure.com"
        ),
        LlmProvider.GROQ: ProviderConfig(enabled=True, api_key="test"),
        LlmProvider.OLLAMA: ProviderConfig(enabled=True),
        LlmProvider.GEMINI: ProviderConfig(enabled=True, api_key="test"),
        LlmProvider.CLAUDE_CODE: ProviderConfig(enabled=True),
    }

    for provider, config in providers_configs.items():
        client = ProviderRegistry.create(provider, config)
        assert client.provider == provider
