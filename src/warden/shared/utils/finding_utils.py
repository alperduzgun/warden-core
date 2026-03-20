"""
Utilities for safely interacting with Finding objects and dictionaries.
Ensures resilience across different data representations in the pipeline.
"""

import re
from typing import Any


def get_finding_attribute(finding: Any, attr: str, default: Any = None) -> Any:
    """
    Safely retrieves an attribute from a Finding object or a dictionary.
    Ensures that .get() is only called on objects that truly support it (like dicts).
    """
    if finding is None:
        return default

    # Strictly check for dict type to avoid calling .get() on Finding objects
    if isinstance(finding, dict):
        try:
            return finding.get(attr, default)
        except AttributeError:
            # Fallback for dict-like objects that might fail .get
            pass

    # Use getattr for everything else, which is safe for Finding objects
    return getattr(finding, attr, default)


def set_finding_attribute(finding: Any, attr: str, value: Any) -> None:
    """
    Safely sets an attribute on a Finding object or a dictionary.
    """
    if finding is None:
        return

    if isinstance(finding, dict):
        try:
            finding[attr] = value
            return
        except (TypeError, KeyError):
            pass

    # Fallback to setattr for objects
    try:
        setattr(finding, attr, value)
    except (AttributeError, TypeError):
        # Ignore if immutable or missing
        pass


_KNOWN_SEVERITIES = frozenset({"critical", "high", "medium", "low"})

# ---------------------------------------------------------------------------
# LLM line-reference validation
# ---------------------------------------------------------------------------

_LINE_REF_STOP_WORDS: frozenset[str] = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "missing",
        "incomplete", "invalid", "incorrect", "potential", "possible",
        "detected", "found", "check", "validation", "input", "output",
        "function", "method", "class", "variable", "value", "code",
        "line", "file", "error", "warning", "issue", "lack", "lacks",
        "without", "when", "where", "before", "after", "should", "must",
        "could", "does", "doesnt", "does not", "not", "been",
    }
)


def extract_finding_keywords(text: str) -> list[str]:
    """Extract meaningful tokens from a finding title or message.

    Strips stop words and punctuation, returning tokens longer than 3
    characters.  The resulting list is used to verify whether an LLM-reported
    line number actually points at relevant code.

    Args:
        text: Free-form string (e.g. finding title or description).

    Returns:
        List of lower-cased, de-noised keyword tokens.
    """
    tokens = re.split(r"[\s\-_/\\.,;:()\[\]{}\"\']+", text.lower())
    return [t for t in tokens if len(t) > 3 and t not in _LINE_REF_STOP_WORDS]


def validate_llm_line_reference(
    finding_message: str,
    finding_title: str,
    code_content: str,
    reported_line: int,
    window: int = 3,
) -> bool:
    """Check whether a LLM-reported line number is plausibly correct.

    LLMs frequently hallucinate line numbers: they cite the right function name
    but report a line number that belongs to a completely different construct
    in the file.  This function cross-checks the finding's keywords against the
    actual source lines in a ±*window* neighbourhood of the reported line.

    Design decisions
    ----------------
    - A ±3-line window (7 lines total) tolerates minor off-by-one errors while
      catching gross hallucinations (e.g. line 1685 for a function defined at
      line 1540).
    - Out-of-range line numbers return ``True`` (cannot validate; keep finding).
    - Blank windows or no extractable keywords return ``True`` (fail-open:
      conservative — only drop findings with clear evidence of hallucination).
    - Severity is NOT modified; callers decide what to do with ``False``
      (drop the finding, downgrade severity, or attach a warning tag).

    Args:
        finding_message: Human-readable message attached to the finding.
        finding_title:   Short title of the finding (may overlap with message).
        code_content:    Full source file text as a single string.
        reported_line:   1-based line number returned by the LLM.
        window:          Number of lines before/after to include in the check.

    Returns:
        ``True``  — keywords matched; line reference appears plausible.
        ``False`` — no keywords matched; line reference is likely hallucinated.
    """
    lines = code_content.splitlines()
    total_lines = len(lines)

    # Out-of-range: cannot validate — keep finding (fail-open)
    if reported_line < 1 or reported_line > total_lines:
        return True

    # Build code window (0-based slice)
    start = max(0, reported_line - 1 - window)
    end = min(total_lines, reported_line + window)  # exclusive
    window_text = " ".join(lines[start:end]).lower()

    if not window_text.strip():
        return True  # Blank window — cannot confirm, keep finding

    # Gather keywords from both title and message
    combined_text = f"{finding_title} {finding_message}"
    keywords = extract_finding_keywords(combined_text)

    if not keywords:
        return True  # Nothing to check against — cannot validate

    return any(kw in window_text for kw in keywords)


def get_finding_severity(finding: Any) -> str:
    """Safely gets normalized severity. Unknown values map to 'low'."""
    sev = get_finding_attribute(finding, "severity", "medium")
    normalized = str(sev).lower() if sev else "medium"
    return normalized if normalized in _KNOWN_SEVERITIES else "low"
