"""
Tests for LLM-powered orphan code filter.

Tests cover:
- Basic filtering functionality
- False positive detection (properties, abstractmethod, etc.)
- Language-agnostic support
- Error handling and fallbacks
- Batch processing
- LLM response parsing
"""

import pytest
import json
from typing import List
from unittest.mock import Mock, AsyncMock, patch

from warden.validation.frames.llm_orphan_filter import (
    LLMOrphanFilter,
    FilterDecision,
)
from warden.validation.frames.orphan_detector import OrphanFinding
from warden.validation.domain.frame import CodeFile
from warden.llm.types import LlmResponse


# ============================================
# FIXTURES
# ============================================

@pytest.fixture
def sample_code_file() -> CodeFile:
    """Sample Python code file with various patterns."""
    code = """
from abc import ABC, abstractmethod
from typing import List
import unused_import

class BaseAnalyzer(ABC):
    @property
    def name(self) -> str:
        return "analyzer"

    @abstractmethod
    def analyze(self) -> None:
        pass

class SpecificAnalyzer(BaseAnalyzer):
    def analyze(self) -> None:
        print("analyzing")

    def to_json(self) -> dict:
        return {"name": self.name}

def truly_unused_function():
    return 42
"""

    return CodeFile(
        path="test.py",
        content=code,
        language="python",
    )


@pytest.fixture
def sample_findings() -> List[OrphanFinding]:
    """Sample orphan findings with mixed true/false positives."""
    return [
        # FALSE POSITIVE: @property
        OrphanFinding(
            orphan_type="unreferenced_function",
            name="name",
            line_number=7,
            code_snippet="def name(self) -> str:",
            reason="Function 'name' is defined but never called",
        ),
        # FALSE POSITIVE: @abstractmethod
        OrphanFinding(
            orphan_type="unreferenced_function",
            name="analyze",
            line_number=11,
            code_snippet="def analyze(self) -> None:",
            reason="Function 'analyze' is defined but never called",
        ),
        # FALSE POSITIVE: Serialization method
        OrphanFinding(
            orphan_type="unreferenced_function",
            name="to_json",
            line_number=19,
            code_snippet="def to_json(self) -> dict:",
            reason="Function 'to_json' is defined but never called",
        ),
        # FALSE POSITIVE: Unused import (but type hint)
        OrphanFinding(
            orphan_type="unused_import",
            name="List",
            line_number=2,
            code_snippet="from typing import List",
            reason="Import 'List' is never used in the code",
        ),
        # TRUE ORPHAN: Actually unused
        OrphanFinding(
            orphan_type="unreferenced_function",
            name="truly_unused_function",
            line_number=22,
            code_snippet="def truly_unused_function():",
            reason="Function 'truly_unused_function' is defined but never called",
        ),
        # TRUE ORPHAN: Actually unused import
        OrphanFinding(
            orphan_type="unused_import",
            name="unused_import",
            line_number=3,
            code_snippet="import unused_import",
            reason="Import 'unused_import' is never used in the code",
        ),
    ]


@pytest.fixture
def mock_llm_response_correct() -> str:
    """Mock LLM response with correct decisions."""
    return """
{
  "decisions": [
    {
      "finding_id": 0,
      "is_true_orphan": false,
      "reasoning": "@property decorator detected. Properties are accessed as attributes, not called as functions. FALSE POSITIVE.",
      "confidence": 0.95
    },
    {
      "finding_id": 1,
      "is_true_orphan": false,
      "reasoning": "@abstractmethod decorator in ABC class. Abstract methods define contracts. FALSE POSITIVE.",
      "confidence": 0.95
    },
    {
      "finding_id": 2,
      "is_true_orphan": false,
      "reasoning": "Method 'to_json' is a standard serialization method. Called by frameworks. FALSE POSITIVE.",
      "confidence": 0.9
    },
    {
      "finding_id": 3,
      "is_true_orphan": false,
      "reasoning": "Import 'List' from typing. Likely used in type hints. FALSE POSITIVE.",
      "confidence": 0.85
    },
    {
      "finding_id": 4,
      "is_true_orphan": true,
      "reasoning": "Function 'truly_unused_function' is defined but never called. No decorators, not abstract. TRUE ORPHAN.",
      "confidence": 0.95
    },
    {
      "finding_id": 5,
      "is_true_orphan": true,
      "reasoning": "Import 'unused_import' is truly never used anywhere. TRUE ORPHAN.",
      "confidence": 0.95
    }
  ]
}
"""


