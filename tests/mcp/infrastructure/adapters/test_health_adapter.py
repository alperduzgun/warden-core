
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from warden.mcp.infrastructure.adapters.health_adapter import HealthAdapter

@pytest.fixture
def adapter(tmp_path):
    return HealthAdapter(project_root=tmp_path)

def test_check_api_key_present_from_env(adapter):
    with patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-test'}, clear=True):
        assert adapter._check_api_key_present('openai') is True

def test_check_api_key_present_from_dotnet_env(adapter, tmp_path):
    # Create .env file with odd formatting
    env_file = tmp_path / ".env"
    env_file.write_text('OPENAI_API_KEY = "sk-spaced-and-quoted"')
    
    with patch.dict('os.environ', {}, clear=True):
        assert adapter._check_api_key_present('openai') is True

def test_check_api_key_missing(adapter):
    with patch.dict('os.environ', {}, clear=True):
        assert adapter._check_api_key_present('openai') is False

def test_check_api_key_local_provider(adapter):
    assert adapter._check_api_key_present('ollama') is True

@pytest.mark.asyncio
async def test_health_check_returns_valid_result(adapter):
    result = await adapter._health_check_async()
    assert result.is_error is False
    assert result.content[0]["type"] == "text"
    import json
    data = json.loads(result.content[0]["text"])
    assert data["status"] in ["ok", "degraded"]
