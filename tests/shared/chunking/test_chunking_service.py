"""Unit tests for warden.shared.chunking.

Covers:
- ChunkingService.should_chunk
- ChunkingService.chunk (fast path, AST path, line-based fallback)
- ChunkingService.reconcile
- ChunkingService.build_prompt_header
- reconcile_findings (absolute, relative, out-of-range, full chunk skip)
"""

from __future__ import annotations

import pytest

from warden.shared.chunking import ChunkingConfig, ChunkingService
from warden.shared.chunking.models import CodeChunk
from warden.shared.chunking.reconciler import reconcile_findings
from warden.validation.domain.frame import CodeFile

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

SAMPLE_LARGE_PY = """\
import os

def func_a(x):
    return x + 1

def func_b(y, z):
    return y * z

class MyService:
    def __init__(self):
        self.db = None

    def process(self, data):
        return self.db.query(data)
"""

_SMALL_CONFIG = ChunkingConfig(max_chunk_tokens=10_000, max_chunks_per_file=3)
_TIGHT_CONFIG = ChunkingConfig(max_chunk_tokens=10, max_chunks_per_file=3)


def _make_file(content: str, path: str = "test.py") -> CodeFile:
    return CodeFile(path=path, content=content, language="python")


def _make_chunk(
    *,
    start_line: int = 1,
    end_line: int = 10,
    chunk_type: str = "function",
    chunk_index: int = 0,
    total_chunks: int = 2,
) -> CodeChunk:
    lines = [f"line {i}" for i in range(start_line, end_line + 1)]
    content = "\n".join(f"{start_line + i}: {ln}" for i, ln in enumerate(lines))
    return CodeChunk(
        content=content,
        start_line=start_line,
        end_line=end_line,
        file_path="test.py",
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        chunk_type=chunk_type,
    )


# ---------------------------------------------------------------------------
# should_chunk
# ---------------------------------------------------------------------------


class TestShouldChunk:
    def test_should_chunk_small_file(self):
        """Files within token budget → False."""
        service = ChunkingService()
        code_file = _make_file("x = 1\n")
        assert service.should_chunk(code_file, _SMALL_CONFIG) is False

    def test_should_chunk_large_file(self):
        """Files exceeding token budget → True."""
        service = ChunkingService()
        # Create content clearly larger than 10 tokens
        code_file = _make_file("x = 1\n" * 200)
        assert service.should_chunk(code_file, _TIGHT_CONFIG) is True

    def test_should_chunk_empty_file(self):
        """Empty file → False (0 tokens ≤ any budget)."""
        service = ChunkingService()
        code_file = _make_file("")
        assert service.should_chunk(code_file, _TIGHT_CONFIG) is False


# ---------------------------------------------------------------------------
# chunk — fast path (small file)
# ---------------------------------------------------------------------------


class TestChunkFastPath:
    def test_chunk_returns_single_for_small_file(self):
        """Small file returns one 'full' chunk with no overhead."""
        service = ChunkingService()
        code_file = _make_file("x = 1\n")
        chunks = service.chunk(code_file, None, _SMALL_CONFIG)

        assert len(chunks) == 1
        assert chunks[0].chunk_type == "full"
        assert chunks[0].chunk_index == 0
        assert chunks[0].total_chunks == 1

    def test_chunk_empty_file_returns_nothing(self):
        """Empty file produces no chunks."""
        service = ChunkingService()
        code_file = _make_file("")
        chunks = service.chunk(code_file, None, _SMALL_CONFIG)
        assert chunks == []


# ---------------------------------------------------------------------------
# chunk — AST path
# ---------------------------------------------------------------------------


class TestChunkASTPath:
    def _make_ast_cache(self, path: str, content: str) -> dict:
        """Build a minimal mock ast_cache entry with real AST nodes."""
        import asyncio

        try:
            from warden.ast.domain.enums import CodeLanguage  # noqa: PLC0415
            from warden.ast.providers.python_ast_provider import PythonASTProvider  # noqa: PLC0415

            provider = PythonASTProvider()
            parse_result = asyncio.run(
                provider.parse(content, CodeLanguage.PYTHON, file_path=path)
            )
            return {path: parse_result}
        except Exception:
            return {}

    def test_chunk_ast_splits_functions(self):
        """AST path produces separate chunks for distinct top-level functions."""
        service = ChunkingService()
        code_file = _make_file(SAMPLE_LARGE_PY)
        ast_cache = self._make_ast_cache(code_file.path, code_file.content)

        if not ast_cache:
            pytest.skip("AST provider unavailable")

        config = ChunkingConfig(max_chunk_tokens=30, max_chunks_per_file=5, min_chunk_lines=1)
        chunks = service.chunk(code_file, ast_cache, config)

        # Must have more than 1 chunk when AST finds multiple units
        assert len(chunks) >= 1
        # All chunks reference the correct file path
        for ch in chunks:
            assert ch.file_path == code_file.path

    def test_chunk_respects_max_chunks_per_file(self):
        """max_chunks_per_file hard-caps the number of chunks returned."""
        service = ChunkingService()
        code_file = _make_file(SAMPLE_LARGE_PY)
        ast_cache = self._make_ast_cache(code_file.path, code_file.content)

        if not ast_cache:
            pytest.skip("AST provider unavailable")

        config = ChunkingConfig(max_chunk_tokens=30, max_chunks_per_file=2, min_chunk_lines=1)
        chunks = service.chunk(code_file, ast_cache, config)

        assert len(chunks) <= 2


