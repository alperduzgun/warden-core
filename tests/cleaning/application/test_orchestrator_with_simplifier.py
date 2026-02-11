"""
Tests for CleaningOrchestrator with CodeSimplifierAnalyzer integration.
"""

import pytest

from warden.cleaning.application.orchestrator import CleaningOrchestrator
from warden.validation.domain.frame import CodeFile


@pytest.mark.asyncio
class TestOrchestratorIntegration:
    """Test that orchestrator integrates CodeSimplifierAnalyzer properly."""

    async def test_orchestrator_includes_simplifier(self):
        """Orchestrator should include CodeSimplifierAnalyzer by default."""
        orchestrator = CleaningOrchestrator()
        analyzers = orchestrator.get_analyzers()

        analyzer_names = [a.name for a in analyzers]
        assert "Code Simplifier" in analyzer_names

    async def test_orchestrator_runs_simplifier(self):
        """Orchestrator should run CodeSimplifierAnalyzer on code."""
        orchestrator = CleaningOrchestrator()

        code = """
def process(x):
    if x is not None:
        if x > 0:
            if x < 100:
                message = "Value is %d" % x
                return x * 2
    return None
"""
        code_file = CodeFile(path="test.py", content=code, language="python")
        result = await orchestrator.analyze_async(code_file)

        assert result.success
        assert result.issues_found > 0
        # Should have suggestions from multiple analyzers including simplifier
        assert len(result.suggestions) > 0

    async def test_orchestrator_priority_order(self):
        """CodeSimplifierAnalyzer should have HIGH priority."""
        orchestrator = CleaningOrchestrator()
        analyzers = orchestrator.get_analyzers()

        # Find the simplifier
        simplifier = next(a for a in analyzers if a.name == "Code Simplifier")
        assert simplifier.priority == 1  # HIGH priority

        # Should run after CRITICAL but before MEDIUM
        priorities = [a.priority for a in analyzers]
        assert sorted(priorities) == priorities  # Should be sorted by priority

    async def test_orchestrator_with_clean_code(self):
        """Orchestrator should report high score for clean code."""
        orchestrator = CleaningOrchestrator()

        code = """
def add(a, b):
    return a + b

def greet(name):
    return f"Hello {name}"
"""
        code_file = CodeFile(path="test.py", content=code, language="python")
        result = await orchestrator.analyze_async(code_file)

        assert result.success
        # Clean code should have high score
        assert result.cleanup_score >= 80.0

    async def test_orchestrator_metrics_include_simplifier(self):
        """Orchestrator metrics should include simplifier metrics."""
        orchestrator = CleaningOrchestrator()

        code = """
def process(x):
    if x is not None:
        if x > 0:
            return x * 2
    return None
"""
        code_file = CodeFile(path="test.py", content=code, language="python")
        result = await orchestrator.analyze_async(code_file)

        assert result.success
        # Metrics should include analyzer results
        assert "analyzer_metrics" in result.metrics
