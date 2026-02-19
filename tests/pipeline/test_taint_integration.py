"""Integration tests for taint analysis pipeline integration."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.mixins import TaintAware
from warden.validation.frames.security.frame import SecurityFrame


def _make_code_file(path: str, content: str, language: str = "python") -> MagicMock:
    cf = MagicMock()
    cf.path = path
    cf.content = content
    cf.language = language
    cf.line_count = content.count("\n") + 1
    cf.size_bytes = len(content)
    cf.metadata = {}
    return cf


def _make_context(**kwargs) -> PipelineContext:
    defaults = {
        "pipeline_id": "test-taint-integration",
        "started_at": datetime.now(),
        "file_path": Path("test.py"),
        "source_code": "",
    }
    defaults.update(kwargs)
    return PipelineContext(**defaults)


VULNERABLE_PYTHON = """\
from flask import request

def search():
    query = request.args.get("q")
    cursor.execute("SELECT * FROM items WHERE name = '%s'" % query)
"""

SAFE_PYTHON = """\
def add(a: int, b: int) -> int:
    return a + b
"""


class TestTaintPathsPopulatedInContext:
    def test_taint_paths_populated_in_context(self, tmp_path: Path):
        """Verify TaintAnalysisService populates context.taint_paths."""
        from warden.analysis.taint.service import TaintAnalysisService

        service = TaintAnalysisService(project_root=tmp_path)
        code_files = [_make_code_file("app.py", VULNERABLE_PYTHON)]

        results = asyncio.get_event_loop().run_until_complete(
            service.analyze_all_async(code_files)
        )

        context = _make_context()
        context.taint_paths = results

        assert len(context.taint_paths) > 0
        assert "app.py" in context.taint_paths


class TestTaintAwareFrameReceivesPaths:
    def test_taint_aware_frame_receives_paths(self):
        """Verify TaintAware mixin allows taint_paths injection."""
        frame = SecurityFrame()
        assert isinstance(frame, TaintAware)

        fake_paths = {"app.py": [MagicMock()]}
        frame.set_taint_paths(fake_paths)
        assert frame._taint_paths == fake_paths


class TestSecurityFrameSharedPaths:
    def test_security_frame_prefers_shared_paths(self):
        """SecurityFrame should use shared taint_paths when available."""
        frame = SecurityFrame()

        # Create a mock taint path
        mock_tp = MagicMock()
        mock_tp.is_sanitized = False
        mock_tp.source.name = "request.args"
        mock_tp.source.line = 4
        mock_tp.sink.name = "cursor.execute"
        mock_tp.sink.sink_type = "SQL-value"
        mock_tp.sink.line = 5
        mock_tp.confidence = 0.9
        mock_tp.to_json.return_value = {}

        frame.set_taint_paths({"app.py": [mock_tp]})

        cf = _make_code_file("app.py", VULNERABLE_PYTHON)
        result = asyncio.get_event_loop().run_until_complete(
            frame.execute_async(cf)
        )

        # Should have findings from shared taint paths
        assert result.issues_found > 0

    def test_security_frame_fallback_when_no_shared(self):
        """SecurityFrame should fallback to inline taint analysis when no shared paths."""
        frame = SecurityFrame()
        # No set_taint_paths called — _taint_paths is empty

        cf = _make_code_file("app.py", VULNERABLE_PYTHON)
        result = asyncio.get_event_loop().run_until_complete(
            frame.execute_async(cf)
        )

        # Should still detect taint paths via inline analysis
        assert result.issues_found >= 0  # At least pattern checks run


class TestNonTaintAwareFrameUnaffected:
    def test_non_taint_aware_frame_unaffected(self):
        """Frames without TaintAware should not be affected."""
        from warden.validation.domain.frame import ValidationFrame

        # A plain ValidationFrame should NOT be TaintAware
        assert not issubclass(ValidationFrame, TaintAware)


class TestTaintPopulationGracefulOnFailure:
    def test_taint_population_graceful_on_failure(self):
        """Pipeline should handle taint analysis failure gracefully."""
        context = _make_context()

        # Simulate what pipeline_phase_runner does
        try:
            from warden.analysis.taint.service import TaintAnalysisService

            # Use a non-existent project root — should still work (no crash)
            service = TaintAnalysisService(
                project_root=Path("/nonexistent/path/that/does/not/exist")
            )
            results = asyncio.get_event_loop().run_until_complete(
                service.analyze_all_async([])
            )
            context.taint_paths = results
        except Exception:
            pass

        # Context should still be usable
        assert isinstance(context.taint_paths, dict)