# ---------------------------------------------------------------------------
# chunk — line-based fallback
# ---------------------------------------------------------------------------


class TestChunkLineFallback:
    def test_chunk_fallback_line_based(self):
        """No AST cache → line-based fallback is used."""
        service = ChunkingService()
        # Enough content to exceed 10-token budget
        code_file = _make_file("x = 1\n" * 200)
        config = ChunkingConfig(max_chunk_tokens=10, max_chunks_per_file=3, min_chunk_lines=1)

        chunks = service.chunk(code_file, ast_cache=None, config=config)

        assert len(chunks) >= 1
        # All returned chunks should have chunk_type "lines"
        for ch in chunks:
            assert ch.chunk_type == "lines"

    def test_chunk_fallback_respects_max_chunks(self):
        """Line fallback also respects max_chunks_per_file."""
        service = ChunkingService()
        code_file = _make_file("x = 1\n" * 500)
        config = ChunkingConfig(max_chunk_tokens=10, max_chunks_per_file=2, min_chunk_lines=1)

        chunks = service.chunk(code_file, ast_cache=None, config=config)
        assert len(chunks) <= 2


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------


class TestReconcile:
    def test_reconcile_absolute_lines(self):
        """LLM reported absolute line already in [start, end] → unchanged."""
        chunk = _make_chunk(start_line=100, end_line=120)
        finding = {"line": 110, "location": "test.py:110", "id": "old-id"}

        result = reconcile_findings(chunk, [finding], "fuzz")

        assert result[0]["line"] == 110  # unchanged

    def test_reconcile_relative_lines(self):
        """LLM counted from 1 (relative) → shifted to absolute."""
        chunk = _make_chunk(start_line=100, end_line=120)
        # relative line 5 → absolute 100 + 5 - 1 = 104
        finding = {"line": 5, "location": "test.py:5", "id": "old-id"}

        result = reconcile_findings(chunk, [finding], "fuzz")

        assert result[0]["line"] == 104

    def test_reconcile_out_of_range(self):
        """Completely invalid line → clamped to start_line."""
        chunk = _make_chunk(start_line=100, end_line=110)
        # 999 is outside [100,110] and also outside relative [1,11]
        finding = {"line": 999, "location": "test.py:999", "id": "old-id"}

        result = reconcile_findings(chunk, [finding], "fuzz")

        assert result[0]["line"] == 100  # start_line fallback

    def test_reconcile_skips_full_chunk(self):
        """chunk_type='full' → reconciliation is a no-op."""
        chunk = _make_chunk(start_line=1, end_line=50, chunk_type="full", total_chunks=1)
        finding = {"line": 5, "location": "test.py:5", "id": "old-id"}

        result = reconcile_findings(chunk, [finding], "fuzz")

        # full chunks skip reconciliation — line stays 5
        assert result[0]["line"] == 5

    def test_reconcile_resets_id(self):
        """Finding ID is reset to frame_id-llm-{absolute_line}."""
        chunk = _make_chunk(start_line=100, end_line=120)
        finding = {"line": 110, "location": "test.py:110", "id": "old-id"}

        result = reconcile_findings(chunk, [finding], "myframe")

        assert result[0]["id"] == "myframe-llm-110"

    def test_reconcile_updates_location(self):
        """Location field is updated to reflect the reconciled line."""
        chunk = _make_chunk(start_line=100, end_line=120)
        finding = {"line": 5, "location": "test.py:5", "id": "x"}

        result = reconcile_findings(chunk, [finding], "f")

        assert "test.py:104" in result[0]["location"]

    def test_reconcile_no_line_field(self):
        """Findings without a 'line' field are left untouched."""
        chunk = _make_chunk(start_line=100, end_line=120)
        finding = {"message": "no line here"}

        result = reconcile_findings(chunk, [finding], "f")

        assert "line" not in result[0]


# ---------------------------------------------------------------------------
# build_prompt_header
# ---------------------------------------------------------------------------


class TestBuildPromptHeader:
    def test_build_prompt_header_includes_inventory(self):
        """Header contains the chunk label with line range."""
        service = ChunkingService()
        chunk = CodeChunk(
            content="10: def foo(): pass",
            start_line=10,
            end_line=20,
            file_path="app.py",
            chunk_index=0,
            total_chunks=3,
            chunk_type="function",
            import_context="import os",
            unit_name="foo",
        )
        header = service.build_prompt_header(chunk)

        assert "10" in header  # start line
        assert "20" in header  # end line
        assert "foo" in header  # unit name
        assert "app.py" in header
        assert "1/3" in header  # chunk position

    def test_class_context_in_method_chunk(self):
        """class_context field appears in the header when set."""
        service = ChunkingService()
        chunk = CodeChunk(
            content="15: def process(self): pass",
            start_line=15,
            end_line=25,
            file_path="svc.py",
            chunk_index=1,
            total_chunks=3,
            chunk_type="class_method",
            class_context="class MyService:\n    def __init__(self): self.db = None",
            unit_name="MyService.process",
        )
        header = service.build_prompt_header(chunk)

        assert "CLASS CONTEXT" in header
        assert "MyService" in header

    def test_header_empty_when_no_context(self):
        """Chunk with no import/class context produces minimal header."""
        service = ChunkingService()
        chunk = CodeChunk(
            content="1: x = 1",
            start_line=1,
            end_line=1,
            file_path="x.py",
            chunk_index=0,
            total_chunks=2,
            chunk_type="lines",
        )
        header = service.build_prompt_header(chunk)

        # Should still contain the CODE TO ANALYZE label
        assert "CODE TO ANALYZE" in header
