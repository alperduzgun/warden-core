"""
Tests for ResilienceFrame (Chaos 2.0).

Validates LLM-driven resilience validation logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from warden.validation.frames.resilience.resilience_frame import ResilienceFrame
from warden.validation.domain.frame import CodeFile, Finding
from warden.validation.domain.enums import FramePriority


@pytest.mark.asyncio
async def test_resilience_frame_metadata():
    """Test ResilienceFrame has correct metadata."""
    frame = ResilienceFrame()

    assert frame.name == "Resilience Architecture Analysis"
    assert frame.frame_id == "resilience"
    assert frame.is_blocker is False  # Advisory
    assert frame.priority == FramePriority.HIGH


@pytest.mark.asyncio
async def test_resilience_frame_execution_with_mock_llm():
    """Test ResilienceFrame execution with mocked LLM service."""
    code = '''
import requests

def fetch_data(url):
    # BAD: No timeout
    return requests.get(url).json()
'''
    code_file = CodeFile(
        path="test_client.py",
        content=code,
        language="python",
    )

    # Mock LLM Service
    mock_llm_service = MagicMock()
    mock_llm_service.analyze_with_llm = AsyncMock()
    
    # Mock LLM response
    mock_findings = [
        Finding(
            id="resilience-llm-1",
            severity="high",
            message="Missing timeout in network call",
            location="test_client.py:5",
            detail="Requests without timeouts can hang indefinitely.",
            code="requests.get(url)"
        )
    ]
    
    # Patch the _analyze_with_llm method or dependencies
    # Since ResilienceFrame._analyze_with_llm is internal, we can mock the llm_service injection
    
    frame = ResilienceFrame()
    frame.llm_service = mock_llm_service
    
    # We need to mock the internal call or ensure the frame uses the injected service
    # The current implementation of ResilienceFrame uses self.llm_service
    
    # However, ResilienceFrame implementation details (from previous turns):
    # It calls `self.llm_service.complete_async`? Or `analyze_with_llm`?
    # Let's assume we need to patch the method that does the actual work or the LLM client.
    
    # For now, let's patch the `_analyze_with_llm` method directly to avoid dependency on complex LLM mocking
    with patch.object(ResilienceFrame, '_analyze_with_llm', new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = mock_findings
        
        result = await frame.execute(code_file)

        assert result.status == "warning"  # High severity = warning (if not critical blocker)
        assert result.issues_found == 1
        assert result.findings[0].message == "Missing timeout in network call"


@pytest.mark.asyncio
async def test_resilience_frame_passes_on_empty_findings():
    """Test ResilienceFrame returns passed status when no issues found."""
    code_file = CodeFile(
        path="safe.py",
        content="print('hello')",
        language="python",
    )

    frame = ResilienceFrame()
    
    with patch.object(ResilienceFrame, '_analyze_with_llm', new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = []
        
        result = await frame.execute(code_file)

        assert result.status == "passed"
        assert result.issues_found == 0
