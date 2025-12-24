"""
Tests for Repository-Level Frame Caching in Orchestrator.

Tests cache hit/miss, performance optimization, and cache behavior.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from warden.pipeline.application.orchestrator import PipelineOrchestrator
from warden.pipeline.domain.models import PipelineConfig
from warden.validation.domain.frame import ValidationFrame, FrameResult, Finding, CodeFile
from warden.validation.domain.enums import FramePriority, FrameScope


class MockRepositoryFrame(ValidationFrame):
    """Mock repository-level frame for testing."""

    name = "MockRepositoryFrame"
    description = "Test repository frame"
    priority = FramePriority.HIGH
    scope = FrameScope.REPOSITORY_LEVEL  # Repository-level
    is_blocker = False

    def __init__(self, config=None):
        super().__init__(config)
        self.execution_count = 0

    async def execute(self, code_file, characteristics=None, memory_context=None):
        """Mock execution that tracks call count."""
        self.execution_count += 1
        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="passed",
            duration=1.0,
            issues_found=0,
            is_blocker=False,
            findings=[],
        )


class MockFileFrame(ValidationFrame):
    """Mock file-level frame for testing."""

    name = "MockFileFrame"
    description = "Test file frame"
    priority = FramePriority.MEDIUM
    scope = FrameScope.FILE_LEVEL  # File-level (no caching)
    is_blocker = False

    def __init__(self, config=None):
        super().__init__(config)
        self.execution_count = 0

    async def execute(self, code_file, characteristics=None, memory_context=None):
        """Mock execution that tracks call count."""
        self.execution_count += 1
        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="passed",
            duration=0.5,
            issues_found=0,
            is_blocker=False,
            findings=[],
        )


class TestRepositoryCacheInitialization:
    """Test cache initialization."""

    def test_cache_initialized_empty(self):
        """Test cache is initialized as empty dict."""
        frame = MockRepositoryFrame()
        orchestrator = PipelineOrchestrator(frames=[frame])

        assert orchestrator._repository_level_cache == {}


class TestCacheMissFirstExecution:
    """Test cache miss on first execution."""

    @pytest.mark.asyncio
    async def test_first_execution_cache_miss(self):
        """Test first execution results in cache miss and execution."""
        repo_frame = MockRepositoryFrame()
        orchestrator = PipelineOrchestrator(frames=[repo_frame])

        code_files = [
            CodeFile(
                path="test.py", content="print('test')", language="python"
            )
        ]

        result = await orchestrator.execute(code_files)

        # Frame should have been executed once
        assert repo_frame.execution_count == 1

        # Result should be cached
        assert repo_frame.name in orchestrator._repository_level_cache


class TestCacheHitSecondExecution:
    """Test cache hit on second execution."""

    @pytest.mark.asyncio
    async def test_second_execution_cache_hit(self):
        """Test second execution uses cache (no re-execution)."""
        repo_frame = MockRepositoryFrame()
        orchestrator = PipelineOrchestrator(frames=[repo_frame])

        code_files = [
            CodeFile(
                path="test.py", content="print('test')", language="python"
            )
        ]

        # First execution - cache miss
        result1 = await orchestrator.execute(code_files)
        assert repo_frame.execution_count == 1

        # Second execution - cache hit
        result2 = await orchestrator.execute(code_files)

        # Frame should NOT have been executed again
        assert repo_frame.execution_count == 1  # Still 1, not 2

        # Both results should be successful
        from warden.pipeline.domain.enums import PipelineStatus
        assert result1.status == PipelineStatus.COMPLETED
        assert result2.status == PipelineStatus.COMPLETED


class TestFileLevelFrameNoCache:
    """Test file-level frames are NOT cached."""

    @pytest.mark.asyncio
    async def test_file_level_frame_always_executes(self):
        """Test file-level frames execute every time (no caching)."""
        file_frame = MockFileFrame()
        orchestrator = PipelineOrchestrator(frames=[file_frame])

        code_files = [
            CodeFile(
                path="test.py", content="print('test')", language="python"
            )
        ]

        # First execution
        await orchestrator.execute(code_files)
        assert file_frame.execution_count == 1

        # Second execution - should execute again (no cache)
        await orchestrator.execute(code_files)
        assert file_frame.execution_count == 2  # Executed twice


class TestMixedFramesCaching:
    """Test mixed repository and file-level frames."""

    @pytest.mark.asyncio
    async def test_mixed_frames_cache_behavior(self):
        """Test repository frames cached, file frames not cached."""
        repo_frame = MockRepositoryFrame()
        file_frame = MockFileFrame()
        orchestrator = PipelineOrchestrator(frames=[repo_frame, file_frame])

        code_files = [
            CodeFile(
                path="test.py", content="print('test')", language="python"
            )
        ]

        # First execution
        await orchestrator.execute(code_files)
        assert repo_frame.execution_count == 1
        assert file_frame.execution_count == 1

        # Second execution
        await orchestrator.execute(code_files)

        # Repository frame: cached (still 1)
        assert repo_frame.execution_count == 1

        # File frame: not cached (executed again = 2)
        assert file_frame.execution_count == 2


class TestCacheKeyIsolation:
    """Test cache key isolation (different frames don't share cache)."""

    @pytest.mark.asyncio
    async def test_different_frames_isolated_cache(self):
        """Test different repository frames have isolated caches."""

        class MockRepoFrame1(MockRepositoryFrame):
            name = "RepoFrame1"

        class MockRepoFrame2(MockRepositoryFrame):
            name = "RepoFrame2"

        frame1 = MockRepoFrame1()
        frame2 = MockRepoFrame2()
        orchestrator = PipelineOrchestrator(frames=[frame1, frame2])

        code_files = [
            CodeFile(
                path="test.py", content="print('test')", language="python"
            )
        ]

        # First execution - both frames execute
        await orchestrator.execute(code_files)
        assert frame1.execution_count == 1
        assert frame2.execution_count == 1

        # Verify both cached separately
        assert "RepoFrame1" in orchestrator._repository_level_cache
        assert "RepoFrame2" in orchestrator._repository_level_cache

        # Second execution - both use cache
        await orchestrator.execute(code_files)
        assert frame1.execution_count == 1  # Still 1 (cached)
        assert frame2.execution_count == 1  # Still 1 (cached)


class TestCacheWithFindings:
    """Test caching behavior when frames have findings."""

    @pytest.mark.asyncio
    async def test_cache_stores_findings(self):
        """Test cache stores and retrieves findings correctly."""

        class FrameWithFindings(ValidationFrame):
            name = "FrameWithFindings"
            description = "Test frame with findings"
            priority = FramePriority.HIGH
            scope = FrameScope.REPOSITORY_LEVEL
            is_blocker = False

            async def execute(self, code_file, characteristics=None, memory_context=None):
                return FrameResult(
                    frame_id=self.frame_id,
                    frame_name=self.name,
                    status="warning",
                    duration=1.0,
                    issues_found=2,
                    is_blocker=False,
                    findings=[
                        Finding(
                            id="1",
                            severity="medium",
                            message="Issue 1",
                            location="test.py:10",
                        ),
                        Finding(
                            id="2",
                            severity="low",
                            message="Issue 2",
                            location="test.py:20",
                        ),
                    ],
                )

        frame = FrameWithFindings()
        orchestrator = PipelineOrchestrator(frames=[frame])

        code_files = [
            CodeFile(
                path="test.py", content="print('test')", language="python"
            )
        ]

        # First execution
        result1 = await orchestrator.execute(code_files)
        assert result1.total_findings == 2

        # Second execution (from cache)
        result2 = await orchestrator.execute(code_files)

        # Findings should be preserved from cache
        assert result2.total_findings == 2


class TestCachePerformance:
    """Test cache performance benefits."""

    @pytest.mark.asyncio
    async def test_cache_reduces_execution_time(self):
        """Test cache reduces overall execution time."""

        class SlowRepositoryFrame(ValidationFrame):
            name = "SlowRepositoryFrame"
            description = "Slow frame to test performance"
            priority = FramePriority.HIGH
            scope = FrameScope.REPOSITORY_LEVEL
            is_blocker = False

            def __init__(self, config=None):
                super().__init__(config)
                self.total_duration = 0.0

            async def execute(self, code_file, characteristics=None, memory_context=None):
                import asyncio

                await asyncio.sleep(0.1)  # Simulate slow execution
                self.total_duration += 0.1

                return FrameResult(
                    frame_id=self.frame_id,
                    frame_name=self.name,
                    status="passed",
                    duration=0.1,
                    issues_found=0,
                    is_blocker=False,
                    findings=[],
                )

        frame = SlowRepositoryFrame()
        orchestrator = PipelineOrchestrator(frames=[frame])

        code_files = [
            CodeFile(
                path="test.py", content="print('test')", language="python"
            )
        ]

        # First execution - slow
        import time

        start = time.time()
        await orchestrator.execute(code_files)
        first_duration = time.time() - start

        # Second execution - fast (cached)
        start = time.time()
        await orchestrator.execute(code_files)
        second_duration = time.time() - start

        # Second execution should be significantly faster
        assert second_duration < first_duration * 0.5  # At least 2x faster


class TestCacheWithMultipleFiles:
    """Test cache behavior with multiple code files."""

    @pytest.mark.asyncio
    async def test_repository_frame_cached_across_files(self):
        """Test repository frame executed once even with multiple files."""
        repo_frame = MockRepositoryFrame()
        orchestrator = PipelineOrchestrator(frames=[repo_frame])

        code_files = [
            CodeFile(
                path="file1.py", content="print('1')", language="python"
            ),
            CodeFile(
                path="file2.py", content="print('2')", language="python"
            ),
            CodeFile(
                path="file3.py", content="print('3')", language="python"
            ),
        ]

        # Execute pipeline
        await orchestrator.execute(code_files)

        # Repository frame should execute once per file = 3 times total
        assert repo_frame.execution_count == 3

        # Second execution with same files
        await orchestrator.execute(code_files)

        # Should still be 3 (cached result reused for all files)
        assert repo_frame.execution_count == 3


class TestCacheLogging:
    """Test cache logging behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit_logged(self):
        """Test cache hit is logged."""
        repo_frame = MockRepositoryFrame()
        orchestrator = PipelineOrchestrator(frames=[repo_frame])

        code_files = [
            CodeFile(
                path="test.py", content="print('test')", language="python"
            )
        ]

        # First execution - prime cache
        await orchestrator.execute(code_files)

        # Second execution - should log cache hit
        with patch("warden.pipeline.application.orchestrator.logger") as mock_logger:
            await orchestrator.execute(code_files)

            # Verify cache hit was logged
            mock_logger.debug.assert_any_call(
                "repository_cache_hit",
                frame_name=repo_frame.name,
                frame_id=repo_frame.frame_id,
                cached_issues=0,
                message="⚡ Using cached result for repository-level frame",
            )
