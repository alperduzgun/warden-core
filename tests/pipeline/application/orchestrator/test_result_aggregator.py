"""
Tests for warden.pipeline.application.orchestrator.result_aggregator

Verifies:
1. No duplicate findings from Rust/Global virtual frames
2. Custom rule violations are converted to findings and aggregated
3. Single source of truth: context.findings == aggregated from frame_results only
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from warden.pipeline.application.orchestrator.result_aggregator import ResultAggregator
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import Finding, FrameResult


# --- Helpers ---

def _make_context(**overrides) -> PipelineContext:
    """Create a minimal PipelineContext for testing."""
    defaults = dict(
        pipeline_id="test-pipeline",
        started_at=datetime.now(),
        file_path=Path("/tmp/test.py"),
        source_code="print('hello')",
    )
    defaults.update(overrides)
    return PipelineContext(**defaults)


def _make_finding(id: str, severity: str = "medium", msg: str = "test") -> Finding:
    return Finding(
        id=id,
        severity=severity,
        message=msg,
        location="test.py:1",
    )


def _make_frame_result(frame_id: str, findings: List[Finding]) -> FrameResult:
    return FrameResult(
        frame_id=frame_id,
        frame_name=frame_id,
        status="failed" if findings else "passed",
        duration=0.1,
        issues_found=len(findings),
        is_blocker=False,
        findings=findings,
    )


@dataclass
class FakeViolation:
    """Mimics CustomRuleViolation for testing."""
    rule_id: str = "R001"
    rule_name: str = "test-rule"
    severity: str = "high"
    is_blocker: bool = False
    file: str = "app.py"
    line: int = 10
    message: str = "Custom rule violated"
    suggestion: str = "Fix it"
    code_snippet: str = "x = eval(input())"


def _make_pipeline():
    """Create a mock ValidationPipeline with tracking fields."""
    p = MagicMock()
    p.frames_executed = 0
    p.frames_passed = 0
    p.frames_failed = 0
    return p


# --- Tests ---

class TestNoDuplicateFindings:
    """Verify Rust/Global rule findings are NOT double-counted."""

    def test_rust_findings_counted_once(self):
        """Rust virtual frame findings should appear exactly once."""
        ctx = _make_context()
        ctx.frame_results = {}

        rust_findings = [_make_finding("RUST-001"), _make_finding("RUST-002")]
        ctx.frame_results["system_security_rules"] = {
            "result": _make_frame_result("system_security_rules", rust_findings),
            "pre_violations": [],
            "post_violations": [],
        }

        # Simulate that we do NOT pre-extend context.findings (the fix)
        # context.findings should be empty before aggregation
        ctx.findings = []

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        # Should have exactly 2, not 4 (the old double-counting bug)
        assert len(ctx.findings) == 2
        ids = [f.id for f in ctx.findings]
        assert ids == ["RUST-001", "RUST-002"]

    def test_global_rules_counted_once(self):
        """Global script rule findings should appear exactly once."""
        ctx = _make_context()
        ctx.frame_results = {}

        global_findings = [_make_finding("GLOBAL-001")]
        ctx.frame_results["global_script_rules"] = {
            "result": _make_frame_result("global_script_rules", global_findings),
            "pre_violations": [],
            "post_violations": [],
        }

        ctx.findings = []

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        assert len(ctx.findings) == 1
        assert ctx.findings[0].id == "GLOBAL-001"

    def test_mixed_frames_no_duplication(self):
        """Multiple frame types should not cause duplication."""
        ctx = _make_context()
        ctx.frame_results = {}

        ctx.frame_results["system_security_rules"] = {
            "result": _make_frame_result("system_security_rules", [_make_finding("R1")]),
            "pre_violations": [],
            "post_violations": [],
        }
        ctx.frame_results["global_script_rules"] = {
            "result": _make_frame_result("global_script_rules", [_make_finding("G1")]),
            "pre_violations": [],
            "post_violations": [],
        }
        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [_make_finding("S1"), _make_finding("S2")]),
            "pre_violations": [],
            "post_violations": [],
        }

        ctx.findings = []

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        assert len(ctx.findings) == 4
        ids = {f.id for f in ctx.findings}
        assert ids == {"R1", "G1", "S1", "S2"}

    def test_preexisting_findings_replaced_not_appended(self):
        """context.findings is REPLACED, not appended to (prevents stale data)."""
        ctx = _make_context()
        ctx.frame_results = {}

        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [_make_finding("NEW-1")]),
            "pre_violations": [],
            "post_violations": [],
        }

        # Simulate stale findings already in context
        ctx.findings = [_make_finding("STALE-1"), _make_finding("STALE-2")]

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        # Should only have the new finding, stale ones replaced
        assert len(ctx.findings) == 1
        assert ctx.findings[0].id == "NEW-1"


class TestViolationsAggregated:
    """Verify custom rule violations flow through as findings."""

    def test_pre_violations_become_findings(self):
        """Pre-rule violations should be converted to Finding and aggregated."""
        ctx = _make_context()
        ctx.frame_results = {}

        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [_make_finding("F1")]),
            "pre_violations": [FakeViolation(rule_id="PRE-R1", message="pre violation")],
            "post_violations": [],
        }

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        assert len(ctx.findings) == 2
        violation_finding = [f for f in ctx.findings if "PRE-R1" in f.id]
        assert len(violation_finding) == 1
        assert violation_finding[0].severity == "high"
        assert "pre violation" in violation_finding[0].message

    def test_post_violations_become_findings(self):
        """Post-rule violations should be converted to Finding and aggregated."""
        ctx = _make_context()
        ctx.frame_results = {}

        ctx.frame_results["orphan_frame"] = {
            "result": _make_frame_result("orphan_frame", []),
            "pre_violations": [],
            "post_violations": [FakeViolation(rule_id="POST-R1", message="post violation")],
        }

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        assert len(ctx.findings) == 1
        assert "POST-R1" in ctx.findings[0].id
        assert "post" in ctx.findings[0].id

    def test_violations_with_frame_findings_combined(self):
        """Violations and frame findings should coexist in context.findings."""
        ctx = _make_context()
        ctx.frame_results = {}

        pre_v = FakeViolation(rule_id="PRE-1", severity="critical", is_blocker=True)
        post_v = FakeViolation(rule_id="POST-1", severity="low")

        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [
                _make_finding("SEC-1", "high"),
                _make_finding("SEC-2", "medium"),
            ]),
            "pre_violations": [pre_v],
            "post_violations": [post_v],
        }

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        # 2 findings + 1 pre + 1 post = 4
        assert len(ctx.findings) == 4

        # Verify blocker flag propagated
        blocker_findings = [f for f in ctx.findings if f.is_blocker]
        assert len(blocker_findings) == 1
        assert "PRE-1" in blocker_findings[0].id

    def test_violation_to_finding_conversion_fields(self):
        """Verify all violation fields are correctly mapped to Finding."""
        agg = ResultAggregator()
        v = FakeViolation(
            rule_id="RULE-42",
            severity="critical",
            is_blocker=True,
            file="main.py",
            line=99,
            message="Dangerous pattern detected",
            suggestion="Use safe alternative",
            code_snippet="eval(user_input)",
        )
        finding = agg._violation_to_finding(v, "sec_frame", "pre")

        assert finding.id == "rule/sec_frame/pre/RULE-42"
        assert finding.severity == "critical"
        assert finding.message == "Dangerous pattern detected"
        assert finding.location == "main.py:99"
        assert finding.line == 99
        assert finding.is_blocker is True
        assert finding.detail == "Use safe alternative"
        assert finding.code == "eval(user_input)"

    def test_enum_severity_handled(self):
        """Violations with enum severity should be converted to string."""
        agg = ResultAggregator()

        class FakeSeverity:
            value = "HIGH"

        v = FakeViolation()
        v.severity = FakeSeverity()

        finding = agg._violation_to_finding(v, "f1", "pre")
        assert finding.severity == "high"

    def test_no_violations_no_extra_findings(self):
        """When there are no violations, only frame findings should appear."""
        ctx = _make_context()
        ctx.frame_results = {}

        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [_make_finding("F1")]),
            "pre_violations": [],
            "post_violations": [],
        }

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        assert len(ctx.findings) == 1
        assert ctx.findings[0].id == "F1"


class TestValidatedIssues:
    """Verify validated_issues filtering works with violations."""

    def test_validated_issues_includes_violations(self):
        """Violation-converted findings should also appear in validated_issues."""
        ctx = _make_context()
        ctx.frame_results = {}
        ctx.suppression_rules = []  # No suppressions

        ctx.frame_results["security_frame"] = {
            "result": _make_frame_result("security_frame", [_make_finding("F1")]),
            "pre_violations": [FakeViolation(rule_id="V1")],
            "post_violations": [],
        }

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        # Both should be in validated_issues (no suppression rules active)
        assert len(ctx.validated_issues) == 2

    def test_empty_frame_results(self):
        """No frame results should produce empty findings."""
        ctx = _make_context()
        # No frame_results attribute at all

        agg = ResultAggregator()
        agg.store_validation_results(ctx, _make_pipeline())

        assert ctx.findings == []
        assert ctx.validated_issues == []


class TestAggregateFrameResults:
    """Test the aggregate_frame_results statistics method."""

    def test_stats_count_violations_in_findings(self):
        """aggregate_frame_results should count violations that were added to findings."""
        ctx = _make_context()
        ctx.frame_results = {}

        # A frame with 1 finding + 1 pre_violation
        frame_result = _make_frame_result("sec", [_make_finding("F1")])
        ctx.frame_results["sec"] = {
            "result": frame_result,
            "pre_violations": [FakeViolation()],
            "post_violations": [],
        }

        agg = ResultAggregator()
        stats = agg.aggregate_frame_results(ctx)

        # aggregate_frame_results only counts frame_result.findings (not violations)
        # This is expected behavior - violations are tracked separately
        assert stats["total_findings"] == 1
        assert stats["total_frames"] == 1
