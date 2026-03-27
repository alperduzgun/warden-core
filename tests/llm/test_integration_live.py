"""
Live LLM Integration Tests

These tests make REAL API calls to LLM providers.
Only run when API keys are configured.

Usage:
    export AZURE_OPENAI_API_KEY="..."
    python3 -m pytest tests/llm/test_integration_live.py -v
"""

import pytest
import os

from warden.llm import (
    LlmProvider,
    LlmRequest,
    LlmConfiguration,
    ProviderConfig,
    create_client,
    ANALYSIS_SYSTEM_PROMPT,
    generate_analysis_request
)


pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not os.getenv("AZURE_OPENAI_API_KEY") and not os.getenv("GROQ_API_KEY"),
        reason="No LLM API keys configured",
    ),
]


@pytest.fixture
def azure_config():
    """Azure OpenAI configuration from environment"""
    return LlmConfiguration(
        default_provider=LlmProvider.AZURE_OPENAI,
        azure_openai=ProviderConfig(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            default_model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            enabled=True
        )
    )


@pytest.fixture
def groq_config():
    """Groq configuration from environment"""
    return LlmConfiguration(
        default_provider=LlmProvider.GROQ,
        groq=ProviderConfig(
            api_key=os.getenv("GROQ_API_KEY"),
            default_model="llama-3.3-70b-versatile",
            enabled=True
        )
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("AZURE_OPENAI_API_KEY"), reason="No Azure OpenAI API key")
async def test_azure_openai_simple_request(azure_config):
    """Test Azure OpenAI with simple request"""
    client = create_client(azure_config)

    request = LlmRequest(
        system_prompt="You are a helpful assistant.",
        user_message="Say 'Hello from Warden!' and nothing else.",
        max_tokens=20,
        timeout_seconds=30
    )

    response = await client.send_async(request)

    assert response.success, f"Request failed: {response.error_message}"
    assert "Warden" in response.content or "warden" in response.content.lower()
    assert response.provider == LlmProvider.AZURE_OPENAI
    assert response.total_tokens is not None
    assert response.duration_ms > 0
    print(f"\n✅ Azure OpenAI Response: {response.content}")
    print(f"   Tokens: {response.total_tokens}, Duration: {response.duration_ms}ms")


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("AZURE_OPENAI_API_KEY"), reason="No Azure OpenAI API key")
async def test_azure_openai_code_analysis(azure_config):
    """Test Azure OpenAI code analysis with real code"""
    client = create_client(azure_config)

    # Sample code with security issue
    code = '''
def get_user(user_id):
    query = f"SELECT * FROM users WHERE id = '{user_id}'"
    return db.execute_async(query)
'''

    request = LlmRequest(
        system_prompt=ANALYSIS_SYSTEM_PROMPT,
        user_message=generate_analysis_request(code, "python", "test.py"),
        temperature=0.3,
        max_tokens=2000,
        timeout_seconds=60
    )

    response = await client.send_async(request)

    assert response.success, f"Analysis failed: {response.error_message}"
    assert response.content, "No content in response"

    # Parse JSON response
    import json
    result_data = json.loads(response.content)

    assert "score" in result_data
    assert "issues" in result_data
    assert "confidence" in result_data

    # Should detect SQL injection
    issues = result_data["issues"]
    has_sql_injection = any(
        "sql" in issue.get("title", "").lower() or
        "injection" in issue.get("title", "").lower()
        for issue in issues
    )

    print("\n✅ Code Analysis Complete:")
    print(f"   Score: {result_data['score']}/10")
    print(f"   Confidence: {result_data['confidence']}")
    print(f"   Issues Found: {len(issues)}")
    print(f"   SQL Injection Detected: {has_sql_injection}")

    # SQL injection should be detected with high confidence
    if has_sql_injection:
        sql_issue = next(
            issue for issue in issues
            if "sql" in issue.get("title", "").lower() or
            "injection" in issue.get("title", "").lower()
        )
        print(f"   SQL Issue Confidence: {sql_issue.get('confidence', 0)}")


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="No Groq API key")
async def test_groq_simple_request(groq_config):
    """Test Groq with simple request"""
    client = create_client(groq_config)

    request = LlmRequest(
        system_prompt="You are a helpful assistant.",
        user_message="Say 'Hello from Groq!' and nothing else.",
        max_tokens=20,
        timeout_seconds=30
    )

    response = await client.send_async(request)

    assert response.success, f"Request failed: {response.error_message}"
    assert response.provider == LlmProvider.GROQ
    print(f"\n✅ Groq Response: {response.content}")


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="No Groq API key for fallback chain test")
async def test_fallback_chain(azure_config):
    """Test fallback chain (Azure → Groq): with no Azure key, should fall back to Groq."""
    from warden.llm.factory import create_client_with_fallback_async

    config = LlmConfiguration(
        default_provider=LlmProvider.AZURE_OPENAI,
        fallback_providers=[LlmProvider.GROQ],
        groq=ProviderConfig(
            api_key=os.getenv("GROQ_API_KEY"),
            default_model="llama-3.3-70b-versatile",
            enabled=True,
        ),
    )

    client = await create_client_with_fallback_async(config)

    request = LlmRequest(
        system_prompt="You are a helpful assistant.",
        user_message="Say 'Fallback test successful!' and nothing else.",
        max_tokens=20,
    )

    response = await client.send_async(request)

    assert response.success
    print(f"\n✅ Fallback Chain Used Provider: {client.provider.value}")
    print(f"   Response: {response.content}")
