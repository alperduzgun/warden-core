"""
Orphan Code Detection Frame

Detects unused and unreachable code (orphan code):
- Unused imports
- Unreferenced functions and classes
- Dead code (unreachable statements)

NEW in v2.0: LLM-powered intelligent filtering to reduce false positives.

Components:
- OrphanFrame: Main frame orchestrator
- OrphanDetector: AST-based detection (fast, simple rules)
- LLMOrphanFilter: LLM-based filtering (smart, context-aware)

Usage:
    from warden.validation.frames.orphan import OrphanFrame

    frame = OrphanFrame(config={"use_llm_filter": True})
    result = await frame.execute(code_file)
"""

from warden.validation.frames.orphan.orphan_frame import OrphanFrame
from warden.validation.frames.orphan.orphan_detector import (
    OrphanDetector,
    OrphanFinding,
)
from warden.validation.frames.orphan.llm_orphan_filter import (
    LLMOrphanFilter,
    FilterDecision,
)

__all__ = [
    "OrphanFrame",
    "OrphanDetector",
    "OrphanFinding",
    "LLMOrphanFilter",
    "FilterDecision",
]
