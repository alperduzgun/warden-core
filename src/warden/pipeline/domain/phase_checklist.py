"""
Phase Checklist Model.

Tracks the status and timing of each pipeline phase for real-time
CLI progress display.  The checklist is populated by the pipeline
runner and consumed by the CLI's Rich Live display.

Phase lifecycle:
    PENDING  -> RUNNING -> DONE | FAILED | SKIPPED

Each item records wall-clock start/end timestamps so the CLI can
render elapsed time while a phase is active and total duration once
it completes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class PhaseStatus(str, Enum):
    """Execution status of an individual pipeline phase."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


# Canonical display order of pipeline phases.
# The keys match the labels used in ``PipelinePhaseRunner.execute_all_phases``.
PIPELINE_PHASES: list[str] = [
    "Pre-Analysis",
    "Triage",
    "Analysis",
    "Classification",
    "Validation",
    "Verification",
    "Fortification",
    "Cleaning",
]


@dataclass
class PhaseChecklistItem:
    """A single row in the phase checklist.

    Attributes:
        name: Human-readable phase name (e.g. "Pre-Analysis").
        status: Current phase execution status.
        start_time: Monotonic timestamp when the phase started
                    (``time.monotonic()``), or ``None`` if not yet started.
        end_time: Monotonic timestamp when the phase ended, or ``None``
                  if still running or not yet started.
    """

    name: str
    status: PhaseStatus = PhaseStatus.PENDING
    start_time: float | None = None
    end_time: float | None = None

    # ------------------------------------------------------------------ #
    # Convenience helpers
    # ------------------------------------------------------------------ #

    @property
    def elapsed(self) -> float | None:
        """Elapsed wall-clock seconds.

        * While running: seconds since start.
        * After completion: total duration.
        * Before start: ``None``.
        """
        if self.start_time is None:
            return None
        end = self.end_time if self.end_time is not None else time.monotonic()
        return end - self.start_time

    @property
    def elapsed_str(self) -> str:
        """Human-friendly elapsed string (e.g. ``"12s"``, ``"1m 3s"``)."""
        secs = self.elapsed
        if secs is None:
            return ""
        if secs < 60:
            return f"{secs:.0f}s"
        minutes = int(secs // 60)
        remainder = int(secs % 60)
        return f"{minutes}m {remainder}s"

    def mark_running(self) -> None:
        """Transition to RUNNING and record start time."""
        self.status = PhaseStatus.RUNNING
        self.start_time = time.monotonic()

    def mark_done(self) -> None:
        """Transition to DONE and record end time."""
        self.status = PhaseStatus.DONE
        self.end_time = time.monotonic()

    def mark_failed(self) -> None:
        """Transition to FAILED and record end time."""
        self.status = PhaseStatus.FAILED
        self.end_time = time.monotonic()

    def mark_skipped(self) -> None:
        """Transition to SKIPPED (no timing recorded)."""
        self.status = PhaseStatus.SKIPPED


@dataclass
class PhaseChecklist:
    """Ordered collection of ``PhaseChecklistItem`` objects.

    The checklist is initialised once at scan start and mutated
    in-place as the pipeline progresses.  The CLI reads it on every
    ``Live.update()`` tick to render the current state.
    """

    items: list[PhaseChecklistItem] = field(default_factory=list)

    # -- Factory -------------------------------------------------------- #

    @classmethod
    def from_defaults(cls) -> PhaseChecklist:
        """Create a checklist pre-populated with all canonical phases."""
        return cls(items=[PhaseChecklistItem(name=name) for name in PIPELINE_PHASES])

    # -- Lookup --------------------------------------------------------- #

    def get(self, name: str) -> PhaseChecklistItem | None:
        """Return the item matching *name* (case-insensitive)."""
        key = name.strip().lower()
        for item in self.items:
            if item.name.lower() == key:
                return item
        return None

    # -- Bulk state helpers --------------------------------------------- #

    def mark_phase_running(self, name: str) -> None:
        """Mark the named phase as RUNNING."""
        item = self.get(name)
        if item and item.status == PhaseStatus.PENDING:
            item.mark_running()

    def mark_phase_done(self, name: str) -> None:
        """Mark the named phase as DONE."""
        item = self.get(name)
        if item and item.status == PhaseStatus.RUNNING:
            item.mark_done()

    def mark_phase_failed(self, name: str) -> None:
        """Mark the named phase as FAILED."""
        item = self.get(name)
        if item and item.status == PhaseStatus.RUNNING:
            item.mark_failed()

    def mark_phase_skipped(self, name: str) -> None:
        """Mark the named phase as SKIPPED."""
        item = self.get(name)
        if item and item.status == PhaseStatus.PENDING:
            item.mark_skipped()

    @property
    def active_phase(self) -> PhaseChecklistItem | None:
        """Return the currently-running phase, if any."""
        for item in self.items:
            if item.status == PhaseStatus.RUNNING:
                return item
        return None

    @property
    def completed_count(self) -> int:
        """Number of phases that finished (DONE, FAILED, or SKIPPED)."""
        terminal = {PhaseStatus.DONE, PhaseStatus.FAILED, PhaseStatus.SKIPPED}
        return sum(1 for item in self.items if item.status in terminal)

    @property
    def total_count(self) -> int:
        return len(self.items)
