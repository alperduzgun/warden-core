"""
Tests for Cleanup Analyzers

Verifies that:
- Each analyzer can detect its target issue type
- Panel JSON serialization works
- No code modification occurs
"""

import pytest
import json
from warden.analyzers.cleanup.analyzers import (
    NamingAnalyzer,
    DuplicationAnalyzer,
    MagicNumberAnalyzer,
    ComplexityAnalyzer,
)
from warden.analyzers.cleanup.analyzer import CleanupAnalyzer
from warden.validation.domain.frame import CodeFile


# Test code samples
SAMPLE_CODE_WITH_NAMING_ISSUES = """
def process(x):
    tmp = x * 2
    val = tmp + 1
    return val

class myclass:
    def __init__(self, v):
        self.v = v
"""

SAMPLE_CODE_WITH_DUPLICATION = """
def calculate_total_a(items):
    total = 0
    for item in items:
        total += item.price
    return total

def calculate_total_b(products):
    total = 0
    for item in products:
        total += item.price
    return total
"""

SAMPLE_CODE_WITH_MAGIC_NUMBERS = """
def calculate_discount(price):
    if price > 100:
        return price * 0.15
    elif price > 50:
        return price * 0.10
    else:
        return price * 0.05

def get_timeout():
    return 300
"""

SAMPLE_CODE_WITH_COMPLEXITY = """
def very_long_function(a, b, c, d, e, f, g):
    # This function has too many parameters
    if a > 0:
        if b > 0:
            if c > 0:
                if d > 0:
                    if e > 0:
                        # Deep nesting
                        result = a + b + c + d + e
                        return result

    # Add more lines to make it long
    line1 = 1
    line2 = 2
    line3 = 3
    line4 = 4
    line5 = 5
    line6 = 6
    line7 = 7
    line8 = 8
    line9 = 9
    line10 = 10
    line11 = 11
    line12 = 12
    line13 = 13
    line14 = 14
    line15 = 15
    line16 = 16
    line17 = 17
    line18 = 18
    line19 = 19
    line20 = 20
    line21 = 21
    line22 = 22
    line23 = 23
    line24 = 24
    line25 = 25
    line26 = 26
    line27 = 27
    line28 = 28
    line29 = 29
    line30 = 30
    line31 = 31
    line32 = 32
    line33 = 33
    line34 = 34
    line35 = 35
    line36 = 36
    line37 = 37
    line38 = 38
    line39 = 39
    line40 = 40
    line41 = 41
    line42 = 42
    line43 = 43
    line44 = 44
    line45 = 45
    line46 = 46
    line47 = 47
    line48 = 48
    line49 = 49
    line50 = 50
    line51 = 51
    line52 = 52

    return f + g
"""

SAMPLE_CODE_CLEAN = """
def calculate_sum(numbers):
    \"\"\"Calculate the sum of numbers.\"\"\"
    return sum(numbers)

class Calculator:
    \"\"\"Simple calculator class.\"\"\"

    def add(self, first_number, second_number):
        \"\"\"Add two numbers.\"\"\"
        return first_number + second_number
"""


