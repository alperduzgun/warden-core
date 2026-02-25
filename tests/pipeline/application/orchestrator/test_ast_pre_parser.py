"""Tests for ASTPreParser centralized cache."""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.ast.domain.enums import ASTNodeType, CodeLanguage, ParseStatus
from warden.ast.domain.models import ASTNode, ParseResult
from warden.pipeline.application.orchestrator.ast_pre_parser import (
    _MAX_AST_CACHE_ENTRIES,
    ASTPreParser,
)
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import CodeFile


def _make_context():
    """Create a minimal PipelineContext for testing."""
    return PipelineContext(
        pipeline_id="test-001",
        started_at=datetime.now(),
        file_path=Path("/tmp/test"),
        source_code="",
    )


def _make_code_file(path="test.py", language="python", content="x = 1"):
    return CodeFile(path=path, content=content, language=language)


def _make_parse_result(language=CodeLanguage.PYTHON, file_path="test.py"):
    return ParseResult(
        status=ParseStatus.SUCCESS,
        language=language,
        provider_name="MockProvider",
        ast_root=ASTNode(node_type=ASTNodeType.MODULE, name=file_path),
        file_path=file_path,
    )


@pytest.fixture
def mock_registry():
    """Create a mock ASTProviderRegistry with a working provider."""
    registry = MagicMock()
    provider = AsyncMock()
    provider.parse = AsyncMock(side_effect=lambda code, lang, path=None: _make_parse_result(lang, path))
    provider.supports_language = MagicMock(return_value=True)
    registry.get_provider.return_value = provider
    registry.discover_providers = AsyncMock()
    return registry


class TestASTPreParserPopulatesCache:
    @pytest.mark.asyncio
    async def test_pre_parse_populates_ast_cache(self, mock_registry):
        """Pre-parsing stores ParseResult in context.ast_cache keyed by file path."""
        context = _make_context()
        files = [_make_code_file("a.py"), _make_code_file("b.py")]

        parser = ASTPreParser()
        with patch.object(parser, "_get_registry", new_callable=AsyncMock, return_value=mock_registry):
            await parser.pre_parse_all_async(context, files)

        assert "a.py" in context.ast_cache
        assert "b.py" in context.ast_cache
        assert context.ast_cache["a.py"].status == ParseStatus.SUCCESS
        assert context.ast_cache["b.py"].ast_root is not None

    @pytest.mark.asyncio
    async def test_pre_parse_skips_cached_files(self, mock_registry):
        """Already-cached files are not re-parsed (idempotent)."""
        context = _make_context()
        context.ast_cache["a.py"] = _make_parse_result(file_path="a.py")
        files = [_make_code_file("a.py"), _make_code_file("b.py")]

        parser = ASTPreParser()
        with patch.object(parser, "_get_registry", new_callable=AsyncMock, return_value=mock_registry):
            await parser.pre_parse_all_async(context, files)

        # a.py should NOT be overwritten (still the original)
        assert context.ast_cache["a.py"].provider_name == "MockProvider"
        # b.py should be newly parsed
        assert "b.py" in context.ast_cache
        # Provider should only be called once (for b.py)
        assert mock_registry.get_provider.call_count == 1


class TestASTPreParserHandlesErrors:
    @pytest.mark.asyncio
    async def test_pre_parse_handles_timeout(self, mock_registry):
        """Timeout on a file doesn't crash; other files still get parsed."""
        context = _make_context()
        files = [_make_code_file("slow.py"), _make_code_file("fast.py")]

        provider = mock_registry.get_provider.return_value

        async def slow_then_fast(code, lang, path=None):
            if path == "slow.py":
                await asyncio.sleep(100)  # Will be timed out
            return _make_parse_result(lang, path)

        provider.parse = AsyncMock(side_effect=slow_then_fast)

        parser = ASTPreParser(timeout=0.01)  # Very short timeout
        with patch.object(parser, "_get_registry", new_callable=AsyncMock, return_value=mock_registry):
            await parser.pre_parse_all_async(context, files)

        # slow.py should fail (timeout), fast.py should succeed
        assert "slow.py" not in context.ast_cache
        assert "fast.py" in context.ast_cache

    @pytest.mark.asyncio
    async def test_pre_parse_handles_parse_error(self, mock_registry):
        """Parse exceptions don't crash; file is skipped."""
        context = _make_context()
        files = [_make_code_file("bad.py"), _make_code_file("good.py")]

        provider = mock_registry.get_provider.return_value

        async def error_then_ok(code, lang, path=None):
            if path == "bad.py":
                raise RuntimeError("Parse explosion")
            return _make_parse_result(lang, path)

        provider.parse = AsyncMock(side_effect=error_then_ok)

        parser = ASTPreParser()
        with patch.object(parser, "_get_registry", new_callable=AsyncMock, return_value=mock_registry):
            await parser.pre_parse_all_async(context, files)

        assert "bad.py" not in context.ast_cache
        assert "good.py" in context.ast_cache


