"""Format code graph symbols for LLM prompt context.

Extracts relevant symbols (classes, functions) from a CodeGraph for a given
file and formats them as compact text suitable for inclusion in LLM prompts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from warden.analysis.domain.code_graph import CodeGraph


def format_file_symbols_for_prompt(
    code_graph: CodeGraph,
    file_path: str,
    max_tokens: int = 150,
) -> str:
    """Format symbols from a file for LLM prompt context.

    Args:
        code_graph: The project code graph.
        file_path: File path to filter symbols for.
        max_tokens: Approximate token budget (4 chars per token).

    Returns:
        Formatted string or empty string if no symbols found.
    """
    symbols = [
        node for node in code_graph.nodes.values()
        if node.file_path == file_path or file_path.endswith(node.file_path)
    ]

    if not symbols:
        return ""

    lines = ["[Code Graph Symbols]:"]
    char_budget = max_tokens * 4

    for sym in symbols[:10]:
        decorators = sym.metadata.get("decorators", [])
        dec_str = " ".join(f"@{d}" for d in decorators[:3])
        if dec_str:
            dec_str += " "
        bases_str = f" extends {', '.join(sym.bases[:3])}" if sym.bases else ""
        line = f"  - {dec_str}{sym.kind.value} {sym.name}{bases_str}"
        lines.append(line)

        if sum(len(ln) for ln in lines) > char_budget:
            break

    return "\n".join(lines)
