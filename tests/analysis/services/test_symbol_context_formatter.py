"""Tests for format_file_symbols_for_prompt.

Covers: empty graph, no file match, single symbol, multiple symbols,
        decorator rendering, base class rendering, token budget,
        partial path matching, and the 10-symbol cap.
"""

from __future__ import annotations

import pytest

from warden.analysis.domain.code_graph import CodeGraph, SymbolKind, SymbolNode
from warden.analysis.services.symbol_context_formatter import (
    format_file_symbols_for_prompt,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FILE = "src/warden/security/frame.py"


def _node(
    name: str,
    *,
    kind: SymbolKind = SymbolKind.CLASS,
    file_path: str = FILE,
    bases: list[str] | None = None,
    decorators: list[str] | None = None,
) -> SymbolNode:
    """Build a minimal SymbolNode with sane defaults."""
    metadata: dict = {}
    if decorators is not None:
        metadata["decorators"] = decorators
    return SymbolNode(
        fqn=f"{file_path}::{name}",
        name=name,
        kind=kind,
        file_path=file_path,
        line=1,
        module="",
        bases=bases or [],
        metadata=metadata,
    )


def _graph(*nodes: SymbolNode) -> CodeGraph:
    """Build a CodeGraph pre-populated with the given nodes."""
    g = CodeGraph()
    for node in nodes:
        g.add_node(node)
    return g


# ---------------------------------------------------------------------------
# 1. Empty graph returns empty string
# ---------------------------------------------------------------------------


def test_empty_graph_returns_empty_string():
    result = format_file_symbols_for_prompt(CodeGraph(), FILE)
    assert result == ""


# ---------------------------------------------------------------------------
# 2. No matching file returns empty string
# ---------------------------------------------------------------------------


def test_no_matching_file_returns_empty_string():
    graph = _graph(_node("MyClass", file_path="src/other/module.py"))
    result = format_file_symbols_for_prompt(graph, FILE)
    assert result == ""


# ---------------------------------------------------------------------------
# 3. Single class symbol formatted correctly
# ---------------------------------------------------------------------------


def test_single_class_symbol_formatted():
    graph = _graph(_node("SecurityFrame"))
    result = format_file_symbols_for_prompt(graph, FILE)

    assert result.startswith("[Code Graph Symbols]:")
    assert "class SecurityFrame" in result


def test_single_function_symbol_formatted():
    graph = _graph(_node("validate", kind=SymbolKind.FUNCTION))
    result = format_file_symbols_for_prompt(graph, FILE)

    assert "function validate" in result


def test_output_lines_start_with_bullet():
    graph = _graph(_node("MyClass"))
    result = format_file_symbols_for_prompt(graph, FILE)

    symbol_lines = result.splitlines()[1:]
    for line in symbol_lines:
        assert line.startswith("  - "), f"Expected bullet prefix, got: {line!r}"


# ---------------------------------------------------------------------------
# 4. Multiple symbols formatted
# ---------------------------------------------------------------------------


def test_multiple_symbols_all_appear():
    graph = _graph(
        _node("Alpha"),
        _node("Beta", kind=SymbolKind.FUNCTION),
        _node("Gamma", kind=SymbolKind.METHOD),
    )
    result = format_file_symbols_for_prompt(graph, FILE)

    assert "Alpha" in result
    assert "Beta" in result
    assert "Gamma" in result


def test_multiple_symbols_header_appears_once():
    graph = _graph(_node("Alpha"), _node("Beta"))
    result = format_file_symbols_for_prompt(graph, FILE)

    assert result.count("[Code Graph Symbols]:") == 1


# ---------------------------------------------------------------------------
# 5. Decorators in metadata are rendered
# ---------------------------------------------------------------------------


def test_single_decorator_rendered():
    graph = _graph(_node("index", kind=SymbolKind.FUNCTION, decorators=["app.route"]))
    result = format_file_symbols_for_prompt(graph, FILE)

    assert "@app.route" in result


def test_multiple_decorators_rendered():
    graph = _graph(
        _node(
            "create_view",
            kind=SymbolKind.FUNCTION,
            decorators=["login_required", "permission_required"],
        )
    )
    result = format_file_symbols_for_prompt(graph, FILE)

    assert "@login_required" in result
    assert "@permission_required" in result


def test_only_first_three_decorators_rendered():
    graph = _graph(
        _node(
            "over_decorated",
            decorators=["d1", "d2", "d3", "d4", "d5"],
        )
    )
    result = format_file_symbols_for_prompt(graph, FILE)

    assert "@d1" in result
    assert "@d2" in result
    assert "@d3" in result
    assert "@d4" not in result
    assert "@d5" not in result


def test_no_decorators_no_at_symbol():
    graph = _graph(_node("Plain"))
    result = format_file_symbols_for_prompt(graph, FILE)

    # Only the bullet prefix should precede the kind keyword — no stray '@'
    symbol_line = next(ln for ln in result.splitlines() if "Plain" in ln)
    assert "@" not in symbol_line


def test_decorator_appears_before_kind_keyword():
    graph = _graph(_node("Routed", decorators=["app.route"]))
    result = format_file_symbols_for_prompt(graph, FILE)

    symbol_line = next(ln for ln in result.splitlines() if "Routed" in ln)
    at_pos = symbol_line.index("@app.route")
    kind_pos = symbol_line.index("class")
    assert at_pos < kind_pos


# ---------------------------------------------------------------------------
# 6. Base classes are rendered
# ---------------------------------------------------------------------------


def test_single_base_class_rendered():
    graph = _graph(_node("Child", bases=["Parent"]))
    result = format_file_symbols_for_prompt(graph, FILE)

    assert "extends Parent" in result


def test_multiple_base_classes_rendered():
    graph = _graph(_node("Multi", bases=["Base", "Mixin"]))
    result = format_file_symbols_for_prompt(graph, FILE)

    assert "extends Base, Mixin" in result


def test_only_first_three_bases_rendered():
    graph = _graph(_node("Wide", bases=["A", "B", "C", "D", "E"]))
    result = format_file_symbols_for_prompt(graph, FILE)

    assert "extends A, B, C" in result
    assert "D" not in result
    assert "E" not in result


def test_no_bases_no_extends_keyword():
    graph = _graph(_node("Standalone"))
    result = format_file_symbols_for_prompt(graph, FILE)

    assert "extends" not in result


# ---------------------------------------------------------------------------
# 7. Token budget is respected
# ---------------------------------------------------------------------------


def test_tiny_budget_truncates_output():
    # 5 tokens = 20 chars budget — header alone is 21 chars, so the check
    # fires after the first symbol line is appended.
    graph = _graph(
        _node("Alpha"),
        _node("Beta"),
        _node("Gamma"),
        _node("Delta"),
        _node("Epsilon"),
    )
    result = format_file_symbols_for_prompt(graph, FILE, max_tokens=5)

    # Must still have the header and at least the line that tripped the budget
    assert "[Code Graph Symbols]:" in result
    # Should NOT contain every symbol — budget was too tight
    symbol_names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"]
    present = [name for name in symbol_names if name in result]
    assert len(present) < len(symbol_names)


def test_generous_budget_includes_all_symbols():
    graph = _graph(
        _node("Alpha"),
        _node("Beta"),
        _node("Gamma"),
    )
    # 1000 tokens = 4000 chars — far beyond what three symbols need
    result = format_file_symbols_for_prompt(graph, FILE, max_tokens=1000)

    assert "Alpha" in result
    assert "Beta" in result
    assert "Gamma" in result


def test_budget_measured_in_chars_not_lines():
    # One long-name symbol should consume more budget than a short one.
    long_name = "A" * 200
    graph = _graph(_node(long_name), _node("Short"))
    # 10 tokens = 40 chars; header is 21, first entry easily exceeds
    result = format_file_symbols_for_prompt(graph, FILE, max_tokens=10)

    assert "[Code Graph Symbols]:" in result


# ---------------------------------------------------------------------------
# 8. Partial file path matching
# ---------------------------------------------------------------------------


def test_exact_file_path_match():
    graph = _graph(_node("Exact", file_path=FILE))
    result = format_file_symbols_for_prompt(graph, FILE)

    assert "Exact" in result


def test_partial_endswith_match():
    # Node stores a relative path; caller passes an absolute path that ends
    # with the same relative segment.
    relative = "warden/security/frame.py"
    absolute = f"/home/runner/project/{relative}"
    graph = _graph(_node("PartialMatch", file_path=relative))
    result = format_file_symbols_for_prompt(graph, absolute)

    assert "PartialMatch" in result


def test_non_matching_suffix_excluded():
    # "other_frame.py" ends with "frame.py" — that would be a false positive
    # only if the node path is exactly "frame.py". Verify the endswith check
    # does not match a node at a completely different path.
    graph = _graph(_node("Unrelated", file_path="src/completely/different.py"))
    result = format_file_symbols_for_prompt(graph, FILE)

    assert result == ""


def test_both_exact_and_partial_matches_included():
    exact_file = FILE
    partial_stored = "security/frame.py"  # ends with this segment
    query_path = f"/abs/{partial_stored}"  # absolute form of the partial path
    graph = _graph(
        _node("ExactNode", file_path=exact_file),
        _node("PartialNode", file_path=partial_stored),
    )
    result = format_file_symbols_for_prompt(graph, query_path)

    # PartialNode matches (query ends with partial_stored)
    assert "PartialNode" in result


# ---------------------------------------------------------------------------
# 9. Max 10 symbols limit
# ---------------------------------------------------------------------------


def test_more_than_ten_symbols_capped_at_ten():
    nodes = [_node(f"Class{i}") for i in range(15)]
    graph = _graph(*nodes)
    # Large budget so the token check never fires first
    result = format_file_symbols_for_prompt(graph, FILE, max_tokens=10_000)

    symbol_lines = [ln for ln in result.splitlines() if ln.startswith("  - ")]
    assert len(symbol_lines) <= 10


def test_exactly_ten_symbols_all_included():
    nodes = [_node(f"Symbol{i}") for i in range(10)]
    graph = _graph(*nodes)
    result = format_file_symbols_for_prompt(graph, FILE, max_tokens=10_000)

    for i in range(10):
        assert f"Symbol{i}" in result


def test_eleven_symbols_eleventh_excluded():
    nodes = [_node(f"Item{i}") for i in range(11)]
    graph = _graph(*nodes)
    result = format_file_symbols_for_prompt(graph, FILE, max_tokens=10_000)

    symbol_lines = [ln for ln in result.splitlines() if ln.startswith("  - ")]
    assert len(symbol_lines) == 10
    # The 11th symbol (Item10) must be absent
    assert "Item10" not in result
