"""
Unit tests for DataDependencyBuilder and DDGVisitor.

Covers:
- WriteNode detection for simple ``context.field = value`` assignments
- ReadNode detection for ``context.field`` access
- FP suppression: context._lock, context.__dunder__, context.metadata
- Dict subscript assignment (context.metadata["k"]=v) is not a WriteNode
- context.findings.append(x) → ReadNode, not WriteNode
- Conditional writes (inside if/try) → is_conditional=True
- Nested function scope tracking
- Multi-file build merging results
- Graceful handling of syntax errors and I/O errors
- init_fields extraction from PipelineContext
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from warden.analysis.application.data_dependency_builder import (
    PIPELINE_CTX_NAMES,
    DataDependencyBuilder,
    DDGVisitor,
    FP_FIELD_PATTERNS,
)
from warden.analysis.domain.data_dependency_graph import DataDependencyGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def visit_code(code: str, file_path: str = "test.py") -> DataDependencyGraph:
    """Parse *code* with DDGVisitor and return the accumulated DDG."""
    ddg = DataDependencyGraph()
    tree = ast.parse(textwrap.dedent(code))
    visitor = DDGVisitor(file_path=file_path, ddg=ddg)
    visitor.visit(tree)
    return ddg


# ---------------------------------------------------------------------------
# PIPELINE_CTX_NAMES configuration
# ---------------------------------------------------------------------------


class TestPipelineCtxNames:
    def test_contains_context(self) -> None:
        assert "context" in PIPELINE_CTX_NAMES

    def test_contains_ctx(self) -> None:
        assert "ctx" in PIPELINE_CTX_NAMES

    def test_contains_pipeline_context(self) -> None:
        assert "pipeline_context" in PIPELINE_CTX_NAMES

    def test_is_frozenset(self) -> None:
        assert isinstance(PIPELINE_CTX_NAMES, frozenset)


# ---------------------------------------------------------------------------
# Basic Write Detection
# ---------------------------------------------------------------------------


class TestWriteDetection:
    def test_simple_assignment_creates_write_node(self) -> None:
        ddg = visit_code("context.code_graph = CodeGraph()")
        assert "context.code_graph" in ddg.writes
        assert len(ddg.writes["context.code_graph"]) == 1

    def test_write_node_has_correct_field_name(self) -> None:
        ddg = visit_code("context.gap_report = GapReport()")
        node = ddg.writes["context.gap_report"][0]
        assert node.field_name == "context.gap_report"

    def test_write_node_has_correct_line_number(self) -> None:
        code = "x = 1\ncontext.code_graph = None\n"
        ddg = visit_code(code)
        node = ddg.writes["context.code_graph"][0]
        assert node.line_no == 2

    def test_write_node_has_correct_file_path(self) -> None:
        ddg = visit_code("context.code_graph = None", file_path="my/module.py")
        node = ddg.writes["context.code_graph"][0]
        assert node.file_path == "my/module.py"

    def test_write_node_tracks_enclosing_function(self) -> None:
        code = """
def populate(context):
    context.code_graph = CodeGraph()
"""
        ddg = visit_code(code)
        node = ddg.writes["context.code_graph"][0]
        assert node.func_name == "populate"

    def test_write_at_module_level_func_name(self) -> None:
        ddg = visit_code("context.code_graph = None")
        node = ddg.writes["context.code_graph"][0]
        assert node.func_name == "<module>"

    def test_write_with_ctx_alias(self) -> None:
        ddg = visit_code("ctx.code_graph = CodeGraph()")
        assert "ctx.code_graph" in ddg.writes

    def test_write_with_pipeline_context_alias(self) -> None:
        ddg = visit_code("pipeline_context.code_graph = CodeGraph()")
        assert "pipeline_context.code_graph" in ddg.writes

    def test_aug_assign_creates_write_node(self) -> None:
        ddg = visit_code("context.count += 1")
        assert "context.count" in ddg.writes

    def test_ann_assign_creates_write_node(self) -> None:
        ddg = visit_code("context.result: int = 42")
        assert "context.result" in ddg.writes

    def test_conditional_write_inside_if(self) -> None:
        code = """
