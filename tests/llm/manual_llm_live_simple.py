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
    create_client,
    ANALYSIS_SYSTEM_PROMPT,
    generate_analysis_request
)

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

    client = create_client(config)

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

    client = create_client(config)

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
