"""
Tests for PipelineContext phase post-condition guarantees (#133).

Verifies:
1. PHASE_POST_CONDITIONS registry is complete and correct
2. assert_phase_complete detects violations (emits warnings, not hard failures)
3. assert_phase_complete passes when fields are properly populated
4. Executor source code calls assert_phase_complete at phase exit
"""

import warnings
from datetime import datetime
from pathlib import Path

import pytest

from warden.pipeline.domain.pipeline_context import (
    PHASE_POST_CONDITIONS,
    PipelineContext,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# PHASE_POST_CONDITIONS registry tests
# ---------------------------------------------------------------------------

class TestPhasePostConditionsRegistry:
    """Ensure the phase map covers all expected phases."""

    def test_registry_contains_all_core_phases(self):
        expected_phases = {
            "PRE_ANALYSIS",
            "TRIAGE",
            "ANALYSIS",
            "CLASSIFICATION",
            "VALIDATION",
            "FORTIFICATION",
            "CLEANING",
        }
        assert expected_phases == set(PHASE_POST_CONDITIONS.keys())

    def test_all_fields_exist_on_pipeline_context(self):
        """Every field in the registry must be an actual attribute of PipelineContext."""
        ctx = _make_context()
        for phase, fields in PHASE_POST_CONDITIONS.items():
            for field_name in fields:
                assert hasattr(ctx, field_name), (
                    f"PHASE_POST_CONDITIONS[{phase!r}] references non-existent "
                    f"field {field_name!r} on PipelineContext"
                )

    def test_registry_values_are_non_empty_lists(self):
        for phase, fields in PHASE_POST_CONDITIONS.items():
            assert isinstance(fields, list), f"Phase {phase} should map to a list"
            assert len(fields) > 0, f"Phase {phase} should have at least one post-condition field"


# ---------------------------------------------------------------------------
# assert_phase_complete: violation detection
# ---------------------------------------------------------------------------

class TestAssertPhaseCompleteViolations:
    """Test that violations are correctly detected and reported."""

    def test_pre_analysis_violation_when_project_context_is_none(self):
        ctx = _make_context()
        # project_context defaults to None -> violation expected
        violations = ctx.assert_phase_complete("PRE_ANALYSIS")
        assert "project_context" in violations

    def test_analysis_violation_when_quality_metrics_is_none(self):
        ctx = _make_context()
        violations = ctx.assert_phase_complete("ANALYSIS")
        assert "quality_metrics" in violations

    def test_classification_passes_with_default_empty_list(self):
        """selected_frames defaults to [] which is not None -> no violation."""
        ctx = _make_context()
        violations = ctx.assert_phase_complete("CLASSIFICATION")
        assert violations == []

    def test_validation_passes_with_default_empty_dict(self):
        """frame_results defaults to {} which is not None -> no violation."""
        ctx = _make_context()
        violations = ctx.assert_phase_complete("VALIDATION")
        assert violations == []

    def test_fortification_passes_with_defaults(self):
        """All fortification fields default to list/dict -> no violation."""
        ctx = _make_context()
        violations = ctx.assert_phase_complete("FORTIFICATION")
        assert violations == []

    def test_cleaning_passes_with_defaults(self):
        """All cleaning fields default to list -> no violation."""
        ctx = _make_context()
        violations = ctx.assert_phase_complete("CLEANING")
        assert violations == []


# ---------------------------------------------------------------------------
# assert_phase_complete: success paths
# ---------------------------------------------------------------------------

class TestAssertPhaseCompleteSuccess:
    """Test that populated fields pass validation."""

    def test_pre_analysis_passes_when_fields_populated(self):
        ctx = _make_context()
        ctx.project_context = {"project_type": "web", "framework": "django"}
        ctx.file_contexts = {"test.py": {"type": "source"}}
        violations = ctx.assert_phase_complete("PRE_ANALYSIS")
        assert violations == []

    def test_analysis_passes_when_quality_metrics_set(self):
        ctx = _make_context()
        # Use a mock-like object instead of importing full QualityMetrics
        ctx.quality_metrics = type("QM", (), {"overall_score": 7.5})()
        violations = ctx.assert_phase_complete("ANALYSIS")
        assert violations == []

    def test_unknown_phase_returns_empty(self):
        """Unknown phase IDs should not raise, just return empty violations."""
        ctx = _make_context()
        violations = ctx.assert_phase_complete("NONEXISTENT_PHASE")
        assert violations == []


# ---------------------------------------------------------------------------
# Warning behavior
# ---------------------------------------------------------------------------

class TestAssertPhaseCompleteWarnings:
    """Test that violations emit warnings but never raise."""

    def test_violation_emits_warning(self):
        ctx = _make_context()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ctx.assert_phase_complete("PRE_ANALYSIS")
            assert len(w) >= 1
            assert "post-condition violation" in str(w[0].message)

    def test_violation_appended_to_context_warnings(self):
        ctx = _make_context()
        ctx.assert_phase_complete("PRE_ANALYSIS")
        assert len(ctx.warnings) >= 1
        assert "PRE_ANALYSIS" in ctx.warnings[0]

    def test_no_warning_when_all_fields_populated(self):
        ctx = _make_context()
        ctx.project_context = {"some": "data"}
        ctx.file_contexts = {"f.py": {}}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ctx.assert_phase_complete("PRE_ANALYSIS")
            phase_warnings = [x for x in w if "post-condition" in str(x.message)]
            assert len(phase_warnings) == 0

    def test_pipeline_id_in_warning_message(self):
        ctx = _make_context(pipeline_id="my-test-id")
        ctx.assert_phase_complete("ANALYSIS")
        assert any("my-test-id" in w for w in ctx.warnings)


# ---------------------------------------------------------------------------
# Return value semantics
# ---------------------------------------------------------------------------

class TestAssertPhaseCompleteReturnValue:
    """Test the return value for programmatic inspection."""

    def test_returns_list_of_field_names(self):
        ctx = _make_context()
        violations = ctx.assert_phase_complete("PRE_ANALYSIS")
        assert isinstance(violations, list)
        # project_context is None by default
        assert "project_context" in violations

    def test_returns_empty_list_on_success(self):
        ctx = _make_context()
        # CLEANING fields all default to non-None (empty lists/dicts)
        violations = ctx.assert_phase_complete("CLEANING")
        assert violations == []

    def test_returns_empty_list_for_unknown_phase(self):
        ctx = _make_context()
        violations = ctx.assert_phase_complete("DOES_NOT_EXIST")
        assert violations == []


# ---------------------------------------------------------------------------
# Executor integration: source code contains assert_phase_complete calls
# ---------------------------------------------------------------------------

class TestExecutorPhaseAssertionCalls:
    """Verify that each executor calls assert_phase_complete at phase exit."""

    @pytest.mark.parametrize(
        "executor_path,phase_id",
        [
            ("src/warden/pipeline/application/executors/pre_analysis_executor.py", "PRE_ANALYSIS"),
            ("src/warden/pipeline/application/executors/analysis_executor.py", "ANALYSIS"),
            ("src/warden/pipeline/application/executors/classification_executor.py", "CLASSIFICATION"),
            ("src/warden/pipeline/application/executors/fortification_executor.py", "FORTIFICATION"),
            ("src/warden/pipeline/application/executors/cleaning_executor.py", "CLEANING"),
            ("src/warden/pipeline/application/orchestrator/frame_executor.py", "VALIDATION"),
        ],
    )
    def test_executor_calls_assert_phase_complete(self, executor_path, phase_id):
        source_path = Path(executor_path)
        with open(source_path) as f:
            source_code = f.read()

        expected_call = f'assert_phase_complete("{phase_id}")'
        assert expected_call in source_code, (
            f"{executor_path} does not contain {expected_call!r}. "
            f"Phase post-condition check missing for {phase_id}."
        )


# ---------------------------------------------------------------------------
# Module-level docstring documentation
# ---------------------------------------------------------------------------

class TestPhaseMapDocumentation:
    """Verify the phase map is documented in the module docstring."""

    def test_module_docstring_contains_phase_map(self):
        import warden.pipeline.domain.pipeline_context as mod

        docstring = mod.__doc__
        assert docstring is not None, "Module docstring is missing"
        assert "Phase Post-Condition Map" in docstring
        assert "PRE_ANALYSIS" in docstring
        assert "CLASSIFICATION" in docstring
        assert "VALIDATION" in docstring
        assert "FORTIFICATION" in docstring
        assert "CLEANING" in docstring

    def test_class_docstring_contains_phase_postconditions(self):
        docstring = PipelineContext.__doc__
        assert docstring is not None, "PipelineContext class docstring is missing"
        assert "Phase Post-Conditions" in docstring or "Post-Condition" in docstring
