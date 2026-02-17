"""
Tests for error handling consistency across executors.

Verifies:
1. All executors catch exceptions and add to context.errors
2. RuntimeError is re-raised by executors (for integrity checks)

Note: These tests verify the error handling pattern exists in the source code
without requiring complex mocking of dynamic imports.
"""

from datetime import datetime
from pathlib import Path

import pytest

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import CodeFile


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
    """Test that executors follow the error handling pattern."""

    def test_analysis_executor_has_error_handling(self):
        """Test that AnalysisExecutor has proper error handling in source code."""
        from pathlib import Path

        # Read the source code of AnalysisExecutor
        source_path = Path("src/warden/pipeline/application/executors/analysis_executor.py")
        with open(source_path) as f:
            source_code = f.read()

        # Check for error handling pattern
        assert "except RuntimeError as e:" in source_code, "Missing RuntimeError re-raise"
        assert "raise e" in source_code, "RuntimeError not being re-raised"
        assert "except Exception as e:" in source_code, "Missing general exception handler"
        assert "context.errors.append" in source_code, "Not adding errors to context"
        assert "traceback.format_exc()" in source_code, "Not logging traceback"

    def test_cleaning_executor_has_error_handling(self):
        """Test that CleaningExecutor has proper error handling in source code."""
        from pathlib import Path

        source_path = Path("src/warden/pipeline/application/executors/cleaning_executor.py")
        with open(source_path) as f:
            source_code = f.read()

        # Check for error handling pattern
        assert "except RuntimeError as e:" in source_code, "Missing RuntimeError re-raise"
        assert "raise e" in source_code, "RuntimeError not being re-raised"
        assert "except Exception as e:" in source_code, "Missing general exception handler"
        assert "context.errors.append" in source_code, "Not adding errors to context"
        assert "traceback.format_exc()" in source_code, "Not logging traceback"

    def test_pre_analysis_executor_has_error_handling(self):
        """Test that PreAnalysisExecutor has proper error handling in source code."""
        from pathlib import Path

        source_path = Path("src/warden/pipeline/application/executors/pre_analysis_executor.py")
        with open(source_path) as f:
            source_code = f.read()

        # Check for error handling pattern
        assert "except RuntimeError as e:" in source_code, "Missing RuntimeError re-raise"
        assert "raise e" in source_code, "RuntimeError not being re-raised"
        assert "except Exception as e:" in source_code, "Missing general exception handler"
        assert "context.errors.append" in source_code, "Not adding errors to context"
        assert "traceback.format_exc()" in source_code, "Not logging traceback"

    def test_classification_executor_has_error_handling(self):
        """Test that ClassificationExecutor has proper error handling in source code."""
        from pathlib import Path

        source_path = Path("src/warden/pipeline/application/executors/classification_executor.py")
        with open(source_path) as f:
            source_code = f.read()

        # Check for error handling pattern
        assert "except RuntimeError as e:" in source_code, "Missing RuntimeError re-raise"
        assert "raise e" in source_code, "RuntimeError not being re-raised"
        assert "except Exception as e:" in source_code, "Missing general exception handler"
        assert "context.errors.append" in source_code, "Not adding errors to context"
        assert "traceback.format_exc()" in source_code, "Not logging traceback"


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
        from warden.pipeline.application.executors.pre_analysis_executor import (
            PreAnalysisExecutor,
        )

        executors = [AnalysisExecutor, CleaningExecutor, ClassificationExecutor, PreAnalysisExecutor]

        for executor_class in executors:
            assert hasattr(executor_class, "execute_async"), (
                f"{executor_class.__name__} missing execute_async method"
            )
            assert callable(getattr(executor_class, "execute_async")), (
                f"{executor_class.__name__}.execute_async is not callable"
            )
