"""
Orphan Code Detection Frame

Detects unused and unreachable code (orphan code):
- Unused imports
- Unreferenced functions and classes
- Dead code (unreachable statements)

Detection Strategies (priority order):
1. LSPOrphanDetector - Cross-file semantic analysis via LSP (most accurate)
2. RustOrphanDetector - Fast single-file via Rust+Tree-sitter
3. PythonOrphanDetector - Native AST for Python
4. UniversalOrphanDetector - Tree-sitter based fallback

LLM-powered intelligent filtering available to reduce false positives.

Usage:
    from . import OrphanFrame

    # Standard mode (fast, single-file)
    frame = OrphanFrame(config={"use_llm_filter": True})
    result = await frame.execute(code_file)

    # LSP mode (slower, cross-file) - set via OrphanDetectorFactory
"""

from warden.validation.frames.orphan.orphan_frame import OrphanFrame
from warden.validation.frames.orphan.orphan_detector import (
    AbstractOrphanDetector,
    PythonOrphanDetector,
    TreeSitterOrphanDetector,
    RustOrphanDetector,
    LSPOrphanDetector,
    OrphanDetectorFactory,
    OrphanFinding,
    LSP_AVAILABLE,
)
from warden.validation.frames.orphan.llm_orphan_filter import (
    LLMOrphanFilter,
    FilterDecision,
)

__all__ = [
    "OrphanFrame",
    "AbstractOrphanDetector",
    "PythonOrphanDetector",
    "TreeSitterOrphanDetector",
    "RustOrphanDetector",
    "LSPOrphanDetector",
    "OrphanDetectorFactory",
    "OrphanFinding",
    "LLMOrphanFilter",
    "FilterDecision",
    "LSP_AVAILABLE",
]
