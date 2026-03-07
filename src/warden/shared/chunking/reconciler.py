"""Finding reconciliation for chunk-based LLM analysis.

When a frame sends a CodeChunk to the LLM, the model reports line numbers
relative to what it saw.  If the chunk content was produced with
``_numbered()`` (line-prefixed strings such as ``"151: def foo():"``), the
LLM *should* echo back absolute line numbers.  Smaller models sometimes
ignore the prefix and count from 1 instead.

This reconciler handles both cases robustly:
- Absolute line already in [start_line, end_line] → accepted as-is.
- Relative line in [1, chunk_length] → shifted to absolute.
- Everything else → clamped to start_line (safe fallback).

It also resets finding IDs to use the absolute line so that
result_aggregator deduplication works correctly across chunks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from warden.shared.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from .models import CodeChunk

logger = get_logger(__name__)


def reconcile_findings(
    chunk: CodeChunk,
    findings: list[Any],
    frame_id: str,
) -> list[Any]:
    """Correct line numbers and IDs for *findings* that came from *chunk*.

    Works with both ``Finding`` dataclass instances and plain dicts.
    Mutates each item in-place and returns the same list.

    Skips reconciliation when ``chunk.chunk_type == "full"`` (the LLM
    saw the entire file, so reported lines are already absolute).
    """
    if chunk.chunk_type == "full" or chunk.total_chunks <= 1:
        return findings

    chunk_length = chunk.end_line - chunk.start_line + 1

    for finding in findings:
        raw_line = _get_line(finding)
        if raw_line is None:
            continue

        absolute = _resolve_line(raw_line, chunk.start_line, chunk.end_line, chunk_length)

        _set_line(finding, absolute)
        _set_location(finding, chunk.file_path, absolute)
        _reset_id(finding, frame_id, absolute)

        logger.debug(
            "finding_reconciled",
            chunk_index=chunk.chunk_index,
            raw_line=raw_line,
            absolute_line=absolute,
        )

    return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_line(raw: int, start: int, end: int, length: int) -> int:
    """Map a raw LLM-reported line to an absolute file line number."""
    if start <= raw <= end:
        # LLM respected the numbered prefix — already absolute
        return raw
    if 1 <= raw <= length:
        # LLM counted from 1 (relative) — shift to absolute
        return start + raw - 1
    # Out of range — fall back to chunk start
    return start


def _get_line(finding: Any) -> int | None:
    if isinstance(finding, dict):
        v = finding.get("line")
    else:
        v = getattr(finding, "line", None)
    return int(v) if v else None


def _set_line(finding: Any, line: int) -> None:
    if isinstance(finding, dict):
        finding["line"] = line
    else:
        try:
            finding.line = line
        except AttributeError:
            pass


def _set_location(finding: Any, file_path: str, line: int) -> None:
    loc = f"{file_path}:{line}"
    if isinstance(finding, dict):
        finding["location"] = loc
    else:
        try:
            finding.location = loc
        except AttributeError:
            pass


def _reset_id(finding: Any, frame_id: str, line: int) -> None:
    """Normalise the finding ID so deduplication is chunk-agnostic."""
    new_id = f"{frame_id}-llm-{line}"
    if isinstance(finding, dict):
        finding["id"] = new_id
    else:
        try:
            finding.id = new_id
        except AttributeError:
            pass
