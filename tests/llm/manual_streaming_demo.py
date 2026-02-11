"""
Manual demo of OpenAI streaming functionality.

This demonstrates the new streaming support for both OpenAI and Azure OpenAI.
Run this with real API credentials to see streaming in action.

Usage:
    python3 tests/llm/manual_streaming_demo.py
"""

import asyncio
import os
import sys

# Add project to path
sys.path.insert(0, '/Users/alper/Documents/Development/Personal/warden-core/src')

from warden.llm.providers.openai import OpenAIClient
from warden.llm.config import ProviderConfig
from warden.llm.types import LlmProvider


async def demo_openai_streaming():
    """Demo OpenAI streaming with real API (requires API key)."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("⚠️  OPENAI_API_KEY not set - skipping OpenAI demo")
        return

    print("\n" + "=" * 60)
    print("OpenAI Streaming Demo")
    print("=" * 60)

    config = ProviderConfig(
        api_key=api_key,
        endpoint="https://api.openai.com/v1",
        default_model="gpt-4o",
        enabled=True
    )

    client = OpenAIClient(config, LlmProvider.OPENAI)

    prompt = "Write a haiku about code quality in exactly 3 lines."
    print(f"\nPrompt: {prompt}\n")
    print("Streaming response:")
    print("-" * 60)

    try:
        async for chunk in client.stream_completion_async(
            prompt=prompt,
            system_prompt="You are a helpful assistant."
        ):
            print(chunk, end="", flush=True)
        print("\n" + "-" * 60)
        print("✅ Streaming completed successfully")
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_azure_openai_streaming():
    """Demo Azure OpenAI streaming with real API (requires API key)."""
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

    if not api_key or not endpoint:
        print("⚠️  Azure OpenAI credentials not set - skipping Azure demo")
        return

    print("\n" + "=" * 60)
    print("Azure OpenAI Streaming Demo")
    print("=" * 60)

    config = ProviderConfig(
        api_key=api_key,
        endpoint=endpoint,
        default_model="gpt-4o",
        api_version="2024-02-01",
        enabled=True
    )

    client = OpenAIClient(config, LlmProvider.AZURE_OPENAI)

    prompt = "Explain what streaming is in 2 sentences."
    print(f"\nPrompt: {prompt}\n")
    print("Streaming response:")
    print("-" * 60)

    try:
        async for chunk in client.stream_completion_async(
            prompt=prompt,
            system_prompt="You are a concise technical writer."
        ):
            print(chunk, end="", flush=True)
        print("\n" + "-" * 60)
        print("✅ Streaming completed successfully")
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_fallback_behavior():
    """Demo fallback to simulated streaming on error."""
    print("\n" + "=" * 60)
    print("Fallback Behavior Demo (No API Key)")
    print("=" * 60)

    # Create client with invalid credentials to trigger fallback
    config = ProviderConfig(
        api_key="invalid-key",
        endpoint="https://api.openai.com/v1",
        default_model="gpt-4o",
        enabled=True
    )

    client = OpenAIClient(config, LlmProvider.OPENAI)

    print("\nNote: This will fail SSE streaming and fall back to simulated chunks")
    print("-" * 60)

    try:
        chunks_received = 0
        async for chunk in client.stream_completion_async(
            prompt="Test",
            system_prompt="Test"
        ):
            chunks_received += 1
            if chunks_received <= 3:  # Show first few chunks
                print(f"Chunk {chunks_received}: '{chunk}'")

        print(f"Total chunks received: {chunks_received}")
        print("✅ Fallback mechanism worked")
    except Exception as e:
        print(f"❌ Error: {e}")


async def main():
    """Run all demos."""
    print("\n" + "=" * 60)
    print("OpenAI Streaming Implementation Demo")
    print("=" * 60)
    print("\nThis demo shows:")
    print("  1. True SSE streaming with OpenAI")
    print("  2. True SSE streaming with Azure OpenAI")
    print("  3. Fallback to simulated streaming on errors")
    print("\n" + "=" * 60)

    # Load .env if it exists
    env_path = "/Users/alper/Documents/Development/Personal/warden-core/.env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    os.environ[key.strip()] = value.strip()

    # Run demos
    await demo_openai_streaming()
    await demo_azure_openai_streaming()
    await demo_fallback_behavior()

    print("\n" + "=" * 60)
    print("Demo Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