# ============================================
# TESTS: Basic Functionality
# ============================================

class TestLLMOrphanFilterBasics:
    """Test basic LLM filter functionality."""

    @pytest.mark.asyncio
    async def test_filter_findings_success(
        self,
        sample_code_file,
        sample_findings,
        mock_llm_response_correct,
    ):
        """Test successful filtering of findings."""
        # Create filter
        filter = LLMOrphanFilter()

        # Mock LLM client
        mock_llm = AsyncMock()
        mock_llm.analyze.return_value = LlmResponse(
            content=mock_llm_response_correct,
            usage={"input_tokens": 1000, "output_tokens": 500},
        )
        filter.llm = mock_llm

        # Filter findings
        true_orphans = await filter.filter_findings(
            findings=sample_findings,
            code_file=sample_code_file,
            language="python",
        )

        # Assertions
        assert len(true_orphans) == 2  # Only 2 TRUE orphans
        assert true_orphans[0].name == "truly_unused_function"
        assert true_orphans[1].name == "unused_import"

        # Verify LLM was called
        mock_llm.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_findings(self, sample_code_file):
        """Test with no findings."""
        filter = LLMOrphanFilter()

        true_orphans = await filter.filter_findings(
            findings=[],
            code_file=sample_code_file,
            language="python",
        )

        assert len(true_orphans) == 0

    @pytest.mark.asyncio
    async def test_batch_processing(self, sample_code_file):
        """Test that findings are batched correctly."""
        filter = LLMOrphanFilter(batch_size=2)  # Small batch for testing

        # Create 5 findings
        findings = [
            OrphanFinding(
                orphan_type="unreferenced_function",
                name=f"func_{i}",
                line_number=i,
                code_snippet=f"def func_{i}():",
                reason="Unreferenced",
            )
            for i in range(5)
        ]

        # Mock LLM to return all as false
        mock_llm = AsyncMock()
        mock_llm.analyze.return_value = LlmResponse(
            content=json.dumps({
                "decisions": [
                    {"finding_id": i, "is_true_orphan": False, "reasoning": "Test"}
                    for i in range(2)  # Batch size
                ]
            }),
            usage={},
        )
        filter.llm = mock_llm

        await filter.filter_findings(findings, sample_code_file, "python")

        # Verify LLM was called 3 times (5 findings ÷ 2 batch size = 3 batches)
        assert mock_llm.analyze.call_count == 3


# ============================================
# TESTS: False Positive Detection
# ============================================