if condition:
    context.code_graph = CodeGraph()
"""
        ddg = visit_code(code)
        node = ddg.writes["context.code_graph"][0]
        assert node.is_conditional is True

    def test_unconditional_write_outside_if(self) -> None:
        ddg = visit_code("context.code_graph = CodeGraph()")
        node = ddg.writes["context.code_graph"][0]
        assert node.is_conditional is False

    def test_conditional_write_inside_try(self) -> None:
        code = """
try:
    context.code_graph = build()
except Exception:
    pass
"""
        ddg = visit_code(code)
        node = ddg.writes["context.code_graph"][0]
        assert node.is_conditional is True

    def test_nested_function_scope_tracked(self) -> None:
        code = """
def outer(context):
    def inner():
        context.value = 1
    inner()
"""
        ddg = visit_code(code)
        node = ddg.writes["context.value"][0]
        assert node.func_name == "inner"


# ---------------------------------------------------------------------------
# Basic Read Detection
# ---------------------------------------------------------------------------


class TestReadDetection:
    def test_attribute_read_creates_read_node(self) -> None:
        ddg = visit_code("x = context.code_graph")
        assert "context.code_graph" in ddg.reads

    def test_read_node_has_correct_field_name(self) -> None:
        ddg = visit_code("x = context.code_graph")
        node = ddg.reads["context.code_graph"][0]
        assert node.field_name == "context.code_graph"

    def test_read_inside_condition(self) -> None:
        ddg = visit_code("if context.gap_report:\n    pass\n")
        assert "context.gap_report" in ddg.reads

    def test_chained_attribute_read_records_first_level_only(self) -> None:
        """context.findings.append(x) → ReadNode for context.findings, not context.findings.append"""
        ddg = visit_code("context.findings.append(item)")
        assert "context.findings" in ddg.reads
        # The chained attribute should not be recorded as a write
        assert "context.findings" not in ddg.writes

    def test_read_inside_function_call_arg(self) -> None:
        ddg = visit_code("process(context.quality_metrics)")
        assert "context.quality_metrics" in ddg.reads

    def test_read_func_name_tracked(self) -> None:
        code = """
def use_graph(context):
    return context.code_graph
