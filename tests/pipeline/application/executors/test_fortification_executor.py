"""
Tests for fortification executor — findings_map linking and dict compatibility.

Covers:
1. findings_map built from validated_issues (not context.findings)
2. Remediation assigned as dict (not dataclass) to finding dicts
3. Unlinked fortifications tracked in phase metrics
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.pipeline.application.executors.fortification_executor import (
    FortificationExecutor,
)
from warden.pipeline.domain.models import PipelineConfig
from warden.pipeline.domain.pipeline_context import PipelineContext


def _make_context(**overrides):
    """Create a minimal PipelineContext for testing."""
    from datetime import datetime

    defaults = {
        "pipeline_id": "test-pipeline",
        "started_at": datetime.now(),
        "file_path": Path("/tmp/test.py"),
        "source_code": "print('hello')",
        "project_root": Path("/tmp"),
    }
    defaults.update(overrides)
    return PipelineContext(**defaults)


def _make_executor(**kwargs):
    config = kwargs.pop("config", PipelineConfig(enable_fortification=True))
    return FortificationExecutor(config=config, **kwargs)


def _make_fortification_result(fortifications):
    """Create a mock FortificationPhase result."""
    result = MagicMock()
    result.fortifications = fortifications
    result.applied_fixes = []
    result.security_improvements = []
    return result


def _get_phase_result(ctx):
    """Get FORTIFICATION phase result from context metadata."""
    return ctx.metadata.get("phase_fortification_result", {})


class TestFindingsMapSource:
    """findings_map must be built from validated_issues local var, not context.findings."""

    @pytest.mark.asyncio
    async def test_linking_uses_validated_issues_not_context_findings(self):
        """Fortification links to normalized validated_issues — not diverged context.findings."""
        ctx = _make_context()
        # context.findings diverged (different IDs from validated_issues)
        ctx.findings = [{"id": "OLD-1", "severity": "high", "message": "old"}]
        ctx.validated_issues = [
            {"id": "NEW-1", "severity": "high", "message": "sql injection", "file_path": "app.py"},
        ]

        fort_result = _make_fortification_result([
            {
                "finding_id": "NEW-1",
                "title": "Fix SQL injection",
                "suggested_code": "safe_query()",
                "original_code": "raw_query()",
            }
        ])

        executor = _make_executor(llm_service=MagicMock())

        with patch(
            "warden.fortification.application.fortification_phase.FortificationPhase"
        ) as MockPhase:
            mock_phase = AsyncMock()
            mock_phase.execute_async.return_value = fort_result
            MockPhase.return_value = mock_phase

            await executor.execute_async(ctx, [])

        # Phase result should show 1 linked, 0 unlinked
        phase_result = _get_phase_result(ctx)
        assert phase_result["fortifications_linked"] == 1
        assert phase_result["fortifications_unlinked"] == 0
        assert phase_result["link_success_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_unlinked_when_id_not_in_validated_issues(self):
        """Fortification with unknown finding_id is tracked as unlinked."""
        ctx = _make_context()
        ctx.validated_issues = [
            {"id": "F1", "severity": "high", "message": "xss", "file_path": "app.py"},
        ]

        fort_result = _make_fortification_result([
            {
                "finding_id": "NONEXISTENT",
                "title": "Fix something",
                "suggested_code": "fix()",
                "original_code": "broken()",
            }
        ])

        executor = _make_executor(llm_service=MagicMock())

        with patch(
            "warden.fortification.application.fortification_phase.FortificationPhase"
        ) as MockPhase:
            mock_phase = AsyncMock()
            mock_phase.execute_async.return_value = fort_result
            MockPhase.return_value = mock_phase

            await executor.execute_async(ctx, [])

        phase_result = _get_phase_result(ctx)
        assert phase_result["fortifications_linked"] == 0
        assert phase_result["fortifications_unlinked"] == 1

    @pytest.mark.asyncio
    async def test_mixed_linked_and_unlinked(self):
        """Some fortifications link, others don't — metrics correct."""
        ctx = _make_context()
        ctx.validated_issues = [
            {"id": "F1", "severity": "high", "message": "xss", "file_path": "app.py"},
            {"id": "F2", "severity": "medium", "message": "info", "file_path": "app.py"},
        ]

        fort_result = _make_fortification_result([
            {"finding_id": "F1", "title": "Fix 1", "suggested_code": "s()", "original_code": "b()"},
            {"finding_id": "GHOST", "title": "Fix 2", "suggested_code": "s()", "original_code": "b()"},
        ])

        executor = _make_executor(llm_service=MagicMock())

        with patch(
            "warden.fortification.application.fortification_phase.FortificationPhase"
        ) as MockPhase:
            mock_phase = AsyncMock()
            mock_phase.execute_async.return_value = fort_result
            MockPhase.return_value = mock_phase

            await executor.execute_async(ctx, [])

        phase_result = _get_phase_result(ctx)
        assert phase_result["fortifications_linked"] == 1
        assert phase_result["fortifications_unlinked"] == 1
        assert phase_result["link_success_rate"] == 0.5


