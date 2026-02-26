"""Tests for StructuredPrompt and prompt builder integration."""

import pytest

from warden.llm.types import StructuredPrompt
from warden.llm.prompts.analysis import (
    ANALYSIS_SYSTEM_PROMPT,
    build_analysis_prompt,
    generate_analysis_request,
)
from warden.llm.prompts.classification import (
    CLASSIFICATION_SYSTEM_PROMPT,
    build_classification_prompt,
    generate_classification_request,
)
from warden.llm.prompts.resilience import (
    CHAOS_SYSTEM_PROMPT,
    build_chaos_prompt,
    generate_chaos_request,
)


class TestStructuredPrompt:
    """Unit tests for StructuredPrompt dataclass."""

    def test_creation(self):
        """Test basic StructuredPrompt creation."""
        sp = StructuredPrompt(
            system_context="You are Warden.",
            file_context="Analyze this code: print('hello')",
        )
        assert sp.system_context == "You are Warden."
        assert sp.file_context == "Analyze this code: print('hello')"

    def test_frozen(self):
        """Test that StructuredPrompt is immutable."""
        sp = StructuredPrompt(system_context="ctx", file_context="file")
        with pytest.raises(AttributeError):
            sp.system_context = "modified"

    def test_to_single_prompt(self):
        """Test flattening to a single prompt string."""
        sp = StructuredPrompt(
            system_context="System instructions here.",
            file_context="File content here.",
        )
        result = sp.to_single_prompt()
        assert "System instructions here." in result
        assert "File content here." in result
        assert result == "System instructions here.\n\nFile content here."

    def test_equality(self):
        """Test dataclass equality comparison."""
        sp1 = StructuredPrompt(system_context="a", file_context="b")
        sp2 = StructuredPrompt(system_context="a", file_context="b")
        assert sp1 == sp2

    def test_inequality(self):
        """Test dataclass inequality."""
        sp1 = StructuredPrompt(system_context="a", file_context="b")
        sp2 = StructuredPrompt(system_context="a", file_context="c")
        assert sp1 != sp2

    def test_empty_contexts(self):
        """Test with empty strings."""
        sp = StructuredPrompt(system_context="", file_context="")
        assert sp.to_single_prompt() == "\n\n"


class TestBuildAnalysisPrompt:
    """Tests for build_analysis_prompt."""

    def test_returns_structured_prompt(self):
        """build_analysis_prompt should return a StructuredPrompt."""
        sp = build_analysis_prompt(
            code="def hello(): pass",
            language="python",
            file_path="test.py",
        )
        assert isinstance(sp, StructuredPrompt)

    def test_system_context_matches_constant(self):
        """System context should be the ANALYSIS_SYSTEM_PROMPT."""
        sp = build_analysis_prompt(code="x = 1", language="python")
        assert sp.system_context == ANALYSIS_SYSTEM_PROMPT

    def test_file_context_contains_code(self):
        """File context should contain the source code."""
        sp = build_analysis_prompt(
            code="import os\nos.system('rm -rf /')",
            language="python",
            file_path="danger.py",
        )
        assert "os.system" in sp.file_context
        assert "danger.py" in sp.file_context

    def test_file_context_matches_generate(self):
        """File context should match generate_analysis_request output."""
        code = "x = 1"
        lang = "python"
        path = "test.py"
        sp = build_analysis_prompt(code, lang, path)
        expected = generate_analysis_request(code, lang, path)
        assert sp.file_context == expected

    def test_no_file_path(self):
        """Should work without file_path."""
        sp = build_analysis_prompt(code="x = 1", language="python")
        assert isinstance(sp, StructuredPrompt)
        assert "File:" not in sp.file_context


class TestBuildClassificationPrompt:
    """Tests for build_classification_prompt."""

    def test_returns_structured_prompt(self):
        """build_classification_prompt should return a StructuredPrompt."""
        sp = build_classification_prompt(
            code="async def fetch(): pass",
            language="python",
        )
        assert isinstance(sp, StructuredPrompt)

    def test_system_context_matches_constant(self):
        """System context should be the CLASSIFICATION_SYSTEM_PROMPT."""
        sp = build_classification_prompt(code="x = 1", language="python")
        assert sp.system_context == CLASSIFICATION_SYSTEM_PROMPT

    def test_file_context_contains_code(self):
        """File context should contain the source code."""
        sp = build_classification_prompt(
            code="async def fetch(): await api.get()",
            language="python",
            file_path="fetcher.py",
        )
        assert "async def fetch" in sp.file_context

    def test_file_context_matches_generate(self):
        """File context should match generate_classification_request."""
        code = "x = 1"
        lang = "python"
        sp = build_classification_prompt(code, lang)
        expected = generate_classification_request(code, lang)
        assert sp.file_context == expected


class TestBuildChaosPrompt:
    """Tests for build_chaos_prompt."""

    def test_returns_structured_prompt(self):
        """build_chaos_prompt should return a StructuredPrompt."""
        sp = build_chaos_prompt(
            code="conn = db.connect()",
            language="python",
        )
        assert isinstance(sp, StructuredPrompt)

    def test_system_context_matches_constant(self):
        """System context should be the CHAOS_SYSTEM_PROMPT."""
        sp = build_chaos_prompt(code="x = 1", language="python")
        assert sp.system_context == CHAOS_SYSTEM_PROMPT

    def test_with_context(self):
        """Should include context info in file_context."""
        sp = build_chaos_prompt(
            code="db.query('SELECT 1')",
            language="python",
            file_path="repo.py",
            context={"dependencies": ["database", "redis"]},
        )
        assert "database" in sp.file_context
        assert "redis" in sp.file_context

    def test_file_context_matches_generate(self):
        """File context should match generate_chaos_request."""
        code = "x = 1"
        lang = "python"
        ctx = {"dependencies": ["api"]}
        sp = build_chaos_prompt(code, lang, context=ctx)
        expected = generate_chaos_request(code, lang, context=ctx)
        assert sp.file_context == expected


class TestStructuredPromptImports:
    """Test that StructuredPrompt is importable from expected locations."""

    def test_import_from_types(self):
        from warden.llm.types import StructuredPrompt as SP
        assert SP is StructuredPrompt

    def test_import_from_llm_init(self):
        from warden.llm import StructuredPrompt as SP
        assert SP is StructuredPrompt
