
import asyncio
from warden.config.loader import load_config
from warden.llm.factory import LlmFactory
from warden.llm.types import LlmProvider
import logging

logging.basicConfig(level=logging.DEBUG)

async def check_factory():
    print("🔍 Reading Config (Full Loader)...")
    app_config = await load_config() # This returns the full AppConfig object
    config = app_config.llm # Extract LlmConfiguration
    
    print(f"   Provider: {config.default_provider}")
    print(f"   Smart Model: {config.smart_model}")
    print(f"   Fast Model: {config.fast_model}")
    print(f"   Ollama Enabled: {config.ollama.enabled}")
    print(f"   Ollama URL: {config.ollama.endpoint}")

    print("\n🏭 Creating Client...")
    client = LlmFactory.create_client(config)
    print(f"   Client Type: {type(client).__name__}")
    
    if hasattr(client, 'smart_client'):
        print(f"   Smart Client: {client.smart_client.provider}")
    if hasattr(client, 'fast_client'):
        print(f"   Fast Client: {client.fast_client.provider if client.fast_client else 'None'}")
    else:
        print("   Not an Orchestrated Client (No fast_client attr)")

if __name__ == "__main__":
    asyncio.run(check_factory())
