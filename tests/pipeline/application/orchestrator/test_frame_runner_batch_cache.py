"""Tests for FindingsCache integration in the BatchExecutable code path.

Issue #98: BatchExecutable frames (SecurityFrame, PropertyFrame, OrphanFrame) were
bypassing the cross-scan findings cache because they used execute_batch_async()
directly, which skipped the per-file cache lookup/store in execute_single_file_async().

These tests verify that the batch execution path now:
- Checks the findings cache before dispatching files to execute_batch_async
- Returns cached results on hit (skipping LLM)
- Stores fresh results to the cache after execute_batch_async completes
- Respects --no-cache (force_scan) flag
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.pipeline.application.orchestrator.findings_cache import FindingsCache
from warden.pipeline.application.orchestrator.frame_runner import FrameRunner
from warden.pipeline.domain.models import PipelineConfig
from warden.validation.domain.frame import CodeFile, Finding, ValidationFrame
from warden.validation.domain.frame import FrameResult as CodeFrameResult
from warden.validation.domain.mixins import BatchExecutable

from .conftest import make_code_file, make_context, make_finding, make_pipeline


# ---------------------------------------------------------------------------
# Helpers: a minimal BatchExecutable frame for testing
# ---------------------------------------------------------------------------


class _StubBatchFrame(ValidationFrame, BatchExecutable):
    """A trivial BatchExecutable frame for testing cache integration."""

    frame_id = "stub_batch"
    name = "Stub Batch Frame"
    description = "Test-only batch frame"
    category = "global"
    priority = "critical"
    scope = "file"
    is_blocker = True
    version = "1.0.0"
    author = "test"
    applicability = []

    def __init__(self) -> None:
        super().__init__({})
        self.execute_batch_calls: list[list[str]] = []

    async def execute_async(self, code_file: CodeFile) -> CodeFrameResult:
        raise NotImplementedError("batch-only frame")

    async def execute_batch_async(
        self, code_files: list[CodeFile], context: Any = None
    ) -> list[CodeFrameResult]:
        self.execute_batch_calls.append([cf.path for cf in code_files])
        results = []
        for cf in code_files:
            finding = Finding(
                id="STUB-001",
                severity="high",
                message=f"stub finding for {cf.path}",
                location=f"{cf.path}:1",
            )
            results.append(
                CodeFrameResult(
                    frame_id=self.frame_id,
                    frame_name=self.name,
                    status="warning",
                    duration=0.1,
                    issues_found=1,
                    is_blocker=False,
                    findings=[finding],
                )
            )
        return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBatchFindingsCacheIntegration:
    """Verify that BatchExecutable frames use the cross-scan findings cache."""

    @pytest.fixture()
    def project_root(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.fixture()
    def runner(self, project_root: Path) -> FrameRunner:
        config = PipelineConfig()
        return FrameRunner(config=config)

    @pytest.fixture()
    def frame(self) -> _StubBatchFrame:
        return _StubBatchFrame()

    @pytest.fixture()
    def pipeline(self) -> Any:
        return make_pipeline()

    @pytest.fixture()
    def context(self, project_root: Path) -> Any:
        return make_context(project_root=project_root)

    @pytest.fixture()
    def code_files(self) -> list[CodeFile]:
        return [
            make_code_file(path="src/a.py", content="print('a')\n"),
            make_code_file(path="src/b.py", content="print('b')\n"),
        ]

    @pytest.mark.asyncio
    async def test_first_scan_populates_cache(
        self, runner: FrameRunner, frame: _StubBatchFrame, context, pipeline, code_files, project_root
    ):
        """On the first scan, all files go to execute_batch_async and results are cached."""
        result = await runner.execute_frame_with_rules_async(context, frame, code_files, pipeline)

        assert result is not None
        # Frame was called with all files (one batch call)
        assert len(frame.execute_batch_calls) >= 1
        all_called = [f for call in frame.execute_batch_calls for f in call]
        assert set(all_called) == {"src/a.py", "src/b.py"}

        # Verify findings were stored in cache
        cache = runner._findings_cache
        assert cache is not None
        for cf in code_files:
            cached = cache.get_findings(frame.frame_id, str(cf.path), cf.content)
            assert cached is not None, f"Expected cache entry for {cf.path}"
            assert len(cached) == 1
            assert cached[0].id == "STUB-001"

    @pytest.mark.asyncio
    async def test_second_scan_uses_cache(
        self, runner: FrameRunner, frame: _StubBatchFrame, context, pipeline, code_files, project_root
    ):
        """On a second scan with unchanged files, findings come from cache, not LLM."""
        # First scan: populate cache
        await runner.execute_frame_with_rules_async(context, frame, code_files, pipeline)
        first_call_count = len(frame.execute_batch_calls)

        # Reset context for second run (frame_results tracks per-run state)
        context2 = make_context(project_root=project_root)

        # Second scan: should hit cache, no new batch calls
        result2 = await runner.execute_frame_with_rules_async(context2, frame, code_files, pipeline)

        assert result2 is not None
        # No additional batch calls (all served from cache)
        assert len(frame.execute_batch_calls) == first_call_count

        # Result should still contain the findings
        assert result2.findings is not None
        assert len(result2.findings) == 2  # one finding per file

    @pytest.mark.asyncio
    async def test_changed_file_causes_cache_miss(
        self, runner: FrameRunner, frame: _StubBatchFrame, context, pipeline, code_files, project_root
    ):
        """If a file's content changes, it is a cache miss and goes to the frame."""
        # First scan: populate cache
        await runner.execute_frame_with_rules_async(context, frame, code_files, pipeline)
        first_call_count = len(frame.execute_batch_calls)

        # Change one file's content
        changed_files = [
            make_code_file(path="src/a.py", content="print('a_v2')\n"),  # changed
            make_code_file(path="src/b.py", content="print('b')\n"),  # unchanged
        ]

        context2 = make_context(project_root=project_root)
        await runner.execute_frame_with_rules_async(context2, frame, changed_files, pipeline)

        # Only the changed file should have been sent to batch
        new_calls = frame.execute_batch_calls[first_call_count:]
        all_new_files = [f for call in new_calls for f in call]
        assert "src/a.py" in all_new_files
        assert "src/b.py" not in all_new_files

    @pytest.mark.asyncio
    async def test_force_scan_bypasses_cache(
        self, frame: _StubBatchFrame, context, pipeline, code_files, project_root
    ):
        """With force_scan=True (--no-cache), the findings cache is not used."""
        config = PipelineConfig()
        config.force_scan = True
        runner = FrameRunner(config=config)

        await runner.execute_frame_with_rules_async(context, frame, code_files, pipeline)

        # Cache should not have been initialised
        assert runner._findings_cache is None

        # All files should have been sent to batch
        all_called = [f for call in frame.execute_batch_calls for f in call]
        assert set(all_called) == {"src/a.py", "src/b.py"}

    @pytest.mark.asyncio
    async def test_clean_file_cached_as_empty_list(
        self, runner: FrameRunner, context, pipeline, project_root
    ):
        """Files with zero findings should cache as [] and be skipped on re-scan."""

        class CleanBatchFrame(_StubBatchFrame):
            frame_id = "clean_batch"

            async def execute_batch_async(self, code_files, context=None):
                self.execute_batch_calls.append([cf.path for cf in code_files])
                return [
                    CodeFrameResult(
                        frame_id=self.frame_id,
                        frame_name=self.name,
                        status="passed",
                        duration=0.1,
                        issues_found=0,
                        is_blocker=False,
                        findings=[],
                    )
                    for _ in code_files
                ]

        frame = CleanBatchFrame()
        files = [make_code_file(path="src/clean.py", content="x = 1\n")]

        # First scan
        await runner.execute_frame_with_rules_async(context, frame, files, pipeline)
        assert len(frame.execute_batch_calls) == 1

        # Verify cache stores empty list (not None)
        cache = runner._findings_cache
        assert cache is not None
        cached = cache.get_findings(frame.frame_id, "src/clean.py", "x = 1\n")
        assert cached is not None
        assert cached == []

        # Second scan: cache hit, no batch call
        context2 = make_context(project_root=project_root)
        await runner.execute_frame_with_rules_async(context2, frame, files, pipeline)
        assert len(frame.execute_batch_calls) == 1  # no new calls
