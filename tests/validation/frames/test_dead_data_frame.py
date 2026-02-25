"""Unit tests for DeadDataFrame."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from warden.analysis.domain.data_dependency_graph import (
    DataDependencyGraph,
    ReadNode,
    WriteNode,
)
from warden.validation.domain.frame import CodeFile
from warden.validation.domain.mixins import DataFlowAware
from warden.validation.frames.dead_data.dead_data_frame import DeadDataFrame


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_code_file(path: str = "src/phase.py", content: str = "# empty") -> CodeFile:
    return CodeFile(path=path, content=content, language="python")


def _make_write(field_name: str, file_path: str = "src/phase.py", line_no: int = 10) -> WriteNode:
    return WriteNode(
        field_name=field_name,
        file_path=file_path,
        line_no=line_no,
        func_name="run",
        is_conditional=False,
    )


def _make_read(field_name: str, file_path: str = "src/consumer.py", line_no: int = 20) -> ReadNode:
    return ReadNode(
        field_name=field_name,
        file_path=file_path,
        line_no=line_no,
        func_name="consume",
    )


def _ddg_with(
    writes: dict[str, list[WriteNode]] | None = None,
    reads: dict[str, list[ReadNode]] | None = None,
    init_fields: set[str] | None = None,
) -> DataDependencyGraph:
    """Build a DataDependencyGraph with the given nodes."""
    ddg = DataDependencyGraph()
    if writes:
        for field, nodes in writes.items():
            ddg.writes[field].extend(nodes)
    if reads:
        for field, nodes in reads.items():
            ddg.reads[field].extend(nodes)
    if init_fields:
        ddg.init_fields = init_fields
    return ddg


def _run(coro) -> Any:
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Test: Frame identity
# ---------------------------------------------------------------------------


class TestFrameIdentity:
    """Tests for frame metadata."""

    def test_frame_id(self):
        frame = DeadDataFrame()
        assert frame.frame_id == "dead_data"

    def test_is_not_blocker(self):
        frame = DeadDataFrame()
        assert frame.is_blocker is False

    def test_is_data_flow_aware(self):
        frame = DeadDataFrame()
        assert isinstance(frame, DataFlowAware)

    def test_name(self):
        frame = DeadDataFrame()
        assert frame.name == "Dead Data Detector"


# ---------------------------------------------------------------------------
# Test: Graceful skip when DDG not injected
# ---------------------------------------------------------------------------


class TestGracefulSkip:
    """Tests for skip behaviour when DDG is not available."""

    def test_graceful_skip_when_no_ddg(self):
        frame = DeadDataFrame()
        result = _run(frame.execute_async(_make_code_file()))
        assert result.status == "passed"
        assert result.issues_found == 0
        assert result.findings == []
        assert result.metadata is not None
        assert result.metadata.get("skipped") is True
        assert result.metadata.get("reason") == "DDG not injected"


# ---------------------------------------------------------------------------
# Test: DEAD_WRITE detection
# ---------------------------------------------------------------------------


class TestDeadWriteDetection:
    """Tests for DEAD_WRITE gap detection."""

    def test_dead_write_detected(self):
        """A field written but never read produces a DEAD_WRITE finding."""
        ddg = _ddg_with(
            writes={"context.unused_report": [_make_write("context.unused_report")]},
            reads={},
        )
        frame = DeadDataFrame()
        frame.set_data_dependency_graph(ddg)
        result = _run(frame.execute_async(_make_code_file()))

        assert result.status == "failed"
        assert result.issues_found == 1
        finding = result.findings[0]
        assert "DEAD-WRITE" in finding.id
        assert finding.severity == "medium"

    def test_read_and_write_no_dead_write(self):
        """A field both written and read does NOT produce a DEAD_WRITE."""
        ddg = _ddg_with(
            writes={"context.result": [_make_write("context.result")]},
            reads={"context.result": [_make_read("context.result")]},
        )
        frame = DeadDataFrame()
        frame.set_data_dependency_graph(ddg)
        result = _run(frame.execute_async(_make_code_file()))

        dead_write_findings = [f for f in result.findings if "DEAD-WRITE" in f.id]
        assert len(dead_write_findings) == 0


# ---------------------------------------------------------------------------
# Test: MISSING_WRITE detection
# ---------------------------------------------------------------------------


class TestMissingWriteDetection:
    """Tests for MISSING_WRITE gap detection."""

    def test_missing_write_detected(self):
        """A field read but never written produces a MISSING_WRITE finding."""
        ddg = _ddg_with(
            writes={},
            reads={"context.code_graph": [_make_read("context.code_graph")]},
        )
        frame = DeadDataFrame()
        frame.set_data_dependency_graph(ddg)
        result = _run(frame.execute_async(_make_code_file()))

        assert result.status == "failed"
        assert result.issues_found == 1
        finding = result.findings[0]
        assert "MISSING-WRITE" in finding.id
        assert finding.severity == "high"

    def test_missing_write_severity_high(self):
        """MISSING_WRITE findings have severity 'high'."""
        ddg = _ddg_with(
            reads={"context.taint_paths": [_make_read("context.taint_paths")]},
        )
        frame = DeadDataFrame()
        frame.set_data_dependency_graph(ddg)
        result = _run(frame.execute_async(_make_code_file()))

        assert any(f.severity == "high" for f in result.findings)


# ---------------------------------------------------------------------------
# Test: NEVER_POPULATED detection
# ---------------------------------------------------------------------------


class TestNeverPopulatedDetection:
    """Tests for NEVER_POPULATED gap detection."""

    def test_never_populated_detected(self):
        """A field in init_fields with no write produces a NEVER_POPULATED finding."""
        ddg = _ddg_with(
            init_fields={"context.chain_validation"},
            writes={},
        )
        frame = DeadDataFrame()
        frame.set_data_dependency_graph(ddg)
        result = _run(frame.execute_async(_make_code_file()))

        assert result.status == "failed"
        assert result.issues_found == 1
        finding = result.findings[0]
        assert "NEVER-POPULATED" in finding.id
        assert finding.severity == "medium"

    def test_init_field_with_write_not_never_populated(self):
        """A field in init_fields that IS written is NOT flagged as NEVER_POPULATED."""
        ddg = _ddg_with(
            init_fields={"context.code_graph"},
            writes={"context.code_graph": [_make_write("context.code_graph")]},
        )
        frame = DeadDataFrame()
        frame.set_data_dependency_graph(ddg)
        result = _run(frame.execute_async(_make_code_file()))

        never_populated = [f for f in result.findings if "NEVER-POPULATED" in f.id]
        assert len(never_populated) == 0


# ---------------------------------------------------------------------------
# Test: Only runs once (project-wide guard)
# ---------------------------------------------------------------------------


class TestRunsOnce:
    """Tests for the per-project analysis guard."""

    def test_only_runs_once(self):
        """
        When called with 2 different code files, analysis only runs on the first.
        Second call returns skipped=True with reason 'already_analyzed'.
        """
        ddg = _ddg_with(
            writes={"context.report": [_make_write("context.report")]},
        )
        frame = DeadDataFrame()
        frame.set_data_dependency_graph(ddg)

        file1 = _make_code_file("src/phase_a.py")
        file2 = _make_code_file("src/phase_b.py")

        result1 = _run(frame.execute_async(file1))
        result2 = _run(frame.execute_async(file2))

        # First call: actual analysis (no DDG reads → DEAD_WRITE)
        assert result1.metadata is not None
        assert result1.metadata.get("skipped") is not True

        # Second call: skipped because already analyzed
        assert result2.metadata is not None
        assert result2.metadata.get("skipped") is True
        assert result2.metadata.get("reason") == "already_analyzed"
        assert result2.issues_found == 0


# ---------------------------------------------------------------------------
# Test: Finding format
# ---------------------------------------------------------------------------


class TestFindingFormat:
    """Tests for the standardized finding dict format."""

    def test_finding_format(self):
        """Finding objects contain the required fields."""
        ddg = _ddg_with(
            writes={"context.orphan_field": [_make_write("context.orphan_field")]},
        )
        frame = DeadDataFrame()
        frame.set_data_dependency_graph(ddg)
        result = _run(frame.execute_async(_make_code_file()))

        assert len(result.findings) == 1
        finding = result.findings[0]

        # Required Finding fields
        assert finding.id
        assert finding.severity in ("critical", "high", "medium", "low")
        assert finding.message
        assert finding.location

    def test_finding_contains_gap_type_in_id(self):
        """Finding ID encodes the gap type."""
        ddg = _ddg_with(
            writes={"context.orphan": [_make_write("context.orphan")]},
        )
        frame = DeadDataFrame()
        frame.set_data_dependency_graph(ddg)
        result = _run(frame.execute_async(_make_code_file()))

        assert len(result.findings) == 1
        assert "DEAD-WRITE" in result.findings[0].id

    def test_finding_id_prefix_contract(self):
        """All finding IDs start with CONTRACT-."""
        ddg = _ddg_with(
            writes={"context.x": [_make_write("context.x")]},
            reads={"context.y": [_make_read("context.y")]},
            init_fields={"context.z"},
        )
        frame = DeadDataFrame()
        frame.set_data_dependency_graph(ddg)
        result = _run(frame.execute_async(_make_code_file()))

        for f in result.findings:
            assert f.id.startswith("CONTRACT-"), f"Unexpected id: {f.id}"


# ---------------------------------------------------------------------------
# Test: Multiple gap types in one run
# ---------------------------------------------------------------------------


class TestMultipleGapTypes:
    """Tests for combined gap detection."""

    def test_all_three_gap_types_detected(self):
        """Frame detects all three gap types in a single pass."""
        ddg = _ddg_with(
            writes={"context.dead": [_make_write("context.dead")]},
            reads={"context.unwritten": [_make_read("context.unwritten")]},
            init_fields={"context.never_set"},
        )
        frame = DeadDataFrame()
        frame.set_data_dependency_graph(ddg)
        result = _run(frame.execute_async(_make_code_file()))

        gap_types_in_ids = {f.id.split("-")[1] for f in result.findings}
        assert "DEAD" in gap_types_in_ids
        assert "MISSING" in gap_types_in_ids
        assert "NEVER" in gap_types_in_ids

    def test_clean_ddg_passes(self):
        """A balanced DDG (writes == reads) produces no findings."""
        ddg = _ddg_with(
            writes={"context.result": [_make_write("context.result")]},
            reads={"context.result": [_make_read("context.result")]},
        )
        frame = DeadDataFrame()
        frame.set_data_dependency_graph(ddg)
        result = _run(frame.execute_async(_make_code_file()))

        assert result.status == "passed"
        assert result.issues_found == 0
