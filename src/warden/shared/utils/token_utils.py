"""
Token estimation and content truncation utilities.

Prevents token/context overflow when sending code to LLMs with limited context windows.
Uses tiktoken for accurate estimation, with len//4 fallback.
"""

from __future__ import annotations

import threading

try:
    import tiktoken

    _TIKTOKEN_AVAILABLE = True
except ImportError:
    tiktoken = None  # type: ignore[assignment]
    _TIKTOKEN_AVAILABLE = False

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class TokenCounter:
    def __init__(self):
        if not _TIKTOKEN_AVAILABLE:
            raise ImportError("tiktoken is not installed")
        self.enc = tiktoken.get_encoding("cl100k_base")

    def count(self, text: str) -> int:
        return len(self.enc.encode(text))

    def estimate_max(self, text: str, max_tokens: int) -> str:
        tokens = self.count(text)
        if tokens > max_tokens:
            chars_per_token = len(text) / tokens
            return text[: int(max_tokens * chars_per_token)]
        return text


_counter: TokenCounter | None = None
_fallback_active: bool = False
_counter_lock = threading.Lock()


def _get_counter() -> TokenCounter:
    """Lazy-init singleton. Raises on tiktoken import/init failure."""
    global _counter
    if _counter is None:
        with _counter_lock:
            if _counter is None:
                _counter = TokenCounter()
    return _counter


def estimate_tokens(text: str) -> int:
    """
    Estimate token count using tiktoken (accurate).

    Falls back to ~4 chars per token heuristic on error.

    Args:
        text: Input text

    Returns:
        Estimated token count
    """
    global _fallback_active
    if not text:
        return 0
    try:
        return _get_counter().count(text)
    except Exception:
        if not _fallback_active:
            _fallback_active = True
            logger.warning("tiktoken_fallback_activated", reason="count failed, using len//4")
        return len(text) // 4


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to fit within max_tokens. Falls back to char-proportional."""
    if not text:
        return text
    try:
        return _get_counter().estimate_max(text, max_tokens)
    except Exception:
        return text[: max_tokens * 4]


def truncate_content_for_llm(
    content: str,
    max_tokens: int = 2000,
    preserve_start_lines: int = 20,
    preserve_end_lines: int = 10,
) -> str:
    """
    Truncate content to fit within LLM token limits while preserving structure.

    Strategy:
    - If content fits, return as-is
    - Otherwise, keep first N lines + last M lines + truncation marker

    Args:
        content: Source code or text content
        max_tokens: Maximum token budget for the content
        preserve_start_lines: Number of lines to keep from the start
        preserve_end_lines: Number of lines to keep from the end

    Returns:
        Truncated content that fits within token budget
    """
    if not content:
        return content

    estimated = estimate_tokens(content)
    if estimated <= max_tokens:
        return content

    # Calculate character budget from token limit (conservative: 4 chars/token for backward compatibility)
    char_budget = int(max_tokens * 4)

    lines = content.split("\n")

    if len(lines) <= preserve_start_lines + preserve_end_lines:
        # Few lines, just hard-truncate by characters
        return content[:char_budget]

    # Keep start + end with truncation marker
    start_section = "\n".join(lines[:preserve_start_lines])
    end_section = "\n".join(lines[-preserve_end_lines:])
    truncation_marker = (
        f"\n\n... [{len(lines) - preserve_start_lines - preserve_end_lines} lines truncated for LLM context] ...\n\n"
    )

    truncated = start_section + truncation_marker + end_section

    # If still too long, hard-truncate
    if estimate_tokens(truncated) > max_tokens:
        truncated = truncated[:char_budget]

    return truncated


def truncate_with_ast_hints(
    content: str,
    max_tokens: int = 2000,
    dangerous_lines: list[int] | None = None,
    preserve_start_lines: int = 10,
    preserve_end_lines: int = 5,
    context_window: int = 5,
) -> str:
    """
    Truncate preserving lines around known dangerous call sites.

    Falls back to head+tail if no hints provided or content fits.

    Args:
        content: Source code content
        max_tokens: Maximum token budget
        dangerous_lines: 1-based line numbers of dangerous calls/sinks
        preserve_start_lines: Lines to always keep from start (imports)
        preserve_end_lines: Lines to always keep from end (exports)
        context_window: Lines before/after each dangerous line to keep

    Returns:
        Truncated content preserving security-relevant sections
    """
    if not content:
        return content

    if estimate_tokens(content) <= max_tokens:
        return content

    if not dangerous_lines:
        return truncate_content_for_llm(content, max_tokens, preserve_start_lines, preserve_end_lines)

    lines = content.splitlines()
    total_lines = len(lines)

    # Build priority set: structure lines + windows around dangerous lines
    # Structure: first N (imports) + last M (exports/module-level)
    selected = set(range(min(preserve_start_lines, total_lines)))
    selected |= set(range(max(0, total_lines - preserve_end_lines), total_lines))

    # Add context windows around each dangerous line (convert 1-based to 0-based)
    for dl in dangerous_lines:
        idx = dl - 1  # 1-based to 0-based
        for offset in range(-context_window, context_window + 1):
            line_idx = idx + offset
            if 0 <= line_idx < total_lines:
                selected.add(line_idx)

    # Sort and build output, adding markers for gaps
    sorted_indices = sorted(selected)
    result_parts: list[str] = []
    prev_idx = -1

    for idx in sorted_indices:
        if prev_idx >= 0 and idx > prev_idx + 1:
            gap = idx - prev_idx - 1
            result_parts.append(f"  ... [{gap} lines omitted] ...")
        result_parts.append(lines[idx])
        prev_idx = idx

    result = "\n".join(result_parts)

    # If still too big after selecting priority lines, hard-truncate
    if estimate_tokens(result) > max_tokens:
        char_budget = int(max_tokens * 4)
        result = result[:char_budget]

    return result