class TestFalsePositiveDetection:
    """Test detection of common false positive patterns."""

    @pytest.mark.asyncio
    async def test_property_decorator_detection(self, sample_code_file):
        """Test that @property decorated methods are NOT reported."""
        filter = LLMOrphanFilter()

        findings = [
            OrphanFinding(
                orphan_type="unreferenced_function",
                name="name",
                line_number=7,
                code_snippet="@property\ndef name(self):",
                reason="Unreferenced",
            )
        ]

        # Mock LLM to correctly identify as false positive
        mock_llm = AsyncMock()
        mock_llm.analyze.return_value = LlmResponse(
            content=json.dumps({
                "decisions": [{
                    "finding_id": 0,
                    "is_true_orphan": false,
                    "reasoning": "@property decorator - FALSE POSITIVE"
                }]
            }),
            usage={},
        )
        filter.llm = mock_llm

        true_orphans = await filter.filter_findings(findings, sample_code_file, "python")

        assert len(true_orphans) == 0  # Should be filtered out

    @pytest.mark.asyncio
    async def test_abstractmethod_detection(self, sample_code_file):
        """Test that @abstractmethod methods are NOT reported."""
        filter = LLMOrphanFilter()

        findings = [
            OrphanFinding(
                orphan_type="unreferenced_function",
                name="analyze",
                line_number=11,
                code_snippet="@abstractmethod\ndef analyze(self):",
                reason="Unreferenced",
            )
        ]

        mock_llm = AsyncMock()
        mock_llm.analyze.return_value = LlmResponse(
            content=json.dumps({
                "decisions": [{
                    "finding_id": 0,
                    "is_true_orphan": False,
                    "reasoning": "@abstractmethod in ABC - FALSE POSITIVE"
                }]
            }),
            usage={},
        )
        filter.llm = mock_llm

        true_orphans = await filter.filter_findings(findings, sample_code_file, "python")

        assert len(true_orphans) == 0


# ============================================
# TESTS: Language Support
# ============================================

class TestLanguageSupport:
    """Test language-agnostic filtering."""

    @pytest.mark.asyncio
    async def test_python_support(self, sample_code_file):
        """Test Python-specific patterns."""
        filter = LLMOrphanFilter()
        assert "python" in filter.LANGUAGE_HINTS

        hints = filter.LANGUAGE_HINTS["python"]
        assert "@property" in hints["decorators"]
        assert "ABC" in hints["protocols"]

    @pytest.mark.asyncio
    async def test_javascript_support(self):
        """Test JavaScript support."""
        filter = LLMOrphanFilter()
        assert "javascript" in filter.LANGUAGE_HINTS

        hints = filter.LANGUAGE_HINTS["javascript"]
        assert "export" in hints["exports"]

    @pytest.mark.asyncio
    async def test_go_support(self):
        """Test Go support."""
        filter = LLMOrphanFilter()
        assert "go" in filter.LANGUAGE_HINTS

        hints = filter.LANGUAGE_HINTS["go"]
        assert "interface" in hints["interfaces"]


# ============================================
# TESTS: Error Handling
# ============================================

class TestErrorHandling:
    """Test error handling and fallbacks."""

    @pytest.mark.asyncio
    async def test_llm_api_error_fallback(self, sample_code_file, sample_findings):
        """Test fallback when LLM API fails."""
        filter = LLMOrphanFilter(max_retries=1)

        # Mock LLM to raise error
        mock_llm = AsyncMock()
        mock_llm.analyze.side_effect = Exception("API Error")
        filter.llm = mock_llm

        # Should raise after retries
        with pytest.raises(Exception):
            await filter.filter_findings(sample_findings, sample_code_file, "python")

    @pytest.mark.asyncio
    async def test_malformed_json_response(self, sample_code_file, sample_findings):
        """Test handling of malformed JSON response."""
        filter = LLMOrphanFilter()

        # Mock LLM to return malformed JSON
        mock_llm = AsyncMock()
        mock_llm.analyze.return_value = LlmResponse(
            content="This is not valid JSON!",
            usage={},
        )
        filter.llm = mock_llm

        true_orphans = await filter.filter_findings(sample_findings, sample_code_file, "python")

        # Should return all as false (conservative fallback)
        assert len(true_orphans) == 0

    @pytest.mark.asyncio
    async def test_wrong_decision_count(self, sample_code_file, sample_findings):
        """Test handling of wrong number of decisions."""
        filter = LLMOrphanFilter()

        # Mock LLM to return wrong count
        mock_llm = AsyncMock()
        mock_llm.analyze.return_value = LlmResponse(
            content=json.dumps({
                "decisions": [
                    {"finding_id": 0, "is_true_orphan": False, "reasoning": "Test"}
                    # Missing decisions for other findings!
                ]
            }),
            usage={},
        )
        filter.llm = mock_llm

        true_orphans = await filter.filter_findings(sample_findings, sample_code_file, "python")

        # Should handle gracefully with conservative fallback
        assert len(true_orphans) == 0


