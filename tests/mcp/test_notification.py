
import pytest
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from warden.mcp.application.mcp_service import MCPService
from warden.mcp.ports.transport import ITransport

class MockTransport(ITransport):
    def __init__(self):
        self.messages = []
        self._is_open = True
    
    async def read_message(self):
        # Keep connection open for a bit then close
        await asyncio.sleep(5)
        return None

    async def write_message(self, message: str):
        self.messages.append(message)
    
    async def close(self):
        self._is_open = False
        
    @property
    def is_open(self):
        return self._is_open

@pytest.mark.asyncio
async def test_report_file_notification(tmp_path):
    """Test that modifying the report file triggers a notification."""
    
    # Setup
    project_root = tmp_path
    reports_dir = project_root / ".warden" / "reports"
    reports_dir.mkdir(parents=True)
    report_file = reports_dir / "warden_report.json"
    report_file.write_text("{}")
    
    # Service
    transport = MockTransport()
    service = MCPService(transport, project_root)
    
    # Start service task
    service_task = asyncio.create_task(service.start())
    
    # Allow startup
    await asyncio.sleep(1)
    
    # Modify file
    assert report_file.exists()
    # Force mtime update
    new_content = json.dumps({"updated": True, "timestamp": str(asyncio.get_event_loop().time())})
    report_file.write_text(new_content)
    os.utime(report_file, None) 
    
    # Wait for watcher
    await asyncio.sleep(3)
    
    # Verify notification
    found = False
    for msg in transport.messages:
        data = json.loads(msg)
        if data.get("method") == "notifications/resources/updated":
            if data["params"]["uri"] == "warden://reports/latest":
                found = True
                break
    
    # Cleanup
    await transport.close()
    service_task.cancel()
    try:
        await service_task
    except asyncio.CancelledError:
        pass
        
    assert found, f"Notification not found in messages: {transport.messages}"