class TestASTPreParserLanguageHandling:
    @pytest.mark.asyncio
    async def test_pre_parse_handles_unsupported_language(self, mock_registry):
        """Files with unsupported language enum are skipped."""
        context = _make_context()
        # "brainfuck" won't map to CodeLanguage
        files = [_make_code_file("a.bf", language="brainfuck"), _make_code_file("b.py")]

        parser = ASTPreParser()
        with patch.object(parser, "_get_registry", new_callable=AsyncMock, return_value=mock_registry):
            await parser.pre_parse_all_async(context, files)

        assert "a.bf" not in context.ast_cache
        assert "b.py" in context.ast_cache

    @pytest.mark.asyncio
    async def test_pre_parse_handles_no_provider(self, mock_registry):
        """Languages with no provider registered are skipped."""
        context = _make_context()
        files = [_make_code_file("a.py")]

        mock_registry.get_provider.return_value = None

        parser = ASTPreParser()
        with patch.object(parser, "_get_registry", new_callable=AsyncMock, return_value=mock_registry):
            await parser.pre_parse_all_async(context, files)

        assert "a.py" not in context.ast_cache

    @pytest.mark.asyncio
    async def test_pre_parse_empty_file_list(self, mock_registry):
        """Empty file list is a no-op."""
        context = _make_context()

        parser = ASTPreParser()
        with patch.object(parser, "_get_registry", new_callable=AsyncMock, return_value=mock_registry):
            await parser.pre_parse_all_async(context, [])

        assert len(context.ast_cache) == 0


class TestASTPreParserMemoryLimit:
    """AST cache never exceeds _MAX_AST_CACHE_ENTRIES entries."""

    @pytest.mark.asyncio
    async def test_cache_bounded_when_exceeds_max(self, mock_registry):
        """Parsing more files than the limit keeps cache size bounded."""
        context = _make_context()
        # Use a small artificial limit via monkeypatching the module constant
        import warden.pipeline.application.orchestrator.ast_pre_parser as _mod

        original = _mod._MAX_AST_CACHE_ENTRIES
        _mod._MAX_AST_CACHE_ENTRIES = 5

        try:
            files = [_make_code_file(f"src/f{i}.py") for i in range(20)]
            parser = ASTPreParser()
            with patch.object(parser, "_get_registry", new_callable=AsyncMock, return_value=mock_registry):
                await parser.pre_parse_all_async(context, files)

            assert len(context.ast_cache) <= 5
        finally:
            _mod._MAX_AST_CACHE_ENTRIES = original

    @pytest.mark.asyncio
    async def test_cache_not_evicted_below_max(self, mock_registry):
        """When file count is within limit, no eviction occurs."""
        context = _make_context()
        files = [_make_code_file(f"src/f{i}.py") for i in range(3)]

        parser = ASTPreParser()
        with patch.object(parser, "_get_registry", new_callable=AsyncMock, return_value=mock_registry):
            await parser.pre_parse_all_async(context, files)

        # All 3 files should be cached (well within the 500 limit)
        assert len(context.ast_cache) == 3

    @pytest.mark.asyncio
    async def test_eviction_removes_oldest_entries(self, mock_registry):
        """After eviction, the most recently parsed files survive."""
        context = _make_context()
        import warden.pipeline.application.orchestrator.ast_pre_parser as _mod

        original = _mod._MAX_AST_CACHE_ENTRIES
        _mod._MAX_AST_CACHE_ENTRIES = 5

        try:
            # Parse 10 files: f0..f9 (insertion order matters)
            files = [_make_code_file(f"src/f{i}.py") for i in range(10)]
            parser = ASTPreParser()
            with patch.object(parser, "_get_registry", new_callable=AsyncMock, return_value=mock_registry):
                await parser.pre_parse_all_async(context, files)

            # Cache must be bounded
            assert len(context.ast_cache) <= 5
            # Most recently inserted files should still be present
            assert "src/f9.py" in context.ast_cache
        finally:
            _mod._MAX_AST_CACHE_ENTRIES = original

    def test_max_ast_cache_entries_constant_is_reasonable(self):
        """The constant should be a positive integer within a sane range."""
        assert isinstance(_MAX_AST_CACHE_ENTRIES, int)
        assert 100 <= _MAX_AST_CACHE_ENTRIES <= 10_000
