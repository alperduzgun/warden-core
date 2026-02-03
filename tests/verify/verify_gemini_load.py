
from warden.llm.providers.gemini import GeminiClient
from warden.llm.config import ProviderConfig

def main():
    print("Testing GeminiClient Import...")
    try:
        config = ProviderConfig(api_key="test", enabled=True)
        client = GeminiClient(config)
        assert client.provider == "gemini"
        print("✅ GeminiClient instantiated successfully")
    except Exception as e:
        print(f"❌ Failed: {e}")
        exit(1)

if __name__ == "__main__":
    main()