class TestNamingAnalyzer:
    """Test Naming Analyzer."""

    @pytest.mark.asyncio
    async def test_detects_naming_issues(self):
        """Test that naming analyzer detects naming issues."""
        analyzer = NamingAnalyzer()
        code_file = CodeFile(
            path="/test/code.py",
            content=SAMPLE_CODE_WITH_NAMING_ISSUES,
            language="python",
        )

        result = await analyzer.analyze_async(code_file)

        assert result.success
        assert result.issues_found > 0
        assert len(result.suggestions) > 0
        assert any("naming" in s.issue.issue_type.value.lower() for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_no_issues_with_clean_code(self):
        """Test that no issues are found in clean code."""
        analyzer = NamingAnalyzer()
        code_file = CodeFile(
            path="/test/code.py",
            content=SAMPLE_CODE_CLEAN,
            language="python",
        )

        result = await analyzer.analyze_async(code_file)

        assert result.success
        assert result.issues_found == 0
        assert result.cleanup_score == 100.0

    @pytest.mark.asyncio
    async def test_does_not_modify_code(self):
        """Test that analyzer does not modify code."""
        analyzer = NamingAnalyzer()
        original_code = SAMPLE_CODE_WITH_NAMING_ISSUES
        code_file = CodeFile(
            path="/test/code.py",
            content=original_code,
            language="python",
        )

        await analyzer.analyze_async(code_file)

        # Code file should remain unchanged
        assert code_file.content == original_code


class TestDuplicationAnalyzer:
    """Test Duplication Analyzer."""

    @pytest.mark.asyncio
    async def test_detects_duplication(self):
        """Test that duplication analyzer detects duplicate code."""
        analyzer = DuplicationAnalyzer()
        code_file = CodeFile(
            path="/test/code.py",
            content=SAMPLE_CODE_WITH_DUPLICATION,
            language="python",
        )

        result = await analyzer.analyze_async(code_file)

        assert result.success
        assert result.issues_found > 0
        assert any("duplication" in s.issue.issue_type.value.lower() for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_does_not_modify_code(self):
        """Test that analyzer does not modify code."""
        analyzer = DuplicationAnalyzer()
        original_code = SAMPLE_CODE_WITH_DUPLICATION
        code_file = CodeFile(
            path="/test/code.py",
            content=original_code,
            language="python",
        )

        await analyzer.analyze_async(code_file)

        assert code_file.content == original_code


class TestMagicNumberAnalyzer:
    """Test Magic Number Analyzer."""

    @pytest.mark.asyncio
    async def test_detects_magic_numbers(self):
        """Test that magic number analyzer detects magic numbers."""
        analyzer = MagicNumberAnalyzer()
        code_file = CodeFile(
            path="/test/code.py",
            content=SAMPLE_CODE_WITH_MAGIC_NUMBERS,
            language="python",
        )

        result = await analyzer.analyze_async(code_file)

        assert result.success
        assert result.issues_found > 0
        assert any("magic" in s.issue.issue_type.value.lower() for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_does_not_modify_code(self):
        """Test that analyzer does not modify code."""
        analyzer = MagicNumberAnalyzer()
        original_code = SAMPLE_CODE_WITH_MAGIC_NUMBERS
        code_file = CodeFile(
            path="/test/code.py",
            content=original_code,
            language="python",
        )

        await analyzer.analyze_async(code_file)

        assert code_file.content == original_code


class TestComplexityAnalyzer:
    """Test Complexity Analyzer."""

    @pytest.mark.asyncio
    async def test_detects_complexity_issues(self):
        """Test that complexity analyzer detects complex code."""
        analyzer = ComplexityAnalyzer()
        code_file = CodeFile(
            path="/test/code.py",
            content=SAMPLE_CODE_WITH_COMPLEXITY,
            language="python",
        )

        result = await analyzer.analyze_async(code_file)

        assert result.success
        assert result.issues_found > 0
        assert any(
            s.issue.issue_type.value in ["long_method", "complex_method"]
            for s in result.suggestions
        )

    @pytest.mark.asyncio
    async def test_does_not_modify_code(self):
        """Test that analyzer does not modify code."""
        analyzer = ComplexityAnalyzer()
        original_code = SAMPLE_CODE_WITH_COMPLEXITY
        code_file = CodeFile(
            path="/test/code.py",
            content=original_code,
            language="python",
        )

        await analyzer.analyze_async(code_file)

        assert code_file.content == original_code


class TestCleanupAnalyzer:
    """Test Cleanup Analyzer orchestrator."""

    @pytest.mark.asyncio
    async def test_runs_all_analyzers(self):
        """Test that cleanup analyzer runs all analyzers."""
        analyzer = CleanupAnalyzer()
        code_file = CodeFile(
            path="/test/code.py",
            content=SAMPLE_CODE_WITH_NAMING_ISSUES,
            language="python",
        )

        result = await analyzer.analyze_async(code_file)

        assert result.success
        assert result.analyzer_name == "CleanupAnalyzer"
        assert "total_analyzers" in result.metrics
        assert result.metrics["total_analyzers"] == 4

    @pytest.mark.asyncio
    async def test_combines_results(self):
        """Test that cleanup analyzer combines results from all analyzers."""
        analyzer = CleanupAnalyzer()
        code_file = CodeFile(
            file_path="/test/code.py",
            content=SAMPLE_CODE_WITH_NAMING_ISSUES + "\n" + SAMPLE_CODE_WITH_MAGIC_NUMBERS,
            language="python",
        )

        result = await analyzer.analyze_async(code_file)

        assert result.success
        assert result.issues_found > 0
        # Should have suggestions from multiple analyzers
        assert len(result.suggestions) > 0

    @pytest.mark.asyncio
    async def test_does_not_modify_code(self):
        """Test that orchestrator does not modify code."""
        analyzer = CleanupAnalyzer()
        original_code = SAMPLE_CODE_WITH_NAMING_ISSUES
        code_file = CodeFile(
            path="/test/code.py",
            content=original_code,
            language="python",
        )

        await analyzer.analyze_async(code_file)

        assert code_file.content == original_code


class TestPanelJsonSerialization:
    """Test Panel JSON serialization."""

    @pytest.mark.asyncio
    async def test_result_serializes_to_json(self):
        """Test that CleanupResult serializes to Panel JSON."""
        analyzer = NamingAnalyzer()
        code_file = CodeFile(
            path="/test/code.py",
            content=SAMPLE_CODE_WITH_NAMING_ISSUES,
            language="python",
        )

        result = await analyzer.analyze_async(code_file)

        # Convert to JSON
        json_data = result.to_json()

        # Verify camelCase keys
        assert "success" in json_data
        assert "filePath" in json_data
        assert "issuesFound" in json_data
        assert "suggestions" in json_data
        assert "cleanupScore" in json_data
        assert "summary" in json_data
        assert "analyzerName" in json_data

        # Verify JSON is serializable
        json_string = json.dumps(json_data)
        assert json_string is not None
        assert len(json_string) > 0

    @pytest.mark.asyncio
    async def test_suggestion_serializes_to_json(self):
        """Test that CleanupSuggestion serializes to Panel JSON."""
        analyzer = NamingAnalyzer()
        code_file = CodeFile(
            path="/test/code.py",
            content=SAMPLE_CODE_WITH_NAMING_ISSUES,
            language="python",
        )

        result = await analyzer.analyze_async(code_file)

        if result.suggestions:
            suggestion = result.suggestions[0]
            json_data = suggestion.to_json()

            # Verify camelCase keys
            assert "issue" in json_data
            assert "suggestion" in json_data
            assert "rationale" in json_data

            # Verify issue has camelCase keys
            issue_data = json_data["issue"]
            assert "issueType" in issue_data
            assert "description" in issue_data
            assert "lineNumber" in issue_data
            assert "severity" in issue_data

    @pytest.mark.asyncio
    async def test_json_roundtrip(self):
        """Test that JSON can be serialized and deserialized."""
        from warden.analyzers.cleanup.models import CleanupResult

        analyzer = NamingAnalyzer()
        code_file = CodeFile(
            path="/test/code.py",
            content=SAMPLE_CODE_WITH_NAMING_ISSUES,
            language="python",
        )

        original_result = await analyzer.analyze_async(code_file)

        # Serialize to JSON
        json_data = original_result.to_json()

        # Deserialize from JSON
        restored_result = CleanupResult.from_json(json_data)

        # Verify key fields match
        assert restored_result.success == original_result.success
        assert restored_result.file_path == original_result.file_path
        assert restored_result.issues_found == original_result.issues_found
        assert len(restored_result.suggestions) == len(original_result.suggestions)
        assert restored_result.cleanup_score == original_result.cleanup_score
