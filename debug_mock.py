import asyncio
import os
import sys
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path
from datetime import datetime

# Add src to sys.path
sys.path.append(os.path.abspath("src"))

from warden.pipeline.application.orchestrator.frame_runner import FrameRunner
from warden.pipeline.domain.models import PipelineConfig, ValidationPipeline
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import ValidationFrame, CodeFile, Finding

async def test():
    frame = MagicMock(spec=ValidationFrame)
    frame.frame_id = "test_security"
    frame.name = "Security"
    frame.is_blocker = False
    frame.config = {}
    frame.requires_frames = []
    frame.requires_config = []
    frame.requires_context = []

    async def _hang(code_file, **kwargs):
        await asyncio.sleep(999)
    frame.execute_async = AsyncMock(side_effect=_hang)

    context = PipelineContext(
        pipeline_id="test",
        started_at=datetime.now(),
        file_path=Path("/tmp/test.py"),
        source_code="print('hello')",
        project_root=Path("/tmp")
    )
    context.file_contexts = {}
    context.frame_results = {}

    pipeline = ValidationPipeline()

    runner = FrameRunner(config=PipelineConfig(force_scan=True))

    # Mock calculate_per_file_timeout to be very small
    import warden.pipeline.application.orchestrator.frame_runner as fr_mod
    fr_mod.calculate_per_file_timeout = lambda *args, **kwargs: 0.01

    code_file = CodeFile(path="/tmp/big.py", content="x = 1\n" * 100, language="python")

    result = await runner.execute_frame_with_rules_async(context, frame, [code_file], pipeline)
    if result:
        print(f"Result status: {result.status}")
        print(f"Findings: {len(result.findings)}")
        for f in result.findings:
             print(f"Finding: {f.id} - {f.message}")
    else:
        print("Result is None")

if __name__ == "__main__":
    asyncio.run(test())