class TestRemediationDictAssignment:
    """Remediation assigned as plain dict (no AttributeError on dict findings)."""

    @pytest.mark.asyncio
    async def test_no_attribute_error_on_dict_findings(self):
        """Remediation dict assignment to dict finding should not raise AttributeError."""
        ctx = _make_context()
        ctx.validated_issues = [
            {"id": "F1", "severity": "high", "message": "eval usage", "file_path": "app.py"},
        ]

        fort_result = _make_fortification_result([
            {
                "finding_id": "F1",
                "title": "Remove eval",
                "suggested_code": "ast.literal_eval(x)",
                "original_code": "eval(x)",
            }
        ])

        executor = _make_executor(llm_service=MagicMock())

        with patch(
            "warden.fortification.application.fortification_phase.FortificationPhase"
        ) as MockPhase:
            mock_phase = AsyncMock()
            mock_phase.execute_async.return_value = fort_result
            MockPhase.return_value = mock_phase

            # Should not raise AttributeError
            await executor.execute_async(ctx, [])

        # Phase completed successfully with linking
        phase_result = _get_phase_result(ctx)
        assert phase_result["fortifications_linked"] == 1
        assert ctx.fortifications == fort_result.fortifications

    @pytest.mark.asyncio
    async def test_diff_generated_when_both_codes_present(self):
        """Unified diff generated when both original_code and suggested_code exist."""
        ctx = _make_context()
        ctx.validated_issues = [
            {"id": "F1", "severity": "high", "message": "issue", "file_path": "app.py"},
        ]

        fort_result = _make_fortification_result([
            {
                "finding_id": "F1",
                "title": "Fix it",
                "suggested_code": "safe(x)",
                "original_code": "unsafe(x)",
            }
        ])

        executor = _make_executor(llm_service=MagicMock())

        with patch(
            "warden.fortification.application.fortification_phase.FortificationPhase"
        ) as MockPhase:
            mock_phase = AsyncMock()
            mock_phase.execute_async.return_value = fort_result
            MockPhase.return_value = mock_phase

            await executor.execute_async(ctx, [])

        # Phase succeeded and linked
        phase_result = _get_phase_result(ctx)
        assert phase_result["fortifications_linked"] == 1


class TestFallbackToFindings:
    """When validated_issues is empty, falls back to context.findings."""

    @pytest.mark.asyncio
    async def test_fallback_to_findings_when_validated_empty(self):
        """Uses context.findings when validated_issues is empty."""
        ctx = _make_context()
        ctx.validated_issues = []
        ctx.findings = [
            MagicMock(
                id="F1", severity="high", message="test",
                file_path="app.py", location="app.py:1",
                type="security", code_snippet="x()",
            )
        ]

        fort_result = _make_fortification_result([
            {"finding_id": "F1", "title": "Fix", "suggested_code": "y()", "original_code": "x()"}
        ])

        executor = _make_executor(llm_service=MagicMock())

        with patch(
            "warden.fortification.application.fortification_phase.FortificationPhase"
        ) as MockPhase:
            mock_phase = AsyncMock()
            mock_phase.execute_async.return_value = fort_result
            MockPhase.return_value = mock_phase

            await executor.execute_async(ctx, [])

        phase_result = _get_phase_result(ctx)
        assert phase_result["fortifications_total"] == 1