# ============================================
# TESTS: JSON Parsing
# ============================================

class TestJSONParsing:
    """Test LLM response JSON parsing."""

    def test_extract_json_from_markdown(self):
        """Test extracting JSON from markdown code blocks."""
        filter = LLMOrphanFilter()

        response = """
Here's the analysis:

```json
{"decisions": [{"finding_id": 0, "is_true_orphan": true}]}
```

That's it!
"""

        json_str = filter._extract_json(response)
        data = json.loads(json_str)

        assert "decisions" in data
        assert data["decisions"][0]["finding_id"] == 0

    def test_extract_json_plain(self):
        """Test extracting plain JSON without markdown."""
        filter = LLMOrphanFilter()

        response = '{"decisions": [{"finding_id": 0, "is_true_orphan": true}]}'

        json_str = filter._extract_json(response)
        data = json.loads(json_str)

        assert "decisions" in data

    def test_parse_filter_decision(self):
        """Test parsing FilterDecision from JSON."""
        filter = LLMOrphanFilter()

        response = json.dumps({
            "decisions": [
                {
                    "finding_id": 0,
                    "is_true_orphan": True,
                    "reasoning": "Test reasoning",
                    "confidence": 0.95,
                },
                {
                    "finding_id": 1,
                    "is_true_orphan": False,
                    "reasoning": "Another test",
                    "confidence": 0.85,
                }
            ]
        })

        decisions = filter._parse_llm_response(response, expected_count=2)

        assert len(decisions) == 2
        assert decisions[0].is_true_orphan is True
        assert decisions[0].confidence == 0.95
        assert decisions[1].is_true_orphan is False


# ============================================
# TESTS: Prompt Building
# ============================================

class TestPromptBuilding:
    """Test prompt generation for LLM."""

    def test_build_prompt_includes_findings(self, sample_code_file, sample_findings):
        """Test that prompt includes all findings."""
        filter = LLMOrphanFilter()

        prompt = filter._build_filter_prompt(
            findings=sample_findings,
            code_file=sample_code_file,
            language="python",
        )

        # Verify all findings are included
        for finding in sample_findings:
            assert finding.name in prompt
            assert str(finding.line_number) in prompt

    def test_build_prompt_includes_language_hints(self, sample_code_file, sample_findings):
        """Test that prompt includes language-specific hints."""
        filter = LLMOrphanFilter()

        prompt = filter._build_filter_prompt(
            findings=sample_findings,
            code_file=sample_code_file,
            language="python",
        )

        # Verify Python hints are included
        assert "@property" in prompt
        assert "@abstractmethod" in prompt
        assert "ABC" in prompt

    def test_format_findings_for_llm(self, sample_findings):
        """Test formatting of findings for LLM."""
        filter = LLMOrphanFilter()

        formatted = filter._format_findings_for_llm(sample_findings)

        assert "Finding 0:" in formatted
        assert "truly_unused_function" in formatted
        assert "Line: 22" in formatted


# ============================================
# TESTS: Integration
# ============================================

@pytest.mark.integration
class TestIntegration:
    """Integration tests (require real LLM API)."""

    @pytest.mark.skip(reason="Requires LLM API key")
    @pytest.mark.asyncio
    async def test_real_llm_filtering(self, sample_code_file, sample_findings):
        """Test with real LLM API (skipped by default)."""
        filter = LLMOrphanFilter()

        true_orphans = await filter.filter_findings(
            findings=sample_findings,
            code_file=sample_code_file,
            language="python",
        )

        # Should filter out false positives
        assert len(true_orphans) < len(sample_findings)
        assert all(
            finding.name in ["truly_unused_function", "unused_import"]
            for finding in true_orphans
        )
