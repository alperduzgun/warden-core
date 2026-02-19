"""Tests for the shared TaintAnalysisService."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from warden.analysis.taint.service import TaintAnalysisService


def _make_code_file(path: str, content: str, language: str) -> MagicMock:
    cf = MagicMock()
    cf.path = path
    cf.content = content
    cf.language = language
    return cf


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

VULNERABLE_JS = """\
const express = require('express');
const app = express();

app.get('/search', (req, res) => {
    const query = req.query.q;
    db.query("SELECT * FROM items WHERE name = '" + query + "'");
});
"""

RUST_CODE = """\
fn main() {
    println!("Hello, world!");
}
"""


class TestTaintAnalysisService:
    def test_analyze_all_returns_paths_for_vulnerable_files(self, tmp_path: Path):
        service = TaintAnalysisService(project_root=tmp_path)
        code_files = [_make_code_file("app.py", VULNERABLE_PYTHON, "python")]

        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            service.analyze_all_async(code_files)
        )

        assert "app.py" in results
        assert len(results["app.py"]) > 0

    def test_analyze_all_skips_unsupported_languages(self, tmp_path: Path):
        service = TaintAnalysisService(project_root=tmp_path)
        code_files = [_make_code_file("main.rs", RUST_CODE, "rust")]

        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            service.analyze_all_async(code_files)
        )

        assert len(results) == 0

    def test_analyze_all_handles_syntax_errors(self, tmp_path: Path):
        service = TaintAnalysisService(project_root=tmp_path)
        bad_python = "def broken(\n  # unterminated"
        code_files = [_make_code_file("bad.py", bad_python, "python")]

        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            service.analyze_all_async(code_files)
        )

        # Should not crash, returns empty for files with syntax errors
        assert isinstance(results, dict)

    def test_catalog_loaded_once(self, tmp_path: Path):
        """Verify lazy init loads catalog exactly once."""
        service = TaintAnalysisService(project_root=tmp_path)
        assert service._catalog is None
        assert service._analyzer is None

        service._ensure_initialized()
        catalog1 = service._catalog
        analyzer1 = service._analyzer

        # Second call should be no-op
        service._ensure_initialized()
        assert service._catalog is catalog1
        assert service._analyzer is analyzer1

    def test_get_paths_for_unknown_file_returns_empty(self, tmp_path: Path):
        service = TaintAnalysisService(project_root=tmp_path)
        assert service.get_paths_for_file("nonexistent.py") == []

    def test_service_with_custom_config(self, tmp_path: Path):
        custom_config = {"confidence_threshold": 0.5, "sanitizer_penalty": 0.1}
        service = TaintAnalysisService(
            project_root=tmp_path, taint_config=custom_config
        )
        code_files = [_make_code_file("app.py", VULNERABLE_PYTHON, "python")]

        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            service.analyze_all_async(code_files)
        )

        assert isinstance(results, dict)

    def test_service_with_none_config(self, tmp_path: Path):
        service = TaintAnalysisService(project_root=tmp_path, taint_config=None)
        code_files = [_make_code_file("app.py", SAFE_PYTHON, "python")]

        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            service.analyze_all_async(code_files)
        )

        # Safe code should produce no taint paths
        assert len(results) == 0

    def test_service_with_empty_files(self, tmp_path: Path):
        service = TaintAnalysisService(project_root=tmp_path)

        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            service.analyze_all_async([])
        )

        assert results == {}

    def test_analyze_all_handles_javascript(self, tmp_path: Path):
        service = TaintAnalysisService(project_root=tmp_path)
        code_files = [_make_code_file("app.js", VULNERABLE_JS, "javascript")]

        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            service.analyze_all_async(code_files)
        )

        assert "app.js" in results
        assert len(results["app.js"]) > 0

    def test_get_paths_after_analyze(self, tmp_path: Path):
        service = TaintAnalysisService(project_root=tmp_path)
        code_files = [_make_code_file("app.py", VULNERABLE_PYTHON, "python")]

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            service.analyze_all_async(code_files)
        )

        paths = service.get_paths_for_file("app.py")
        assert len(paths) > 0
        assert service.get_paths_for_file("other.py") == []
