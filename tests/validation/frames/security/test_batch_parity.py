"""
Tests for batch mode execution parity with single mode.

Verifies:
1. Batch mode produces similar results to single mode (includes AST/taint)
2. Batch mode handles errors gracefully when some files fail
3. Batch mode runs AST extraction and data flow analysis (not just pattern checks)
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
        """Batch execution runs the same analysis pipeline as single mode."""
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

        # Finding counts should match between single and batch
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

    @pytest.mark.asyncio
    async def test_batch_mode_calls_ast_extraction(self, security_frame):
        """Batch mode invokes extract_ast_context for each file."""
        code_files = [
            CodeFile(path="/tmp/a.py", content="x = eval(input())", language="python"),
            CodeFile(path="/tmp/b.py", content="y = 1 + 2", language="python"),
        ]

        with patch(
            "warden.validation.frames.security.frame.extract_ast_context",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_ast:
            await security_frame.execute_batch_async(code_files)

        # AST extraction should be called once per file
        assert mock_ast.call_count == len(code_files)
        called_paths = [call.args[0].path for call in mock_ast.call_args_list]
        assert "/tmp/a.py" in called_paths
        assert "/tmp/b.py" in called_paths

    @pytest.mark.asyncio
    async def test_batch_mode_calls_data_flow_analysis(self, security_frame):
        """Batch mode invokes analyze_data_flow when check results exist."""
        from warden.validation.domain.check import CheckFinding, CheckResult, CheckSeverity

        code_files = [
            CodeFile(
                path="/tmp/vuln.py",
                content='query = f"SELECT * FROM users WHERE id = {uid}"',
                language="python",
            ),
        ]

        # Register a mock check that produces a finding so check_results is non-empty
        mock_check = MagicMock()
        mock_check.name = "mock-check"
        mock_check.execute_async = AsyncMock(return_value=CheckResult(
            check_id="mock",
            check_name="Mock Check",
            passed=False,
            findings=[
                CheckFinding(
                    check_id="mock",
                    check_name="Mock Check",
                    severity=CheckSeverity.HIGH,
                    message="test finding",
                    location="/tmp/vuln.py:1",
                    suggestion="fix it",
                ),
            ],
        ))
        security_frame.checks.register(mock_check)

        with patch(
            "warden.validation.frames.security.frame.analyze_data_flow",
            new_callable=AsyncMock,
            return_value={"tainted_paths": [], "blast_radius": [], "data_sources": []},
        ) as mock_df:
            await security_frame.execute_batch_async(code_files)

        # Data flow analysis should be called for the file with findings
        assert mock_df.call_count == 1
        assert mock_df.call_args.args[0].path == "/tmp/vuln.py"

    @pytest.mark.asyncio
    async def test_batch_mode_metadata_includes_ast_analysis(self, security_frame):
        """Batch results contain ast_analysis in metadata when AST data is available."""
        code_files = [
            CodeFile(path="/tmp/test.py", content="exec(user_input)", language="python"),
        ]

        fake_ast = {
            "dangerous_calls": [{"name": "exec", "line": 1}],
            "sql_queries": [],
            "input_sources": [{"name": "user_input", "line": 1}],
            "string_concatenations": [],
        }

        with patch(
            "warden.validation.frames.security.frame.extract_ast_context",
            new_callable=AsyncMock,
            return_value=fake_ast,
        ):
            results = await security_frame.execute_batch_async(code_files)

        metadata = results[0].metadata
        assert "ast_analysis" in metadata
        assert metadata["ast_analysis"]["dangerous_calls_found"] == 1
        assert metadata["ast_analysis"]["input_sources_found"] == 1

    @pytest.mark.asyncio
    async def test_batch_mode_metadata_includes_data_flow(self, security_frame):
        """Batch results contain data_flow_analysis in metadata when data flow is available."""
        from warden.validation.domain.check import CheckFinding, CheckResult, CheckSeverity

        code_files = [
            CodeFile(path="/tmp/test.py", content="x = 1", language="python"),
        ]

        # Need a check that produces findings to trigger data flow analysis
        mock_check = MagicMock()
        mock_check.name = "mock"
        mock_check.execute_async = AsyncMock(return_value=CheckResult(
            check_id="mock",
            check_name="Mock",
            passed=False,
            findings=[
                CheckFinding(
                    check_id="mock",
                    check_name="Mock",
                    severity=CheckSeverity.MEDIUM,
                    message="test",
                    location="/tmp/test.py:1",
                    suggestion="fix",
                ),
            ],
        ))
        security_frame.checks.register(mock_check)

        fake_data_flow = {
            "tainted_paths": ["/tmp/test.py:1 -> /tmp/test.py:5"],
            "blast_radius": ["/tmp/other.py"],
            "data_sources": ["/tmp/test.py:1"],
        }

        with patch(
            "warden.validation.frames.security.frame.analyze_data_flow",
            new_callable=AsyncMock,
            return_value=fake_data_flow,
        ):
            results = await security_frame.execute_batch_async(code_files)

        metadata = results[0].metadata
        assert "data_flow_analysis" in metadata
        assert metadata["data_flow_analysis"]["tainted_paths_found"] == 1
        assert metadata["data_flow_analysis"]["blast_radius_files"] == 1
        assert metadata["data_flow_analysis"]["data_sources_traced"] == 1
        assert metadata["tainted_paths"] == fake_data_flow["tainted_paths"]

    @pytest.mark.asyncio
    async def test_batch_and_single_mode_metadata_parity(self, security_frame):
        """Both modes populate the same metadata keys for analysis results."""
        code_files = [
            CodeFile(path="/tmp/app.py", content="x = 1", language="python"),
        ]

        fake_ast = {
            "dangerous_calls": [],
            "sql_queries": [],
            "input_sources": [],
            "string_concatenations": [],
        }

        with patch(
            "warden.validation.frames.security.frame.extract_ast_context",
            new_callable=AsyncMock,
            return_value=fake_ast,
        ):
            single_result = await security_frame.execute_async(code_files[0])
            batch_results = await security_frame.execute_batch_async(code_files)

        # Core metadata keys should be present in both
        for key in ("checks_executed", "checks_passed", "checks_failed"):
            assert key in single_result.metadata, f"Single mode missing key: {key}"
            assert key in batch_results[0].metadata, f"Batch mode missing key: {key}"
