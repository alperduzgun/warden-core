
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from warden.llm.providers.gemini import GeminiClient
from warden.llm.config import ProviderConfig
from warden.llm.types import LlmRequest

async def verify_gemini_security():
    print("🛡️ Verifying Gemini API Key Security...")
    
    # 1. Setup
    dummy_key = "AIzaSyDUMMYKEY12345"
    config = ProviderConfig(api_key=dummy_key, enabled=True)
    client = GeminiClient(config)
    
    request = LlmRequest(
        system_prompt="sys",
        user_message="hello",
        max_tokens=10
    )
    
    # 2. Mock httpx
    # We strip the decorator to test the raw logic if needed, 
    # but mocking the client context manager is cleaner.
    
    mock_post = AsyncMock()
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "response"}]}}],
        "usageMetadata": {}
    }
    
    mock_client = AsyncMock()
    mock_client.post = mock_post
    
    # Mock the context manager: async with httpx.AsyncClient(...) as client:
    mock_client_ctx = AsyncMock()
    mock_client_ctx.__aenter__.return_value = mock_client
    mock_client_ctx.__aexit__.return_value = None
    
    with patch("httpx.AsyncClient", return_value=mock_client_ctx):
        # 3. Execute
        await client.send_async(request)
        
        # 4. Verification
        # Get arguments passed to post()
        call_args = mock_post.call_args
        url = call_args[0][0]
        kwargs = call_args[1]
        headers = kwargs.get("headers", {})
        
        print(f"   URL: {url}")
        print(f"   Headers: {headers}")
        
        # Check URL for key
        if dummy_key in url:
            print("❌ SECURITY FAIL: API Key found in URL!")
            exit(1)
        else:
            print("✅ PASS: API Key NOT in URL.")
            
        # Check Headers for key
        if headers.get("x-goog-api-key") == dummy_key:
            print("✅ PASS: API Key found in Headers.")
        else:
            print("❌ FAIL: API Key NOT in Headers (Functionality broken?).")
            exit(1)

if __name__ == "__main__":
    asyncio.run(verify_gemini_security())
