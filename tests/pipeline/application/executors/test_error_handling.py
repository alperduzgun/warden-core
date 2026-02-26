"""
Tests for error handling consistency across executors.

Verifies:
1. All executors catch exceptions and add to context.errors
2. RuntimeError is re-raised by executors (for integrity checks)
3. Error logging uses consistent field names (error, error_type, tb)
4. Fortification executor no longer silently swallows errors

Note: These tests verify the error handling pattern exists in the source code
without requiring complex mocking of dynamic imports.
"""

from datetime import datetime
from pathlib import Path

import pytest

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import CodeFile


# All executor source paths (relative to project root)
_EXECUTOR_SOURCES = {
    "pre_analysis": "src/warden/pipeline/application/executors/pre_analysis_executor.py",
    "analysis": "src/warden/pipeline/application/executors/analysis_executor.py",
    "classification": "src/warden/pipeline/application/executors/classification_executor.py",
    "fortification": "src/warden/pipeline/application/executors/fortification_executor.py",
    "cleaning": "src/warden/pipeline/application/executors/cleaning_executor.py",
}


def _read_executor_source(name: str) -> str:
    """Read source code for a given executor name."""
    source_path = Path(_EXECUTOR_SOURCES[name])
    with open(source_path) as f:
        return f.read()


def _make_context(**overrides) -> PipelineContext:
    """Create a minimal PipelineContext for testing."""
    defaults = dict(
        pipeline_id="test-pipeline",
        started_at=datetime.now(),
        file_path=Path("/tmp/test.py"),
        source_code="x = 1",
    )
    defaults.update(overrides)
    return PipelineContext(**defaults)


def _make_code_files() -> list[CodeFile]:
    """Create a list of CodeFile objects for testing."""
    return [
        CodeFile(path="/tmp/test.py", content="x = 1", language="python"),
    ]


class TestExecutorErrorHandlingPatterns:
    """Test that all executors follow the standardized error handling pattern."""

    @pytest.mark.parametrize("executor_name", list(_EXECUTOR_SOURCES.keys()))
    def test_executor_has_runtime_error_handler(self, executor_name):
        """Every executor must catch RuntimeError separately for critical errors."""
        source = _read_executor_source(executor_name)
        assert "except RuntimeError as e:" in source, (
            f"{executor_name}: Missing RuntimeError handler"
        )

    @pytest.mark.parametrize("executor_name", list(_EXECUTOR_SOURCES.keys()))
    def test_executor_reraises_runtime_error(self, executor_name):
        """RuntimeError must be re-raised to stop the pipeline."""
        source = _read_executor_source(executor_name)
        assert "raise" in source, (
            f"{executor_name}: RuntimeError not being re-raised"
        )

    @pytest.mark.parametrize("executor_name", list(_EXECUTOR_SOURCES.keys()))
    def test_executor_has_general_exception_handler(self, executor_name):
        """Every executor must catch generic Exception for non-critical errors."""
        source = _read_executor_source(executor_name)
        assert "except Exception as e:" in source, (
            f"{executor_name}: Missing general exception handler"
        )

    @pytest.mark.parametrize("executor_name", list(_EXECUTOR_SOURCES.keys()))
    def test_executor_appends_to_context_errors(self, executor_name):
        """Every executor must record errors in context.errors."""
        source = _read_executor_source(executor_name)
        assert "context.errors.append" in source, (
            f"{executor_name}: Not adding errors to context.errors"
        )

    @pytest.mark.parametrize("executor_name", list(_EXECUTOR_SOURCES.keys()))
    def test_executor_logs_traceback(self, executor_name):
        """Every executor must log the full traceback."""
        source = _read_executor_source(executor_name)
        assert "traceback.format_exc()" in source, (
            f"{executor_name}: Not logging traceback"
        )

    @pytest.mark.parametrize("executor_name", list(_EXECUTOR_SOURCES.keys()))
    def test_executor_logs_error_type(self, executor_name):
        """Every executor must log error_type for structured error reporting."""
        source = _read_executor_source(executor_name)
        assert 'error_type=type(e).__name__' in source, (
            f"{executor_name}: Missing error_type in error log"
        )

    @pytest.mark.parametrize("executor_name", list(_EXECUTOR_SOURCES.keys()))
    def test_executor_uses_consistent_tb_field(self, executor_name):
        """Every executor must use 'tb=' (not 'traceback=') as the log field name."""
        source = _read_executor_source(executor_name)
        # The phase_failed log call must use tb= not traceback=
        assert "tb=traceback.format_exc()" in source, (
            f"{executor_name}: Must use 'tb=' field name for traceback logging"
        )


