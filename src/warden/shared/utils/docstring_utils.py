"""
Shared Docstring/Comment Detection Utilities

Centralised keyword sets and helper functions for detecting docstring sections,
comment markers, and documentation patterns.  Used by both the false-positive
heuristic filter (FindingVerificationService) and the documentation quality
analyser (DocumentationAnalyzer) so that keyword lists stay in sync.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical keyword / marker sets
# ---------------------------------------------------------------------------

# Google / Sphinx / NumPy-style section headers found inside docstrings.
# These are stored in *lower-case*; callers should normalise before lookup.
DOCSTRING_SECTION_KEYWORDS: frozenset[str] = frozenset(
    {
        "args:",
        "arguments:",
        "parameters:",
        "params:",
        "returns:",
        "return:",
        "yields:",
        "yield:",
        "raises:",
        "example:",
        "examples:",
        "note:",
        "notes:",
        "warning:",
        "warnings:",
        "see also:",
        "references:",
        "attributes:",
        "todo:",
    }
)

# Subset: keywords that document *parameters* specifically.
DOCSTRING_PARAM_KEYWORDS: frozenset[str] = frozenset(
    {
        "args:",
        "arguments:",
        "parameters:",
        "params:",
    }
)

# Subset: keywords that document *return / yield values* specifically.
DOCSTRING_RETURN_KEYWORDS: frozenset[str] = frozenset(
    {
        "returns:",
        "return:",
        "yields:",
        "yield:",
    }
)

# Markers that indicate the *code snippet itself* is a comment or docstring
# (used by the FP heuristic filter to short-circuit verification).
COMMENT_START_MARKERS: tuple[str, ...] = (
    "#",
    "//",
    "/*",
    '"""',
    "'''",
)

# Additional indicators that a code snippet lives inside documentation
# context (e.g. a docstring body or inline example comment).
DOCSTRING_CONTEXT_INDICATORS: tuple[str, ...] = (
    '"""',
    "'''",
    "# Example",
    "# Usage",
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def has_docstring_section_keyword(text: str) -> bool:
    """Return True if *text* contains any recognised docstring section keyword.

    The check is case-insensitive and looks for keywords anywhere in the text.
    """
    text_lower = text.lower()
    return any(kw in text_lower for kw in DOCSTRING_SECTION_KEYWORDS)


def has_param_section(docstring: str) -> bool:
    """Return True if *docstring* contains a parameter documentation section."""
    docstring_lower = docstring.lower()
    return any(kw in docstring_lower for kw in DOCSTRING_PARAM_KEYWORDS)


def has_return_section(docstring: str) -> bool:
    """Return True if *docstring* contains a return/yield documentation section."""
    docstring_lower = docstring.lower()
    return any(kw in docstring_lower for kw in DOCSTRING_RETURN_KEYWORDS)


def looks_like_comment_or_docstring(code: str) -> bool:
    """Return True if *code* starts with a comment or docstring marker."""
    stripped = code.lstrip()
    return stripped.startswith(COMMENT_START_MARKERS)


def has_docstring_context_indicator(code: str) -> bool:
    """Return True if *code* contains indicators of documentation context.

    This combines the section keyword check with additional markers like
    triple-quote strings and inline example comments.
    """
    if has_docstring_section_keyword(code):
        return True
    return any(indicator in code for indicator in DOCSTRING_CONTEXT_INDICATORS)
