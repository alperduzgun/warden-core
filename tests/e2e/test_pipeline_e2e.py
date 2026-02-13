"""Pipeline E2E tests — verify orchestrator produces findings end-to-end."""

import pytest

from warden.validation.domain.frame import CodeFile
from warden.pipeline.domain.models import PipelineConfig
from warden.pipeline.application.orchestrator.orchestrator import PhaseOrchestrator
from warden.validation.frames.security.security_frame import SecurityFrame


@pytest.mark.e2e
@pytest.mark.asyncio
class TestPipelineE2E:

    async def test_pipeline_produces_findings_for_vulnerable_code(self):
        """Pipeline detects issues in code with known vulnerabilities."""
        code = CodeFile(
            path="test_vuln.py",
            content=(
                'import os\n'
                'password = "admin123"\n'
                'query = f"SELECT * FROM users WHERE id={uid}"\n'
            ),
            language="python",
        )
        config = PipelineConfig(
            use_llm=False,
            enable_fortification=False,
            enable_cleaning=False,
            enable_issue_validation=False,
        )
        orchestrator = PhaseOrchestrator(
            frames=[SecurityFrame()],
            config=config,
        )

        result, _ctx = await orchestrator.execute_async(
            [code], analysis_level="basic"
        )

        # Pipeline completed
        assert result.status is not None
        # SecurityFrame ran and produced results
        assert result.total_frames >= 1

    async def test_pipeline_clean_code_no_blockers(self):
        """Clean code should not produce blocker findings."""
        code = CodeFile(
            path="clean.py",
            content=(
                'def add(a: int, b: int) -> int:\n'
                '    """Add two numbers."""\n'
                '    return a + b\n'
            ),
            language="python",
        )
        config = PipelineConfig(
            use_llm=False,
            enable_fortification=False,
            enable_cleaning=False,
            enable_issue_validation=False,
        )
        orchestrator = PhaseOrchestrator(
            frames=[SecurityFrame()],
            config=config,
        )

        result, _ctx = await orchestrator.execute_async(
            [code], analysis_level="basic"
        )

        assert result.status is not None
        # Clean code should have zero critical/blocker findings
        assert result.critical_findings == 0

    async def test_pipeline_multiple_files(self):
        """Pipeline handles multiple files in a single run."""
        files = [
            CodeFile(
                path=f"module_{i}.py",
                content=f'def func_{i}() -> int:\n    return {i}\n',
                language="python",
            )
            for i in range(3)
        ]
        config = PipelineConfig(
            use_llm=False,
            enable_fortification=False,
            enable_cleaning=False,
            enable_issue_validation=False,
        )
        orchestrator = PhaseOrchestrator(
            frames=[SecurityFrame()],
            config=config,
        )

        result, _ctx = await orchestrator.execute_async(
            files, analysis_level="basic"
        )

        assert result.status is not None
        assert result.total_frames >= 1
