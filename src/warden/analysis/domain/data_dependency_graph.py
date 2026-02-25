"""
DataDependencyGraph — domain model for pipeline context field data flow.

Tracks which PipelineContext fields are written (WriteNode) and read (ReadNode)
across the codebase. Used by DeadDataFrame to detect DEAD_WRITE, MISSING_WRITE,
and NEVER_POPULATED gaps in the data flow contracts.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WriteNode:
    """Represents a context field write operation detected in AST.

    Attributes:
        field_name: Qualified field name, e.g. ``"context.code_graph"``.
        file_path: Source file containing the write, e.g. ``"pre_analysis_phase.py"``.
        line_no: 1-based line number of the assignment.
        func_name: Name of the enclosing function or method.
        is_conditional: ``True`` when the assignment is inside an ``if`` or
            ``try`` block, meaning it may not always execute.
    """

    field_name: str
    file_path: str
    line_no: int
    func_name: str
    is_conditional: bool


@dataclass(frozen=True)
class ReadNode:
    """Represents a context field read operation detected in AST.

    Attributes:
        field_name: Qualified field name, e.g. ``"context.code_graph"``.
        file_path: Source file containing the read.
        line_no: 1-based line number of the attribute access.
        func_name: Name of the enclosing function or method.
    """

    field_name: str
    file_path: str
    line_no: int
    func_name: str


@dataclass
class DataDependencyGraph:
    """Graph of data dependencies between pipeline context fields.

    Tracks which fields are written (WriteNode) and read (ReadNode) across the
    codebase.  Used by ``DeadDataFrame`` to detect:

    * **DEAD_WRITE** — field is written but never read anywhere.
    * **MISSING_WRITE** — field is read but was never written anywhere.
    * **NEVER_POPULATED** — Optional field declared in ``PipelineContext`` but
      neither written nor read (purely dead declaration).

    Attributes:
        writes: Mapping from field_name to list of WriteNode.
        reads: Mapping from field_name to list of ReadNode.
        init_fields: Set of field names declared in PipelineContext dataclass
            (e.g. ``"context.code_graph"``).  Used for NEVER_POPULATED detection.
    """

    writes: defaultdict[str, list[WriteNode]] = field(default_factory=lambda: defaultdict(list))
    reads: defaultdict[str, list[ReadNode]] = field(default_factory=lambda: defaultdict(list))
    init_fields: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------
    # Gap-detection queries
    # ------------------------------------------------------------------

    def dead_writes(self) -> dict[str, list[WriteNode]]:
        """Return fields that are written but never read (DEAD_WRITE gaps).

        A field is a dead write when at least one WriteNode exists for it but
        **zero** ReadNodes exist across the entire graph.

        Returns:
            Mapping of field_name → list[WriteNode] for dead-write fields.
        """
        result: dict[str, list[WriteNode]] = {}
        for field_name, write_nodes in self.writes.items():
            if write_nodes and not self.reads[field_name]:
                result[field_name] = list(write_nodes)
        return result

    def missing_writes(self) -> dict[str, list[ReadNode]]:
        """Return fields that are read but never written (MISSING_WRITE gaps).

        A field has a missing write when at least one ReadNode exists but
        **zero** WriteNodes exist.  This signals a potential runtime
        ``AttributeError`` or stale-None access.

        Returns:
            Mapping of field_name → list[ReadNode] for fields with no write.
        """
        result: dict[str, list[ReadNode]] = {}
        for field_name, read_nodes in self.reads.items():
            if read_nodes and not self.writes[field_name]:
                result[field_name] = list(read_nodes)
        return result

    def never_populated(self) -> set[str]:
        """Return Optional fields declared in ``init_fields`` but never written.

        These fields are declared in the ``PipelineContext`` dataclass (typically
        with ``None`` as default) but no code ever assigns to them, making them
        permanently ``None`` throughout the pipeline.

        Returns:
            Set of field names that are declared but never written.
        """
        return {field_name for field_name in self.init_fields if not self.writes[field_name]}

    def all_fields(self) -> set[str]:
        """Return the union of all field names seen in writes or reads.

        Returns:
            Set of all unique field names observed in the graph.
        """
        return set(self.writes.keys()) | set(self.reads.keys())

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return summary statistics suitable for JSON serialization.

        Returns:
            Dictionary with counts for total fields, writes, reads, and gap
            categories.
        """
        dead = self.dead_writes()
        missing = self.missing_writes()
        never_pop = self.never_populated()
        return {
            "total_fields": len(self.all_fields()),
            "write_fields": len(self.writes),
            "read_fields": len(self.reads),
            "init_fields": len(self.init_fields),
            "dead_write_count": len(dead),
            "missing_write_count": len(missing),
            "never_populated_count": len(never_pop),
            "dead_write_fields": sorted(dead.keys()),
            "missing_write_fields": sorted(missing.keys()),
            "never_populated_fields": sorted(never_pop),
        }
