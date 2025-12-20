"""
Simple Live LLM Test (No pytest required)

Tests real Azure OpenAI GPT-4o integration
"""

import asyncio
import os
import sys
import json

# Add project to path
sys.path.insert(0, '/Users/alper/Documents/Development/Personal/warden-core/src')

from warden.llm import (
    LlmProvider,
    LlmRequest,
    LlmConfiguration,
    ProviderConfig,
    LlmClientFactory,
    ANALYSIS_SYSTEM_PROMPT,
    generate_analysis_request
)
from warden.core.analysis.analyzer import CodeAnalyzer
from warden.core.analysis.classifier import CodeClassifier


async def test_azure_simple():
    """Test 1: Simple Azure OpenAI request"""
    print("\n🧪 Test 1: Azure OpenAI Simple Request")
    print("=" * 60)

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
    client = factory.create_default_client()

    request = LlmRequest(
        system_prompt="You are a helpful assistant.",
        user_message="Say 'Hello from Warden LLM!' and nothing else.",
        max_tokens=20,
        timeout_seconds=30
    )

    response = await client.send_async(request)

    if response.success:
        print(f"✅ SUCCESS")
        print(f"   Provider: {response.provider.value}")
        print(f"   Response: {response.content}")
        print(f"   Tokens: {response.total_tokens}")
        print(f"   Duration: {response.duration_ms}ms")
        return True
    else:
        print(f"❌ FAILED: {response.error_message}")
        return False


async def test_code_analysis():
    """Test 2: Code analysis with SQL injection detection"""
    print("\n🧪 Test 2: Code Analysis (SQL Injection Detection)")
    print("=" * 60)

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
    client = factory.create_default_client()

    # Vulnerable code
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

    if response.success:
        # LLM might return markdown code blocks, clean it
        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"❌ JSON Parse Error: {e}")
            print(f"   Raw Response: {response.content[:200]}...")
            return False
        print(f"✅ SUCCESS")
        print(f"   Score: {result['score']}/10")
        print(f"   Confidence: {result['confidence']}")
        print(f"   Issues Found: {len(result['issues'])}")

        # Check for SQL injection detection
        has_sql_injection = any(
            "sql" in issue.get("title", "").lower() or
            "injection" in issue.get("title", "").lower()
            for issue in result["issues"]
        )

        if has_sql_injection:
            print(f"   ✅ SQL Injection Detected!")
            sql_issue = next(
                issue for issue in result["issues"]
                if "sql" in issue.get("title", "").lower() or
                "injection" in issue.get("title", "").lower()
            )
            print(f"   Title: {sql_issue['title']}")
            print(f"   Severity: {sql_issue['severity']}")
            print(f"   Confidence: {sql_issue['confidence']}")
        else:
            print(f"   ⚠️  SQL Injection NOT detected (unexpected)")

        return True
    else:
        print(f"❌ FAILED: {response.error_message}")
        return False


async def test_analyzer_integration():
    """Test 3: CodeAnalyzer with LLM"""
    print("\n🧪 Test 3: CodeAnalyzer with LLM Integration")
    print("=" * 60)

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

    code = '''
import os

def unsafe_exec(user_cmd):
    os.system(user_cmd)  # Command injection!
'''

    result = await analyzer.analyze_with_llm("unsafe.py", code, "python")

    if result.get("score") is not None:
        print(f"✅ SUCCESS")
        print(f"   Score: {result['score']}/10")
        print(f"   Confidence: {result.get('confidence', 'N/A')}")
        print(f"   Issues: {len(result.get('issues', []))}")
        print(f"   Provider: {result.get('provider', 'N/A')}")
        print(f"   Tokens: {result.get('tokensUsed', 0)}")
        return True
    else:
        print(f"❌ FAILED: No score in result")
        return False


async def test_classifier_integration():
    """Test 4: CodeClassifier with LLM"""
    print("\n🧪 Test 4: CodeClassifier with LLM Integration")
    print("=" * 60)

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

    code = '''
import asyncio
import httpx

async def fetch_api(url: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()
'''

    result = await classifier.classify_with_llm("api.py", code, "python")

    if "characteristics" in result:
        chars = result["characteristics"]
        print(f"✅ SUCCESS")
        print(f"   Has Async: {chars.get('hasAsyncOperations', False)}")
        print(f"   Has API Calls: {chars.get('hasExternalApiCalls', False)}")
        print(f"   Recommended Frames: {result.get('recommendedFrames', [])}")
        print(f"   Provider: {result.get('provider', 'N/A')}")
        return True
    else:
        print(f"❌ FAILED: No characteristics in result")
        return False


async def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("🚀 Warden LLM Integration Live Tests")
    print("=" * 60)
    print(f"Provider: Azure OpenAI GPT-4o")
    print(f"Endpoint: {os.getenv('AZURE_OPENAI_ENDPOINT', 'Not set')}")
    print("=" * 60)

    # Load .env
    env_path = "/Users/alper/Documents/Development/Personal/warden-core/.env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    os.environ[key.strip()] = value.strip()

    # Check API key
    if not os.getenv("AZURE_OPENAI_API_KEY"):
        print("❌ ERROR: AZURE_OPENAI_API_KEY not found in environment")
        return

    # Run tests
    results = []

    results.append(await test_azure_simple())
    results.append(await test_code_analysis())
    results.append(await test_analyzer_integration())
    results.append(await test_classifier_integration())

    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)
    print(f"Total Tests: {len(results)}")
    print(f"Passed: {sum(results)}")
    print(f"Failed: {len(results) - sum(results)}")

    if all(results):
        print("\n✅ ALL TESTS PASSED!")
    else:
        print("\n❌ SOME TESTS FAILED")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
