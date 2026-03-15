"""Scan performance benchmarks with SLA targets.

Validates that scan performance doesn't regress beyond defined thresholds.
Run with: pytest tests/benchmark/ -x --timeout=120 -v

SLA Targets:
- basic level: <30s for 20 files (no LLM)
- Pipeline overhead: <5s for setup + teardown
- Memory: <200MB peak for 20 files
"""

from __future__ import annotations

import asyncio
import time
import tracemalloc
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from warden.pipeline import PipelineConfig
from warden.pipeline.application.orchestrator.orchestrator import PhaseOrchestrator
from warden.pipeline.domain.enums import AnalysisLevel, PipelineStatus
from warden.validation.domain.frame import CodeFile
from warden.validation.frames import SecurityFrame


def _generate_python_files(count: int) -> list[CodeFile]:
    """Generate N synthetic Python files with realistic content."""
    files = []
    for i in range(count):
        content = f'''"""Module {i}: auto-generated for benchmark."""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class Service{i}:
    """Service handler for module {i}."""

    def __init__(self, config: dict):
        self.config = config
        self.name = "service_{i}"

    def process(self, data: Optional[str] = None) -> dict:
        """Process incoming data."""
        if data is None:
            logger.warning("No data provided for %s", self.name)
            return {{"status": "empty"}}
        result = self._transform(data)
        logger.info("Processed %d bytes in %s", len(data), self.name)
        return {{"status": "ok", "result": result}}

    def _transform(self, raw: str) -> str:
        return raw.strip().lower()

    def validate(self, value: str) -> bool:
        if not value:
            raise ValueError("Value cannot be empty")
        if len(value) > 10000:
            raise ValueError("Value too long")
        return True


def helper_{i}(x: int, y: int) -> int:
    """Helper function for module {i}."""
    if x < 0 or y < 0:
        raise ValueError("Negative values not allowed")
    return x + y
'''
        files.append(CodeFile(path=f"module_{i}.py", content=content, language="python"))
    return files


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock()
    llm.complete_async = AsyncMock(return_value=MagicMock(content="{}"))
    llm.provider = MagicMock(value="mock")
    llm.config = None
    llm.get_usage = MagicMock(return_value={
        "total_tokens": 0, "prompt_tokens": 0,
        "completion_tokens": 0, "request_count": 0,
    })
    return llm


class TestBasicLevelPerformance:
    """SLA: basic level scan must complete within time and memory bounds."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_20_files_under_30s(self, project_root: Path) -> None:
        """Basic scan of 20 files must complete in <30s."""
        files = _generate_python_files(20)
        config = PipelineConfig(
            analysis_level=AnalysisLevel.BASIC,
            use_llm=False,
            enable_fortification=False,
            enable_cleaning=False,
            enable_issue_validation=False,
            timeout=60,
        )

        orchestrator = PhaseOrchestrator(
            frames=[SecurityFrame()],
            config=config,
            project_root=project_root,
        )

        start = time.monotonic()
        result, context = await orchestrator.execute_async(files, analysis_level="basic")
        elapsed = time.monotonic() - start

        assert result.status in (PipelineStatus.COMPLETED, PipelineStatus.FAILED, PipelineStatus.COMPLETED_WITH_FAILURES)
        assert elapsed < 30, f"Basic scan took {elapsed:.1f}s (SLA: <30s)"

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_single_file_under_5s(self, project_root: Path) -> None:
        """Single file basic scan must complete in <5s."""
        files = _generate_python_files(1)
        config = PipelineConfig(
            analysis_level=AnalysisLevel.BASIC,
            use_llm=False,
            enable_fortification=False,
            enable_cleaning=False,
            enable_issue_validation=False,
            timeout=30,
        )

        orchestrator = PhaseOrchestrator(
            frames=[SecurityFrame()],
            config=config,
            project_root=project_root,
        )

        start = time.monotonic()
        result, _ = await orchestrator.execute_async(files, analysis_level="basic")
        elapsed = time.monotonic() - start

        assert elapsed < 5, f"Single file scan took {elapsed:.1f}s (SLA: <5s)"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_memory_under_200mb(self, project_root: Path) -> None:
        """Peak memory during 20-file scan must be <200MB."""
        files = _generate_python_files(20)
        config = PipelineConfig(
            analysis_level=AnalysisLevel.BASIC,
            use_llm=False,
            enable_fortification=False,
            enable_cleaning=False,
            enable_issue_validation=False,
            timeout=60,
        )

        orchestrator = PhaseOrchestrator(
            frames=[SecurityFrame()],
            config=config,
            project_root=project_root,
        )

        tracemalloc.start()
        await orchestrator.execute_async(files, analysis_level="basic")
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak / (1024 * 1024)
        assert peak_mb < 200, f"Peak memory: {peak_mb:.1f}MB (SLA: <200MB)"


class TestStandardLevelPerformance:
    """SLA: standard level scan with mock LLM."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(300)
    async def test_5_files_completes(self, project_root: Path, mock_llm: AsyncMock) -> None:
        """Standard scan of 5 files with mock LLM must complete within 180s."""
        files = _generate_python_files(5)
        config = PipelineConfig(
            analysis_level=AnalysisLevel.STANDARD,
            use_llm=True,
            enable_fortification=False,
            enable_cleaning=False,
            timeout=180,
        )

        orchestrator = PhaseOrchestrator(
            frames=[SecurityFrame()],
            config=config,
            project_root=project_root,
            llm_service=mock_llm,
        )

        start = time.monotonic()
        result, _ = await orchestrator.execute_async(files, analysis_level="standard")
        elapsed = time.monotonic() - start

        assert result.status in (PipelineStatus.COMPLETED, PipelineStatus.FAILED, PipelineStatus.COMPLETED_WITH_FAILURES)
        assert elapsed < 180, f"Standard scan (mock) took {elapsed:.1f}s (SLA: <180s)"
