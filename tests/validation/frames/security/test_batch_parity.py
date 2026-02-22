"""
Tests for batch mode execution parity with single mode.

Verifies:
1. Batch mode produces similar results to single mode (includes AST/taint)
2. Batch mode handles errors gracefully when some files fail
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.validation.domain.frame import CodeFile, FrameResult


@pytest.fixture
def security_frame():
    """Create a SecurityFrame with mocked internal check imports."""
    from warden.validation.frames.security.frame import SecurityFrame

    with patch.object(SecurityFrame, "_register_builtin_checks"), \
         patch.object(SecurityFrame, "_discover_community_checks"):
        frame = SecurityFrame()
    return frame


class TestSecurityFrameBatchParity:
    """Test that batch mode produces similar results to single mode."""

    @pytest.mark.asyncio
    async def test_batch_mode_produces_findings_like_single_mode(self, security_frame):
        """Batch execution delegates to execute_async per file, so results match."""
        code_files = [
            CodeFile(
                path="/tmp/app.py",
                content='query = f"SELECT * FROM users WHERE id = {user_id}"',
                language="python",
            ),
            CodeFile(
                path="/tmp/admin.py",
                content='query = "DELETE FROM users WHERE id = " + user_id',
                language="python",
            ),
        ]

        # Execute single mode on each file
        single_results = []
        for code_file in code_files:
            result = await security_frame.execute_async(code_file)
            single_results.append(result)

        # Execute batch mode
        batch_results = await security_frame.execute_batch_async(code_files)

        # Both should return same count
        assert len(batch_results) == len(code_files)

        # Batch delegates to execute_async, so finding counts should match
        for i in range(len(code_files)):
            assert batch_results[i].issues_found == single_results[i].issues_found

    @pytest.mark.asyncio
    async def test_batch_mode_handles_errors_gracefully(self, security_frame):
        """Batch mode returns error result for files that throw exceptions."""
        code_files = [
            CodeFile(path="/tmp/good.py", content="x = 1", language="python"),
            CodeFile(path="/tmp/bad.py", content="y = 2", language="python"),
        ]

        # Mock checks.get_enabled to raise for second file
        original_get_enabled = security_frame.checks.get_enabled
        call_count = 0

        def mock_get_enabled(config):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ValueError("Simulated execution error")
            return original_get_enabled(config)

        with patch.object(security_frame.checks, "get_enabled", side_effect=mock_get_enabled):
            batch_results = await security_frame.execute_batch_async(code_files)

        # Should return results for both
        assert len(batch_results) == 2

        # Second result should have error status
        assert batch_results[1].status == "error"
        assert batch_results[1].issues_found == 0

    @pytest.mark.asyncio
    async def test_batch_mode_handles_empty_list(self, security_frame):
        """Batch mode returns empty list for empty input."""
        batch_results = await security_frame.execute_batch_async([])
        assert batch_results == []

    @pytest.mark.asyncio
    async def test_batch_returns_frame_results(self, security_frame):
        """Each batch result is a proper FrameResult."""
        code_files = [
            CodeFile(path="/tmp/test.py", content="x = 1", language="python"),
        ]

        batch_results = await security_frame.execute_batch_async(code_files)

        assert len(batch_results) == 1
        assert isinstance(batch_results[0], FrameResult)
        assert batch_results[0].frame_id == security_frame.frame_id