"""
        ddg = visit_code(code)
        node = ddg.reads["context.code_graph"][0]
        assert node.func_name == "use_graph"


# ---------------------------------------------------------------------------
# False Positive Suppression
# ---------------------------------------------------------------------------


class TestFpSuppression:
    def test_lock_attribute_not_recorded(self) -> None:
        ddg = visit_code("context._lock = threading.Lock()")
        assert "context._lock" not in ddg.writes
        assert "context._lock" not in ddg.reads

    def test_lock_prefixed_field_suppressed_by_lock_pattern(self) -> None:
        """Fields starting with _lock are suppressed (threading internals)."""
        ddg = visit_code("context._lock_timeout = 30")
        assert "context._lock_timeout" not in ddg.writes

    def test_metadata_assignment_not_write_node(self) -> None:
        """context.metadata is in FP_FIELD_PATTERNS — the field itself is suppressed."""
        ddg = visit_code("context.metadata['key'] = 'value'")
        assert "context.metadata" not in ddg.writes

    def test_metadata_field_access_not_read_node(self) -> None:
        """context.metadata read also suppressed."""
        ddg = visit_code("x = context.metadata")
        assert "context.metadata" not in ddg.reads

    def test_dunder_attribute_not_recorded(self) -> None:
        ddg = visit_code("context.__class__")
        assert not any("__" in k for k in ddg.reads.keys())
        assert not any("__" in k for k in ddg.writes.keys())

    def test_fp_field_patterns_tuple(self) -> None:
        assert isinstance(FP_FIELD_PATTERNS, tuple)
        assert "_lock" in FP_FIELD_PATTERNS
        assert "__" in FP_FIELD_PATTERNS
        assert "metadata" in FP_FIELD_PATTERNS


# ---------------------------------------------------------------------------
# Multi-file Build
# ---------------------------------------------------------------------------


class TestMultiFileBuild:
    def test_two_files_merged_into_single_ddg(self, tmp_path: Path) -> None:
        file_a = tmp_path / "phase_a.py"
        file_a.write_text("context.code_graph = CodeGraph()\n")

        file_b = tmp_path / "phase_b.py"
        file_b.write_text("x = context.code_graph\n")

        builder = DataDependencyBuilder(tmp_path)
        ddg = builder.build([file_a, file_b])

        assert "context.code_graph" in ddg.writes
        assert "context.code_graph" in ddg.reads

    def test_dead_write_detected_across_files(self, tmp_path: Path) -> None:
        file_a = tmp_path / "writer.py"
        file_a.write_text("context.orphan_field = 42\n")

        file_b = tmp_path / "reader.py"
        file_b.write_text("x = context.other_field\n")

        builder = DataDependencyBuilder(tmp_path)
        ddg = builder.build([file_a, file_b])

        dead = ddg.dead_writes()
        assert "context.orphan_field" in dead

    def test_multiple_write_nodes_from_different_files(self, tmp_path: Path) -> None:
        file_a = tmp_path / "a.py"
        file_a.write_text("context.shared = 1\n")

        file_b = tmp_path / "b.py"
        file_b.write_text("context.shared = 2\n")

        builder = DataDependencyBuilder(tmp_path)
        ddg = builder.build([file_a, file_b])

        # Both writes collected
        assert len(ddg.writes["context.shared"]) == 2

    def test_empty_file_list_returns_empty_ddg(self, tmp_path: Path) -> None:
        builder = DataDependencyBuilder(tmp_path)
        ddg = builder.build([])
        assert ddg.all_fields() == set()


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_syntax_error_does_not_raise(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def broken(:\n    pass\n")

        builder = DataDependencyBuilder(tmp_path)
        # Should not raise any exception
        ddg = builder.build([bad_file])
        assert ddg.all_fields() == set()

    def test_missing_file_does_not_raise(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.py"

        builder = DataDependencyBuilder(tmp_path)
        ddg = builder.build([missing])
        assert ddg.all_fields() == set()

    def test_valid_file_processed_after_bad_file(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def broken(:\n    pass\n")

        good_file = tmp_path / "good.py"
        good_file.write_text("context.code_graph = CodeGraph()\n")

        builder = DataDependencyBuilder(tmp_path)
        ddg = builder.build([bad_file, good_file])

        assert "context.code_graph" in ddg.writes


# ---------------------------------------------------------------------------
# init_fields Extraction
# ---------------------------------------------------------------------------


class TestInitFieldsExtraction:
    def test_optional_fields_extracted_from_pipeline_context(self, tmp_path: Path) -> None:
        # Create a minimal PipelineContext-like file
        pc_dir = tmp_path / "pipeline" / "domain"
        pc_dir.mkdir(parents=True)
        pc_file = pc_dir / "pipeline_context.py"
        pc_file.write_text(
            textwrap.dedent(
                """
                from dataclasses import dataclass
                from typing import Any

                @dataclass
                class PipelineContext:
                    pipeline_id: str
                    code_graph: Any | None = None
                    gap_report: Any | None = None
                    required_field: str = ""
                """
            )
        )

        builder = DataDependencyBuilder(tmp_path)
        ddg = builder.build([])

        assert "context.code_graph" in ddg.init_fields
        assert "context.gap_report" in ddg.init_fields
        # Non-optional field should NOT be in init_fields
        assert "context.required_field" not in ddg.init_fields
        # Non-optional str field not included
        assert "context.pipeline_id" not in ddg.init_fields

    def test_no_pipeline_context_file_returns_empty_set(self, tmp_path: Path) -> None:
        builder = DataDependencyBuilder(tmp_path)
        ddg = builder.build([])
        assert ddg.init_fields == set()
