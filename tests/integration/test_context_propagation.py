
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from typing import Any, Dict, List

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.pipeline.application.executors.classification_executor import ClassificationExecutor
from warden.pipeline.domain.models import PipelineConfig
from warden.validation.domain.frame import CodeFile, ValidationFrame
from warden.analysis.domain.project_context import ProjectType, Framework

@pytest.mark.asyncio
async def test_classification_phase_propagates_context_to_llm():
    """
    Verify that architectural context (Project Type, Framework, etc.) 
    is correctly propagated from PipelineContext to the LLM prompt.
    """
    # 1. Setup Mock LLM
    mock_llm = AsyncMock()
    mock_llm.send_async.return_value.success = True
    mock_llm.send_async.return_value.content = """
    ```json
    {
        "selected_frames": ["security", "chaos"],
        "suppression_rules": [],
        "priorities": {},
        "reasoning": "Test reasoning based on project type"
    }
    ```
    """

    # 2. Setup Pipeline Context with specific architectural data
    project_root = Path("/tmp/test_project")
    context = PipelineContext(
        pipeline_id="test-123",
        started_at=None,
        file_path=Path("main.py"),
        project_root=project_root,
        source_code="print('hello')",
        language="python"
    )
    
    # Populate context as if Pre-Analysis ran
    # Using Enum values to simulate real context
    context.project_type = ProjectType.MICROSERVICE
    context.framework = Framework.FASTAPI
    context.file_contexts = {
        "main.py": {"context": "PRODUCTION", "summary": "Main entry point"}
    }
    context.quality_score_before = 8.5
    
    # 3. Initialize Executor
    executor = ClassificationExecutor(
        config=PipelineConfig(enable_classification=True),
        project_root=project_root,
        llm_service=mock_llm,
        frames=[],
        available_frames=[]
    )

    # 4. Execute Phase
    code_files = [CodeFile(path="main.py", content="print('hello')", language="python")]
    
    # We need to mock the internal LLMClassificationPhase import/init 
    # to capture the instance or properly spy on it. 
    # But since we modified the Executor to pass context, we can just run it 
    # and check the calls to mock_llm.
    
    await executor.execute_async(context, code_files)

    # 5. Verify LLM Interaction
    # The LLM should have been called with a prompt containing our context
    assert mock_llm.send_async.called
    
    call_args = mock_llm.send_async.call_args
    llm_request = call_args[0][0] # First arg is request object
    prompt_content = llm_request.user_message

    # Assertions: Check if semantic context is in the prompt
    print(f"Captured Prompt: {prompt_content}")

    assert "PROJECT TYPE: microservice" in prompt_content.lower() or "microservice" in prompt_content.lower()
    assert "FRAMEWORK: fastapi" in prompt_content.lower() or "fastapi" in prompt_content.lower()
    assert "PRODUCTION" in prompt_content # File context
    
    # Verify logger usage (traceability) check if possible
    # (Optional, usually requires checking logs or spying logger)

