"""
Tests for ResilienceFrame (Chaos 2.0).

Validates LLM-driven resilience validation logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from warden.validation.domain.frame import CodeFile, Finding
from warden.validation.domain.enums import FramePriority


@pytest.fixture
def ResilienceFrame():
    from warden.validation.infrastructure.frame_registry import FrameRegistry
    registry = FrameRegistry()
    registry.discover_all()
    cls = registry.get_frame_by_id("resilience")
    if not cls:
        pytest.skip("ResilienceFrame not found in registry")
    return cls

@pytest.mark.asyncio
async def test_resilience_frame_metadata(ResilienceFrame):
    """Test ResilienceFrame has correct metadata."""
    frame = ResilienceFrame()

    assert frame.name == "Resilience Architecture Analysis"
    assert frame.frame_id == "resilience"
    assert frame.is_blocker is False  # Advisory
    assert frame.priority == FramePriority.HIGH


@pytest.mark.asyncio
async def test_resilience_frame_execution_with_mock_llm(ResilienceFrame):
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
    
    frame = ResilienceFrame()
    frame.llm_service = mock_llm_service
    
    # Patch the _analyze_with_llm method on the CLASS/Instance
    # Since ResilienceFrame is dynamic, we patch on the class or instance.
    # Note: patching 'warden.validation.frames.resilience.resilience_frame.ResilienceFrame' string won't work.
    # We must patch the object directly.
    
    with patch.object(ResilienceFrame, '_analyze_with_llm', new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = mock_findings
        
        result = await frame.execute(code_file)

        assert result.status == "warning"  # High severity = warning (if not critical blocker)
        assert result.issues_found == 1
        assert result.findings[0].message == "Missing timeout in network call"


@pytest.mark.asyncio
async def test_resilience_frame_passes_on_empty_findings(ResilienceFrame):
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