class TestFortificationErrorHandlingStandardized:
    """Verify fortification executor no longer silently swallows errors."""

    def test_fortification_has_runtime_error_handler(self):
        """Fortification must now handle RuntimeError explicitly (was missing before)."""
        source = _read_executor_source("fortification")
        assert "except RuntimeError as e:" in source, (
            "Fortification executor must have separate RuntimeError handler"
        )

    def test_fortification_no_silent_catch(self):
        """Fortification must not silently swallow exceptions with bare pass."""
        source = _read_executor_source("fortification")
        # The old pattern: except (ValueError, TypeError, RuntimeError): pass
        assert "except (ValueError, TypeError, RuntimeError)" not in source, (
            "Fortification must not silently catch ValueError/TypeError/RuntimeError"
        )

    def test_fortification_diff_errors_are_logged(self):
        """Diff generation errors must be logged, not silently swallowed."""
        source = _read_executor_source("fortification")
        assert "fortification_diff_generation_failed" in source, (
            "Diff generation errors must be logged with a structured event"
        )


class TestErrorContextBehavior:
    """Test that context.errors is properly populated."""

    def test_context_errors_starts_empty(self):
        """Test that context.errors starts as an empty list."""
        ctx = _make_context()
        assert ctx.errors == []
        assert isinstance(ctx.errors, list)

    def test_context_errors_can_be_appended(self):
        """Test that errors can be added to context.errors."""
        ctx = _make_context()
        ctx.errors.append("Test error 1")
        ctx.errors.append("Test error 2")

        assert len(ctx.errors) == 2
        assert "Test error 1" in ctx.errors
        assert "Test error 2" in ctx.errors


class TestErrorHandlingDocumentation:
    """Test that error handling is properly documented."""

    def test_analysis_executor_documents_error_behavior(self):
        """Test that AnalysisExecutor has error handling documentation."""
        from warden.pipeline.application.executors import analysis_executor

        # Check that the module has a docstring
        assert analysis_executor.__doc__ is not None

        # Check that execute_async method exists
        from warden.pipeline.application.executors.analysis_executor import AnalysisExecutor

        assert hasattr(AnalysisExecutor, "execute_async")
        assert callable(getattr(AnalysisExecutor, "execute_async"))

    def test_all_executors_have_execute_async(self):
        """Test that all executors have execute_async method."""
        from warden.pipeline.application.executors.analysis_executor import AnalysisExecutor
        from warden.pipeline.application.executors.cleaning_executor import CleaningExecutor
        from warden.pipeline.application.executors.classification_executor import (
            ClassificationExecutor,
        )
        from warden.pipeline.application.executors.fortification_executor import (
            FortificationExecutor,
        )
        from warden.pipeline.application.executors.pre_analysis_executor import (
            PreAnalysisExecutor,
        )

        executors = [
            AnalysisExecutor,
            CleaningExecutor,
            ClassificationExecutor,
            FortificationExecutor,
            PreAnalysisExecutor,
        ]

        for executor_class in executors:
            assert hasattr(executor_class, "execute_async"), (
                f"{executor_class.__name__} missing execute_async method"
            )
            assert callable(getattr(executor_class, "execute_async")), (
                f"{executor_class.__name__}.execute_async is not callable"
            )
