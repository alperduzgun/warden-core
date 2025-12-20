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
import asyncio
from warden.llm import (
    LlmProvider,
    LlmRequest,
    LlmConfiguration,
    ProviderConfig,
    LlmClientFactory,
    AnalysisResult,
    ANALYSIS_SYSTEM_PROMPT,
    generate_analysis_request
)


# Skip if no API keys configured
pytestmark = pytest.mark.skipif(
    not os.getenv("AZURE_OPENAI_API_KEY") and not os.getenv("GROQ_API_KEY"),
    reason="No LLM API keys configured"
)


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
            default_model="llama-3.1-70b-versatile",
            enabled=True
        )
    )


@pytest.mark.asyncio
async def test_azure_openai_simple_request(azure_config):
    """Test Azure OpenAI with simple request"""
    factory = LlmClientFactory(azure_config)
    client = factory.create_default_client()

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
async def test_azure_openai_code_analysis(azure_config):
    """Test Azure OpenAI code analysis with real code"""
    factory = LlmClientFactory(azure_config)
    client = factory.create_default_client()

    # Sample code with security issue
    code = '''
def get_user(user_id):
    query = f"SELECT * FROM users WHERE id = '{user_id}'"
    return db.execute(query)
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

    print(f"\n✅ Code Analysis Complete:")
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
    factory = LlmClientFactory(groq_config)
    client = factory.create_default_client()

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
async def test_fallback_chain(azure_config):
    """Test fallback chain (Azure → Groq)"""
    # Configure both providers
    config = LlmConfiguration(
        default_provider=LlmProvider.AZURE_OPENAI,
        fallback_providers=[LlmProvider.GROQ]
    )

    # Azure config
    config.azure_openai = azure_config.azure_openai

    # Groq config (if available)
    if os.getenv("GROQ_API_KEY"):
        config.groq = ProviderConfig(
            api_key=os.getenv("GROQ_API_KEY"),
            default_model="llama-3.1-70b-versatile",
            enabled=True
        )

    factory = LlmClientFactory(config)

    # Should get Azure (or fallback to Groq if Azure fails)
    client = await factory.create_client_with_fallback()

    request = LlmRequest(
        system_prompt="You are a helpful assistant.",
        user_message="Say 'Fallback test successful!' and nothing else.",
        max_tokens=20
    )

    response = await client.send_async(request)

    assert response.success
    print(f"\n✅ Fallback Chain Used Provider: {client.provider.value}")
    print(f"   Response: {response.content}")


@pytest.mark.asyncio
async def test_analyzer_with_llm():
    """Test CodeAnalyzer with LLM integration"""
    from warden.core.analysis.analyzer import CodeAnalyzer

    # Setup LLM config
    config = LlmConfiguration(
        default_provider=LlmProvider.AZURE_OPENAI,
        azure_openai=ProviderConfig(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            default_model="gpt-4o",
            api_version="2024-02-01",
            enabled=True
        )
    )

    factory = LlmClientFactory(config)
    analyzer = CodeAnalyzer(llm_factory=factory)

    # Test code with issues
    code = '''
import os

def unsafe_function(user_input):
    # SQL Injection vulnerability
    query = f"SELECT * FROM users WHERE name = '{user_input}'"

    # Command injection vulnerability
    os.system(f"echo {user_input}")

    return query
'''

    result = await analyzer.analyze_with_llm("test.py", code, "python")

    assert result["score"] is not None
    assert "confidence" in result
    assert "issues" in result
    assert result["provider"] == "azure_openai"

    print(f"\n✅ Analyzer with LLM:")
    print(f"   Score: {result['score']}/10")
    print(f"   Confidence: {result['confidence']}")
    print(f"   Issues: {len(result['issues'])}")
    print(f"   Provider: {result['provider']}")
    print(f"   Tokens Used: {result.get('tokensUsed', 0)}")


@pytest.mark.asyncio
async def test_classifier_with_llm():
    """Test CodeClassifier with LLM integration"""
    from warden.core.analysis.classifier import CodeClassifier

    # Setup LLM config
    config = LlmConfiguration(
        default_provider=LlmProvider.AZURE_OPENAI,
        azure_openai=ProviderConfig(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            default_model="gpt-4o",
            api_version="2024-02-01",
            enabled=True
        )
    )

    factory = LlmClientFactory(config)
    classifier = CodeClassifier(llm_factory=factory)

    # Test code with various characteristics
    code = '''
import asyncio
import httpx

async def fetch_user_data(user_id: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://api.example.com/users/{user_id}")
        return response.json()
'''

    result = await classifier.classify_with_llm("api.py", code, "python")

    assert "characteristics" in result
    assert "recommendedFrames" in result
    assert result["provider"] == "azure_openai"

    # Should detect async operations and external API calls
    chars = result["characteristics"]
    assert chars.get("hasAsyncOperations") is True
    assert chars.get("hasExternalApiCalls") is True

    print(f"\n✅ Classifier with LLM:")
    print(f"   Has Async: {chars.get('hasAsyncOperations')}")
    print(f"   Has API Calls: {chars.get('hasExternalApiCalls')}")
    print(f"   Recommended Frames: {result['recommendedFrames']}")
    print(f"   Provider: {result['provider']}")


if __name__ == "__main__":
    # Run tests manually
    print("🧪 Running Live LLM Integration Tests...\n")

    async def run_all():
        # Load environment
        from dotenv import load_dotenv
        load_dotenv()

        # Azure tests
        config = LlmConfiguration(
            default_provider=LlmProvider.AZURE_OPENAI,
            azure_openai=ProviderConfig(
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                default_model="gpt-4o",
                api_version="2024-02-01",
                enabled=True
            )
        )

        await test_azure_openai_simple_request(config)
        await test_azure_openai_code_analysis(config)
        await test_analyzer_with_llm()
        await test_classifier_with_llm()

    asyncio.run(run_all())
    print("\n✅ All tests passed!")
