
import asyncio
import os
import shutil
from pathlib import Path
from warden.mcp.infrastructure.adapters.config_adapter import ConfigAdapter
from warden.mcp.infrastructure.adapters.setup_resource_adapter import SetupResourceAdapter

# Mock Bridge
class MockBridge:
    pass

async def main():
    print("🧪 Verifying MCP Setup Tool & Protocol...")
    
    # localized test dir
    test_dir = Path("tests/verify/sandbox")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)
    
    # --- Verify Protocol Resource ---
    print("\nScenario 0: Verify Setup Protocol Resource")
    setup_adapter = SetupResourceAdapter(project_root=test_dir)
    protocol = setup_adapter.read_resource("warden://setup/guide")
    
    if protocol and "Warden Setup Protocol" in protocol:
        print("✅ Protocol Resource found and valid")
    else:
        print(f"❌ Protocol Resource failed. Content: {protocol[:50] if protocol else 'None'}")
        exit(1)

    # --- Verify Config Tool ---
    
    # Create adapter
    adapter = ConfigAdapter(project_root=test_dir, bridge=MockBridge())
    
    # 1. Configure Gemini
    print("\nScenario 1: Configure Gemini")
    params = {
        "provider": "gemini",
        "api_key": "fake_gemini_key_123",
        "model": "gemini-1.5-pro",
        "vector_db": "qdrant"
    }
    
    result = await adapter._configure_warden_async(params)
    
    print(f"Result: {result}")
    
    # Verify .env
    env_path = test_dir / ".env"
    if env_path.exists():
        content = env_path.read_text()
        print(f"\n.env Content:\n{content}")
        assert "GEMINI_API_KEY=fake_gemini_key_123" in content
    else:
        print("❌ .env not found")
        
    # Verify config.yaml
    config_path = test_dir / ".warden" / "config.yaml"
    if config_path.exists():
        content = config_path.read_text()
        print(f"\nconfig.yaml Content:\n{content}")
        assert "provider: gemini" in content
        assert "smart_model: gemini-1.5-pro" in content
        assert "provider: qdrant" in content # vector db
    else:
        print("❌ config.yaml not found")

    # 2. Re-configure with Ollama (Idempotency check)
    print("\nScenario 2: Re-configure Ollama (Idempotency)")
    params2 = {
        "provider": "ollama",
        "model": "qwen2.5-coder"
    }
    result2 = await adapter._configure_warden_async(params2)
    print(f"Result 2: {result2}")
    
    config_content = config_path.read_text()
    print(f"\nUpdated config.yaml:\n{config_content}")
    assert "provider: ollama" in config_content
    # API key should still be there in env
    assert "GEMINI_API_KEY=fake_gemini_key_123" in env_path.read_text()

    print("\n✅ Verification Complete!")

if __name__ == "__main__":
    asyncio.run(main())
