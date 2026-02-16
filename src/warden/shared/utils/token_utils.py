"""
Token estimation and content truncation utilities.

Prevents token/context overflow when sending code to LLMs with limited context windows.
"""


def estimate_tokens(text: str) -> int:
    """
    Estimate token count using character-based heuristic.

    Uses ~4 chars per token ratio (common for English/code).

    Args:
        text: Input text

    Returns:
        Estimated token count
    """
    if not text:
        return 0
    return len(text) // 4


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

    # Calculate character budget from token limit
    char_budget = max_tokens * 4

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
    if len(truncated) > char_budget:
        truncated = truncated[:char_budget]

    return truncated
