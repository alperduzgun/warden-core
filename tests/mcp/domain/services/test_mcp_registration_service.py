
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from warden.mcp.domain.services.mcp_registration_service import MCPRegistrationService

@pytest.fixture
def service():
    return MCPRegistrationService(warden_path="/usr/bin/warden")

def test_register_single_tool_success(service, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.parent.mkdir()
    
    with patch('warden.mcp.domain.services.mcp_registration_service.is_safe_to_create_dir', return_value=True):
         result = service._register_single_tool("TestTool", config_path, {"cmd": "warden"})
         
    assert result.status == "registered"
    assert config_path.exists()
    assert "warden" in config_path.read_text()

def test_register_single_tool_unsafe_dir(service, tmp_path):
    # Path that doesn't exist and is unsafe
    config_path = tmp_path / "unsafe" / "config.json"
    
    with patch('warden.mcp.domain.services.mcp_registration_service.is_safe_to_create_dir', return_value=False):
         result = service._register_single_tool("TestTool", config_path, {"cmd": "warden"})
         
    assert result.status == "skipped"
    assert result.message == "Unsafe directory creation prevented"
    assert not config_path.exists()

def test_idempotency_skip(service, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"mcpServers": {"warden": {"command": "/usr/bin/warden"}}}')
    
    result = service._register_single_tool("TestTool", config_path, {"cmd": "warden"})
    
    assert result.status == "skipped"
    assert result.message == "Already registered"
