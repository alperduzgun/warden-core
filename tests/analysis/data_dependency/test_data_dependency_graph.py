"""
Unit tests for DataDependencyGraph domain model.

Covers:
- WriteNode and ReadNode immutability (frozen dataclasses)
- DataDependencyGraph.dead_writes()
- DataDependencyGraph.missing_writes()
- DataDependencyGraph.never_populated()
- DataDependencyGraph.all_fields()
- DataDependencyGraph.stats()
- Edge cases: fields that are both written and read are NOT dead writes
- Edge cases: init_fields that are written are NOT never_populated
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from warden.analysis.domain.data_dependency_graph import (
    DataDependencyGraph,
    ReadNode,
    WriteNode,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_write(field: str, file: str = "foo.py", line: int = 1, func: str = "f", cond: bool = False) -> WriteNode:
    return WriteNode(field_name=field, file_path=file, line_no=line, func_name=func, is_conditional=cond)


def make_read(field: str, file: str = "bar.py", line: int = 1, func: str = "g") -> ReadNode:
    return ReadNode(field_name=field, file_path=file, line_no=line, func_name=func)


def empty_ddg() -> DataDependencyGraph:
    return DataDependencyGraph()


def ddg_with(
    writes: dict[str, list[WriteNode]] | None = None,
    reads: dict[str, list[ReadNode]] | None = None,
    init_fields: set[str] | None = None,
) -> DataDependencyGraph:
    ddg = DataDependencyGraph()
    if writes:
        ddg.writes.update(writes)
    if reads:
        ddg.reads.update(reads)
    if init_fields:
        ddg.init_fields = init_fields
    return ddg


# ---------------------------------------------------------------------------
# WriteNode — immutability
# ---------------------------------------------------------------------------


class TestWriteNodeImmutability:
    def test_frozen_cannot_set_field(self) -> None:
        node = make_write("context.foo")
        with pytest.raises((AttributeError, TypeError)):
            node.field_name = "context.bar"  # type: ignore[misc]

    def test_frozen_cannot_delete_field(self) -> None:
        node = make_write("context.foo")
        with pytest.raises((AttributeError, TypeError)):
            del node.field_name  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        a = make_write("context.x", line=5)
        b = make_write("context.x", line=5)
        assert a == b

    def test_hashable(self) -> None:
        node = make_write("context.x")
        s = {node}
        assert node in s

    def test_conditional_flag_stored(self) -> None:
        node = make_write("context.x", cond=True)
        assert node.is_conditional is True

    def test_non_conditional_flag_stored(self) -> None:
        node = make_write("context.x", cond=False)
        assert node.is_conditional is False


# ---------------------------------------------------------------------------
# ReadNode — immutability
# ---------------------------------------------------------------------------


class TestReadNodeImmutability:
    def test_frozen_cannot_set_field(self) -> None:
        node = make_read("context.foo")
        with pytest.raises((AttributeError, TypeError)):
            node.field_name = "context.bar"  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        a = make_read("context.x", line=3)
        b = make_read("context.x", line=3)
        assert a == b

    def test_hashable(self) -> None:
        node = make_read("context.x")
        s = {node}
        assert node in s


# ---------------------------------------------------------------------------
# DataDependencyGraph.dead_writes
# ---------------------------------------------------------------------------


class TestDeadWrites:
    def test_write_only_is_dead(self) -> None:
        ddg = ddg_with(writes={"context.foo": [make_write("context.foo")]})
        result = ddg.dead_writes()
        assert "context.foo" in result
        assert len(result["context.foo"]) == 1

    def test_field_with_read_is_not_dead(self) -> None:
        ddg = ddg_with(
            writes={"context.foo": [make_write("context.foo")]},
            reads={"context.foo": [make_read("context.foo")]},
        )
        result = ddg.dead_writes()
        assert "context.foo" not in result

    def test_read_only_field_not_in_dead_writes(self) -> None:
        ddg = ddg_with(reads={"context.bar": [make_read("context.bar")]})
        result = ddg.dead_writes()
        assert "context.bar" not in result

    def test_empty_graph_returns_empty(self) -> None:
        ddg = empty_ddg()
        assert ddg.dead_writes() == {}

    def test_multiple_dead_writes_returned(self) -> None:
        ddg = ddg_with(
            writes={
                "context.a": [make_write("context.a")],
                "context.b": [make_write("context.b")],
            }
        )
        result = ddg.dead_writes()
        assert set(result.keys()) == {"context.a", "context.b"}

    def test_mixed_dead_and_live_writes(self) -> None:
        ddg = ddg_with(
            writes={
                "context.dead": [make_write("context.dead")],
                "context.live": [make_write("context.live")],
            },
            reads={"context.live": [make_read("context.live")]},
        )
        result = ddg.dead_writes()
        assert "context.dead" in result
        assert "context.live" not in result

    def test_multiple_write_nodes_preserved(self) -> None:
        w1 = make_write("context.x", line=1)
        w2 = make_write("context.x", line=5, cond=True)
        ddg = ddg_with(writes={"context.x": [w1, w2]})
        result = ddg.dead_writes()
        assert len(result["context.x"]) == 2


# ---------------------------------------------------------------------------
# DataDependencyGraph.missing_writes
# ---------------------------------------------------------------------------


class TestMissingWrites:
    def test_read_without_write_is_missing(self) -> None:
        ddg = ddg_with(reads={"context.missing": [make_read("context.missing")]})
        result = ddg.missing_writes()
        assert "context.missing" in result

    def test_read_with_write_is_not_missing(self) -> None:
        ddg = ddg_with(
            writes={"context.present": [make_write("context.present")]},
            reads={"context.present": [make_read("context.present")]},
        )
        result = ddg.missing_writes()
        assert "context.present" not in result

    def test_write_only_not_in_missing_writes(self) -> None:
        ddg = ddg_with(writes={"context.x": [make_write("context.x")]})
        result = ddg.missing_writes()
        assert "context.x" not in result

    def test_empty_graph_returns_empty(self) -> None:
        assert empty_ddg().missing_writes() == {}

    def test_multiple_read_nodes_preserved(self) -> None:
        r1 = make_read("context.x", line=1)
        r2 = make_read("context.x", line=8)
        ddg = ddg_with(reads={"context.x": [r1, r2]})
        result = ddg.missing_writes()
        assert len(result["context.x"]) == 2


# ---------------------------------------------------------------------------
# DataDependencyGraph.never_populated
# ---------------------------------------------------------------------------


class TestNeverPopulated:
    def test_declared_but_never_written_is_never_populated(self) -> None:
        ddg = ddg_with(init_fields={"context.code_graph"})
        result = ddg.never_populated()
        assert "context.code_graph" in result

    def test_declared_and_written_not_in_never_populated(self) -> None:
        ddg = ddg_with(
            writes={"context.code_graph": [make_write("context.code_graph")]},
            init_fields={"context.code_graph"},
        )
        result = ddg.never_populated()
        assert "context.code_graph" not in result

    def test_not_in_init_fields_not_returned(self) -> None:
        # A field that is read but was not declared as init_field
        ddg = ddg_with(reads={"context.runtime": [make_read("context.runtime")]})
        result = ddg.never_populated()
        assert "context.runtime" not in result

    def test_empty_init_fields_returns_empty(self) -> None:
        ddg = ddg_with(writes={"context.x": [make_write("context.x")]})
        assert ddg.never_populated() == set()

    def test_multiple_never_populated(self) -> None:
        ddg = ddg_with(init_fields={"context.a", "context.b", "context.c"})
        result = ddg.never_populated()
        assert result == {"context.a", "context.b", "context.c"}

    def test_partial_declared_fields(self) -> None:
        ddg = ddg_with(
            writes={"context.a": [make_write("context.a")]},
            init_fields={"context.a", "context.b"},
        )
        result = ddg.never_populated()
        assert "context.a" not in result
        assert "context.b" in result


# ---------------------------------------------------------------------------
# DataDependencyGraph.all_fields
# ---------------------------------------------------------------------------


class TestAllFields:
    def test_union_of_writes_and_reads(self) -> None:
        ddg = ddg_with(
            writes={"context.a": [make_write("context.a")]},
            reads={"context.b": [make_read("context.b")]},
        )
        assert ddg.all_fields() == {"context.a", "context.b"}

    def test_shared_field_appears_once(self) -> None:
        ddg = ddg_with(
            writes={"context.x": [make_write("context.x")]},
            reads={"context.x": [make_read("context.x")]},
        )
        assert ddg.all_fields() == {"context.x"}

    def test_empty_graph(self) -> None:
        assert empty_ddg().all_fields() == set()

    def test_writes_only(self) -> None:
        ddg = ddg_with(writes={"context.w": [make_write("context.w")]})
        assert ddg.all_fields() == {"context.w"}

    def test_reads_only(self) -> None:
        ddg = ddg_with(reads={"context.r": [make_read("context.r")]})
        assert ddg.all_fields() == {"context.r"}


# ---------------------------------------------------------------------------
# DataDependencyGraph.stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats_keys_present(self) -> None:
        stats = empty_ddg().stats()
        expected_keys = {
            "total_fields",
            "write_fields",
            "read_fields",
            "init_fields",
            "dead_write_count",
            "missing_write_count",
            "never_populated_count",
            "dead_write_fields",
            "missing_write_fields",
            "never_populated_fields",
        }
        assert set(stats.keys()) == expected_keys

    def test_empty_graph_all_zeros(self) -> None:
        stats = empty_ddg().stats()
        assert stats["total_fields"] == 0
        assert stats["dead_write_count"] == 0
        assert stats["missing_write_count"] == 0
        assert stats["never_populated_count"] == 0

    def test_stats_with_data(self) -> None:
        ddg = ddg_with(
            writes={
                "context.dead": [make_write("context.dead")],
                "context.live": [make_write("context.live")],
            },
            reads={
                "context.live": [make_read("context.live")],
                "context.missing": [make_read("context.missing")],
            },
            init_fields={"context.never"},
        )
        stats = ddg.stats()
        assert stats["dead_write_count"] == 1
        assert stats["missing_write_count"] == 1
        assert stats["never_populated_count"] == 1
        assert "context.dead" in stats["dead_write_fields"]
        assert "context.missing" in stats["missing_write_fields"]
        assert "context.never" in stats["never_populated_fields"]

    def test_stats_fields_are_sorted(self) -> None:
        ddg = ddg_with(
            writes={
                "context.z": [make_write("context.z")],
                "context.a": [make_write("context.a")],
            },
        )
        stats = ddg.stats()
        dead = stats["dead_write_fields"]
        assert dead == sorted(dead)
