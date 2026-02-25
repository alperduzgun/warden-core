"""
Unit tests for DDG false-positive filter behaviour.

Naming convention: tests that specifically verify suppressed false-positives
are named ``test_false_positive_*`` so the roadmap validation pattern finds them.

Covers:
- context.metadata assignment → false_positive_metadata_assignment
- Dunder attributes → false_positive_dunder_attribute
- Private _lock fields → false_positive_lock_field
- Chained attribute call (context.findings.append) → ReadNode, not WriteNode
- Non-context variables are never recorded
- Only the first attribute level is recorded for chained reads
"""

from __future__ import annotations

import ast
import textwrap

from warden.analysis.application.data_dependency_builder import DDGVisitor
from warden.analysis.domain.data_dependency_graph import DataDependencyGraph


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def visit_code(code: str, file_path: str = "test.py") -> DataDependencyGraph:
    ddg = DataDependencyGraph()
    tree = ast.parse(textwrap.dedent(code))
    visitor = DDGVisitor(file_path=file_path, ddg=ddg)
    visitor.visit(tree)
    return ddg


# ---------------------------------------------------------------------------
# False positive: metadata dict-item assignment
# ---------------------------------------------------------------------------


class TestFalsePositiveMetadataAssignment:
    def test_false_positive_metadata_assignment_no_write_node(self) -> None:
        """context.metadata['key'] = value must NOT produce a WriteNode.

        Reason: ``metadata`` is a generic dict, not a typed pipeline field.
        FP_FIELD_PATTERNS contains "metadata" to suppress this.
        """
        ddg = visit_code("context.metadata['key'] = 'value'")
        assert "context.metadata" not in ddg.writes, (
            "context.metadata dict-item assignment should be a false positive (no WriteNode)"
        )

    def test_false_positive_metadata_read_suppressed(self) -> None:
        """context.metadata read also suppressed — not a meaningful pipeline field."""
        ddg = visit_code("x = context.metadata")
        assert "context.metadata" not in ddg.reads, "context.metadata read should be suppressed as a false positive"

    def test_false_positive_metadata_subscript_read_in_condition(self) -> None:
        code = """
if context.metadata.get('key'):
    pass
"""
        ddg = visit_code(code)
        assert "context.metadata" not in ddg.reads


# ---------------------------------------------------------------------------
# False positive: dunder attributes
# ---------------------------------------------------------------------------


class TestFalsePositiveDunderAttribute:
    def test_false_positive_dunder_attribute_class_not_recorded(self) -> None:
        """context.__class__ must NOT produce a ReadNode — dunder is internal."""
        ddg = visit_code("x = context.__class__")
        dunder_reads = [k for k in ddg.reads if "__" in k]
        assert not dunder_reads, f"Dunder attribute should be false positive, got reads: {dunder_reads}"

    def test_false_positive_dunder_attribute_dict_not_recorded(self) -> None:
        ddg = visit_code("x = context.__dict__")
        dunder_reads = [k for k in ddg.reads if "__" in k]
        assert not dunder_reads

    def test_false_positive_dunder_write_suppressed(self) -> None:
        ddg = visit_code("context.__custom__ = None")
        dunder_writes = [k for k in ddg.writes if "__" in k]
        assert not dunder_writes, f"Dunder attribute write should be false positive, got writes: {dunder_writes}"


# ---------------------------------------------------------------------------
# False positive: lock and private fields
# ---------------------------------------------------------------------------


class TestFalsePositiveLockField:
    def test_false_positive_lock_field_not_in_writes(self) -> None:
        """context._lock = threading.Lock() must NOT produce a WriteNode."""
        ddg = visit_code("context._lock = threading.Lock()")
        assert "context._lock" not in ddg.writes, "context._lock should be a false positive (threading internal)"

    def test_false_positive_lock_field_not_in_reads(self) -> None:
        ddg = visit_code("x = context._lock")
        assert "context._lock" not in ddg.reads

    def test_false_positive_other_private_prefixed_lock(self) -> None:
        """Any field starting with _lock prefix should be suppressed."""
        ddg = visit_code("context._lock_timeout = 30")
        lock_writes = [k for k in ddg.writes if "_lock" in k]
        assert not lock_writes


# ---------------------------------------------------------------------------
# Chained attribute — ReadNode not WriteNode
# ---------------------------------------------------------------------------


class TestChainedAttributeIsReadNotWrite:
    def test_findings_append_is_read_not_write(self) -> None:
        """context.findings.append(x) is a *read* of context.findings, not a write."""
        ddg = visit_code("context.findings.append(item)")
        assert "context.findings" in ddg.reads, (
            "context.findings.append should generate a ReadNode for context.findings"
        )
        assert "context.findings" not in ddg.writes, "context.findings.append must NOT generate a WriteNode"

    def test_chained_method_call_read_only(self) -> None:
        ddg = visit_code("context.errors.extend([err])")
        assert "context.errors" in ddg.reads
        assert "context.errors" not in ddg.writes

    def test_chained_attribute_nested_access_read(self) -> None:
        """context.quality_metrics.hotspot_count — ReadNode for quality_metrics."""
        ddg = visit_code("x = context.quality_metrics.hotspot_count")
        assert "context.quality_metrics" in ddg.reads
        # The second-level attribute (.hotspot_count) should not appear as a field
        assert "context.quality_metrics.hotspot_count" not in ddg.reads

    def test_dict_key_access_is_read(self) -> None:
        ddg = visit_code("x = context.frame_results['SecurityFrame']")
        assert "context.frame_results" in ddg.reads


# ---------------------------------------------------------------------------
# Non-context variables — should never be recorded
# ---------------------------------------------------------------------------


class TestNonContextVariables:
    def test_other_variable_attribute_not_recorded(self) -> None:
        ddg = visit_code("other_obj.code_graph = CodeGraph()")
        assert "other_obj.code_graph" not in ddg.writes

    def test_self_attribute_not_recorded(self) -> None:
        code = """
class Foo:
    def setup(self):
        self.code_graph = CodeGraph()
"""
        ddg = visit_code(code)
        assert "self.code_graph" not in ddg.writes

    def test_result_attribute_not_recorded(self) -> None:
        ddg = visit_code("result.findings = []")
        assert "result.findings" not in ddg.writes

    def test_only_pipeline_ctx_names_recorded(self) -> None:
        code = """
context.real_field = 1
other.real_field = 2
self.real_field = 3
"""
        ddg = visit_code(code)
        # Only context.real_field should be in writes
        assert "context.real_field" in ddg.writes
        assert "other.real_field" not in ddg.writes
        assert "self.real_field" not in ddg.writes


# ---------------------------------------------------------------------------
# Edge: mixed real and FP in same function
# ---------------------------------------------------------------------------


class TestMixedRealAndFp:
    def test_real_writes_preserved_alongside_fp(self) -> None:
        code = """
def phase_setup(context):
    context._lock = threading.Lock()           # FP
    context.code_graph = CodeGraph()           # real write
    context.metadata['step'] = 'pre_analysis' # FP
    context.gap_report = GapReport()           # real write
"""
        ddg = visit_code(code)
        # Real writes present
        assert "context.code_graph" in ddg.writes
        assert "context.gap_report" in ddg.writes
        # FP fields absent
        assert "context._lock" not in ddg.writes
        assert "context.metadata" not in ddg.writes

    def test_fp_in_nested_conditional_still_suppressed(self) -> None:
        code = """
if condition:
    try:
        context._lock = threading.Lock()
    except Exception:
        pass
"""
        ddg = visit_code(code)
        assert "context._lock" not in ddg.writes
