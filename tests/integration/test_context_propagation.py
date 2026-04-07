import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.pipeline.application.executors.classification_executor import ClassificationExecutor
from warden.pipeline.domain.models import PipelineConfig
from warden.validation.domain.frame import CodeFile
from warden.analysis.domain.project_context import ProjectType, Framework


@pytest.mark.asyncio
async def test_classification_phase_propagates_context_to_llm():
    """
    Verify that architectural context (Project Type, Framework, etc.)
    is correctly propagated from PipelineContext to the LLM prompt.
    """
    # 1. Setup Mock LLM
    mock_llm = AsyncMock()
    mock_response = MagicMock()
    mock_response.success = True
    mock_response.content = """
    ```json
    {
        "selected_frames": ["security", "resilience"],
        "suppression_rules": [],
        "priorities": {},
        "reasoning": "Test reasoning based on project type"
    }
    ```
    """
    mock_llm.complete_async.return_value = mock_response

    # 2. Setup Pipeline Context with specific architectural data
    project_root = Path("/tmp/test_project")
    context = PipelineContext(
        pipeline_id="test-123",
        started_at=None,
        file_path=Path("main.py"),
        project_root=project_root,
        source_code="print('hello')",
        language="python",
    )

    # Populate context as if Pre-Analysis ran
    # Using Enum values to simulate real context
    substantive_content = (
        "from fastapi import FastAPI, Depends\n"
        "from fastapi.security import OAuth2PasswordBearer\n"
        "import httpx\n\n"
        "app = FastAPI()\n"
        "oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')\n\n"
        "async def get_current_user(token: str = Depends(oauth2_scheme)):\n"
        "    async with httpx.AsyncClient() as client:\n"
        "        r = await client.get('https://auth.example.com/verify',\n"
        "                             headers={'Authorization': f'Bearer {token}'})\n"
        "    return r.json()\n\n"
        "@app.get('/users/me')\n"
        "async def read_users_me(current_user=Depends(get_current_user)):\n"
        "    return current_user\n"
    )
    context.project_type = ProjectType.MICROSERVICE
    context.framework = Framework.FASTAPI
    # file_contexts must include "content" so the static pre-filter
    # uses the real source instead of falling back to empty string.
    context.file_contexts = {
        "main.py": {
            "context": "PRODUCTION",
            "summary": "Main entry point",
            "content": substantive_content,
        }
    }
    context.quality_score_before = 8.5

    # 3. Initialize Executor with mock frames (empty list prevents LLM call)
    mock_frame_security = MagicMock(frame_id="security", name="Security Analysis", description="Security checks")
    mock_frame_resilience = MagicMock(frame_id="resilience", name="Resilience Analysis", description="Resilience checks")
    mock_frames = [mock_frame_security, mock_frame_resilience]

    executor = ClassificationExecutor(
        config=PipelineConfig(enable_classification=True, force_scan=True),
        project_root=project_root,
        llm_service=mock_llm,
        frames=mock_frames,
        available_frames=mock_frames,
    )

    # 4. Execute Phase
    code_files = [CodeFile(path="main.py", content=substantive_content, language="python")]

    # We need to mock the internal LLMClassificationPhase import/init
    # to capture the instance or properly spy on it.
    # But since we modified the Executor to pass context, we can just run it
    # and check the calls to mock_llm.

    with (
        patch(
            "warden.pipeline.application.executors.classification_cache.ClassificationCache.get",
            return_value=None,
        ),
        # Bypass the static pre-filter so the LLM is always invoked.
        # This test verifies context propagation to the LLM prompt, not
        # the static pre-filter routing logic (covered separately).
        patch(
            "warden.classification.application.static_pre_filter.StaticPreFilter.batch_classify",
            return_value=({}, ["main.py"]),  # nothing pre-classified, all go to LLM
        ),
    ):
        await executor.execute_async(context, code_files)

    # 5. Verify LLM Interaction
    # The LLM should have been called with a prompt containing our context
    assert mock_llm.complete_async.called

    call_args = mock_llm.complete_async.call_args
    prompt_content = call_args.kwargs.get("prompt", "") or call_args[1].get("prompt", "") if call_args[1] else ""
    if not prompt_content and call_args[0]:
        prompt_content = call_args[0][0]

    # Assertions: Check if semantic context is in the prompt
    print(f"Captured Prompt: {prompt_content}")

    assert "PROJECT TYPE: microservice" in prompt_content.lower() or "microservice" in prompt_content.lower()
    assert "FRAMEWORK: fastapi" in prompt_content.lower() or "fastapi" in prompt_content.lower()
    assert "PRODUCTION" in prompt_content  # File context

    # Verify logger usage (traceability) check if possible
    # (Optional, usually requires checking logs or spying logger)
