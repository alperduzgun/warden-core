"""
Phase checklist renderer for the ``warden scan`` Rich Live display.

Converts a ``PhaseChecklist`` into a list of ``rich.text.Text`` rows
suitable for inclusion in the live panel.  The checklist is shown at
the top of the display, giving the user an at-a-glance view of which
phases have completed, which is active, and which are still pending.

Rendering format (one row per phase):
    Done    :  [checkmark] Phase-Name    12s
    Running :  [spinner]   Phase-Name    ...
    Failed  :  [x]         Phase-Name    8s
    Skipped :  [-]         Phase-Name
    Pending :  [ ]         Phase-Name
"""

from __future__ import annotations

from rich.text import Text

from warden.pipeline.domain.phase_checklist import PhaseChecklist, PhaseChecklistItem, PhaseStatus

# ── Glyph / style lookup per status ──────────────────────────────────────

_STATUS_GLYPHS: dict[PhaseStatus, tuple[str, str]] = {
    # (glyph, rich_style)
    PhaseStatus.DONE: ("OK", "bold green"),
    PhaseStatus.RUNNING: (">>" , "bold blue"),
    PhaseStatus.FAILED: ("!!", "bold red"),
    PhaseStatus.SKIPPED: ("--", "dim"),
    PhaseStatus.PENDING: ("  ", "dim"),
}

# Phase name alignment width
_NAME_WIDTH = 18


def render_checklist_rows(checklist: PhaseChecklist) -> list[Text]:
    """Return a list of ``Text`` objects representing the checklist.

    Each phase occupies one line.  Only phases that have transitioned
    out of PENDING (or the first PENDING phase) are rendered so the
    display stays compact before the pipeline starts.
    """
    rows: list[Text] = []

    for item in checklist.items:
        row = _render_item(item)
        rows.append(row)

    return rows


def _render_item(item: PhaseChecklistItem) -> Text:
    """Render a single checklist item as a Rich ``Text`` object."""
    glyph, style = _STATUS_GLYPHS.get(item.status, ("  ", "dim"))

    row = Text()
    row.append("  ", style="")

    # Status glyph
    row.append(f"{glyph}", style=style)
    row.append(" ", style="")

    # Phase name (fixed width for alignment)
    name_style = "bold white" if item.status == PhaseStatus.RUNNING else (
        "white" if item.status == PhaseStatus.DONE else (
            "bold red" if item.status == PhaseStatus.FAILED else "dim"
        )
    )
    row.append(f"{item.name:<{_NAME_WIDTH}}", style=name_style)

    # Timing info
    if item.status == PhaseStatus.RUNNING:
        elapsed = item.elapsed_str
        if elapsed:
            row.append(f"  {elapsed}", style="dim blue")
        else:
            row.append("  ...", style="dim blue")
    elif item.status in (PhaseStatus.DONE, PhaseStatus.FAILED):
        elapsed = item.elapsed_str
        if elapsed:
            row.append(f"  {elapsed}", style="dim")
    # PENDING and SKIPPED: no timing info

    return row


# ── Phase name normalisation ─────────────────────────────────────────────

# Mapping from executor/runner phase identifiers to canonical checklist
# names (matching ``PIPELINE_PHASES`` in phase_checklist.py).
_PHASE_NAME_MAP: dict[str, str] = {
    # Executor identifiers (UPPER_CASE)
    "PRE_ANALYSIS": "Pre-Analysis",
    "PRE-ANALYSIS": "Pre-Analysis",
    "TRIAGE": "Triage",
    "ANALYSIS": "Analysis",
    "CLASSIFICATION": "Classification",
    "VALIDATION": "Validation",
    "VERIFICATION": "Verification",
    "FORTIFICATION": "Fortification",
    "CLEANING": "Cleaning",
    # Runner labels (Title Case) -- already canonical
    "Pre-Analysis": "Pre-Analysis",
    "Triage": "Triage",
    "Analysis": "Analysis",
    "Classification": "Classification",
    "Validation": "Validation",
    "Verification": "Verification",
    "Fortification": "Fortification",
    "Cleaning": "Cleaning",
    # .title() variants
    "Pre_Analysis": "Pre-Analysis",
    "Pre Analysis": "Pre-Analysis",
    # LSP sub-phase -- not in the main checklist, ignored
    "LSP_DIAGNOSTICS": "",
    "Lsp Diagnostics": "",
    "Lsp_Diagnostics": "",
}


def normalise_phase_name(raw: str) -> str:
    """Map an event phase identifier to the canonical checklist name.

    Returns an empty string if the phase should be ignored (e.g. LSP
    sub-phases that are not in the main checklist).
    """
    # Fast exact match
    canonical = _PHASE_NAME_MAP.get(raw)
    if canonical is not None:
        return canonical

    # Fallback: try .title() for things like "pre-analysis" -> "Pre-Analysis"
    titled = raw.replace("_", " ").title().replace(" ", "-")
    # Fix double-hyphen edge cases
    titled = titled.replace("Pre-", "Pre-")
    canonical = _PHASE_NAME_MAP.get(titled)
    if canonical is not None:
        return canonical

    # Last resort: return the title-cased version and let the checklist
    # handle "not found" gracefully.
    return raw.replace("_", " ").title()
