"""
Warden Audit-Context CLI Command.

Display and check code graph intelligence from .warden/intelligence/.
Outputs YAML, JSON, or Markdown (LLM audit prompt) format.

Stages 4+8 of the audit-context plan.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

console = Console()


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file safely, return empty dict on failure."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _load_intelligence(project_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    Load intelligence data from .warden/intelligence/.

    Returns:
        (code_graph_data, gap_report_data, dependency_graph_data)
    """
    intel_dir = project_root / ".warden" / "intelligence"
    code_graph = _load_json(intel_dir / "code_graph.json")
    gap_report = _load_json(intel_dir / "gap_report.json")
    dep_graph = _load_json(intel_dir / "dependency_graph.json")
    return code_graph, gap_report, dep_graph


def _render_yaml(
    code_graph: dict[str, Any],
    gap_report: dict[str, Any],
    dep_graph: dict[str, Any],
    full: bool = False,
) -> str:
    """Render compact YAML output."""
    import yaml

    sections: dict[str, Any] = {}

    # Graph stats
    if code_graph:
        stats = code_graph.get("stats", {})
        if not stats:
            nodes = code_graph.get("nodes", {})
            edges = code_graph.get("edges", [])
            stats = {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
            }
        sections["graph"] = {
            "nodes": stats.get("total_nodes", 0),
            "edges": stats.get("total_edges", 0),
            "classes": stats.get("classes", 0),
            "functions": stats.get("functions", 0),
            "test_nodes": stats.get("test_nodes", 0),
            "generated_at": code_graph.get("generated_at", "unknown"),
        }

    # Gap summary
    if gap_report:
        sections["gaps"] = {
            "coverage": gap_report.get("coverage", 0),
            "orphan_files": len(gap_report.get("orphan_files", [])),
            "orphan_symbols": len(gap_report.get("orphan_symbols", [])),
            "broken_imports": len(gap_report.get("broken_imports", [])),
            "circular_deps": len(gap_report.get("circular_deps", [])),
            "unreachable": len(gap_report.get("unreachable_from_entry", [])),
            "missing_mixin_impl": len(gap_report.get("missing_mixin_impl", [])),
            "star_imports": len(gap_report.get("star_imports", [])),
            "dynamic_imports": len(gap_report.get("dynamic_imports", [])),
            "unparseable_files": len(gap_report.get("unparseable_files", [])),
        }

    # Dependency graph stats
    if dep_graph:
        dep_stats = dep_graph.get("stats", {})
        sections["dependencies"] = {
            "total_files": dep_stats.get("total_files", 0),
            "total_edges": dep_stats.get("total_edges", 0),
            "orphan_files": dep_stats.get("orphan_count", 0),
            "integrity_ok": dep_graph.get("integrity", {}).get("forward_reverse_match", False),
        }

    # Full mode: include lists
    if full:
        if gap_report.get("broken_imports"):
            sections["broken_imports_detail"] = gap_report["broken_imports"]
        if gap_report.get("circular_deps"):
            sections["circular_deps_detail"] = gap_report["circular_deps"]
        if gap_report.get("orphan_files"):
            sections["orphan_files_detail"] = gap_report["orphan_files"][:50]
        if gap_report.get("missing_mixin_impl"):
            sections["missing_mixin_impl_detail"] = gap_report["missing_mixin_impl"]
        if gap_report.get("test_only_consumers"):
            sections["test_only_consumers_detail"] = gap_report["test_only_consumers"]

    if not sections:
        return "# No intelligence data found. Run 'warden refresh --force' first.\n"

    return yaml.safe_dump(sections, sort_keys=False, default_flow_style=False)


def _render_json(
    code_graph: dict[str, Any],
    gap_report: dict[str, Any],
    dep_graph: dict[str, Any],
    full: bool = False,
) -> str:
    """Render machine-readable JSON output."""
    result: dict[str, Any] = {}

    if code_graph:
        if full:
            result["code_graph"] = code_graph
        else:
            result["code_graph"] = {
                "schema_version": code_graph.get("schema_version", "1.0.0"),
                "generated_at": code_graph.get("generated_at", ""),
                "stats": code_graph.get("stats", {}),
            }

    if gap_report:
        if full:
            result["gap_report"] = gap_report
        else:
            # Summary only
            summary = {
                "coverage": gap_report.get("coverage", 0),
                "orphan_files": len(gap_report.get("orphan_files", [])),
                "orphan_symbols": len(gap_report.get("orphan_symbols", [])),
                "broken_imports": len(gap_report.get("broken_imports", [])),
                "circular_deps": len(gap_report.get("circular_deps", [])),
                "unreachable_from_entry": len(gap_report.get("unreachable_from_entry", [])),
                "missing_mixin_impl": len(gap_report.get("missing_mixin_impl", [])),
                "star_imports": len(gap_report.get("star_imports", [])),
                "dynamic_imports": len(gap_report.get("dynamic_imports", [])),
                "unparseable_files": len(gap_report.get("unparseable_files", [])),
            }
            result["gap_report"] = summary

    if dep_graph:
        if full:
            result["dependency_graph"] = dep_graph
        else:
            result["dependency_graph"] = {
                "stats": dep_graph.get("stats", {}),
                "integrity": dep_graph.get("integrity", {}),
            }

    return json.dumps(result, indent=2, ensure_ascii=False)


def _render_markdown(
    code_graph: dict[str, Any],
    gap_report: dict[str, Any],
    dep_graph: dict[str, Any],
    full: bool = False,
) -> str:
    """Render Markdown audit prompt for LLM consumption."""
    lines: list[str] = []
    lines.append("# Warden Audit Context")
    lines.append("")

    # --- Graph overview ---
    if code_graph:
        lines.append("## Code Graph Overview")
        lines.append("")
        nodes = code_graph.get("nodes", {})
        edges = code_graph.get("edges", [])
        stats = code_graph.get("stats", {})
        n_nodes = stats.get("total_nodes", len(nodes))
        n_edges = stats.get("total_edges", len(edges))
        n_classes = stats.get("classes", 0)
        n_funcs = stats.get("functions", 0)
        n_tests = stats.get("test_nodes", 0)
        lines.append(f"- **Symbols:** {n_nodes} ({n_classes} classes, {n_funcs} functions, {n_tests} test)")
        lines.append(f"- **Edges:** {n_edges}")
        lines.append(f"- **Generated:** {code_graph.get('generated_at', 'unknown')}")
        lines.append("")

        # Service map table (top classes by connections)
        if nodes and full:
            lines.append("### Symbol Map (top classes)")
            lines.append("")
            lines.append("| Symbol | Kind | File | Line |")
            lines.append("|--------|------|------|------|")
            class_nodes = [
                n for n in nodes.values()
                if isinstance(n, dict) and n.get("kind") == "class"
            ]
            for node in class_nodes[:30]:
                name = node.get("name", "?")
                kind = node.get("kind", "?")
                fpath = node.get("file_path", "?")
                line = node.get("line", 0)
                lines.append(f"| `{name}` | {kind} | `{fpath}` | {line} |")
            lines.append("")

        # Class hierarchy
        if edges and full:
            inherit_edges = [
                e for e in edges
                if isinstance(e, dict) and e.get("relation") in ("inherits", "implements")
            ]
            if inherit_edges:
                lines.append("### Class Hierarchy")
                lines.append("")
                lines.append("```")
                for e in inherit_edges[:40]:
                    src = e.get("source", "?").rsplit("::", 1)[-1]
                    tgt = e.get("target", "?").rsplit("::", 1)[-1]
                    rel = e.get("relation", "?")
                    lines.append(f"  {src} --{rel}--> {tgt}")
                lines.append("```")
                lines.append("")

    # --- Gap report ---
    if gap_report:
        lines.append("## Gap Analysis")
        lines.append("")
        coverage = gap_report.get("coverage", 0)
        lines.append(f"- **Coverage:** {coverage:.1%}")
        lines.append(f"- **Orphan files:** {len(gap_report.get('orphan_files', []))}")
        lines.append(f"- **Orphan symbols:** {len(gap_report.get('orphan_symbols', []))}")
        lines.append(f"- **Broken imports:** {len(gap_report.get('broken_imports', []))}")
        lines.append(f"- **Circular deps:** {len(gap_report.get('circular_deps', []))}")
        lines.append(f"- **Unreachable from entry:** {len(gap_report.get('unreachable_from_entry', []))}")
        lines.append(f"- **Missing mixin impls:** {len(gap_report.get('missing_mixin_impl', []))}")
        lines.append(f"- **Star imports:** {len(gap_report.get('star_imports', []))}")
        lines.append(f"- **Dynamic imports:** {len(gap_report.get('dynamic_imports', []))}")
        lines.append(f"- **Unparseable files:** {len(gap_report.get('unparseable_files', []))}")
        lines.append("")

        # Known issues list
        issues: list[str] = []
        for bi in gap_report.get("broken_imports", []):
            issues.append(f"  - Broken import: `{bi}`")
        for cd in gap_report.get("circular_deps", []):
            chain = " -> ".join(str(c).rsplit("::", 1)[-1] for c in cd)
            issues.append(f"  - Circular: {chain}")
        for mm in gap_report.get("missing_mixin_impl", []):
            issues.append(f"  - Missing mixin impl: `{mm}`")

        if issues:
            lines.append("### Known Issues")
            lines.append("")
            for issue in issues[:50]:
                lines.append(issue)
            lines.append("")

    # --- Dependency graph ---
    if dep_graph:
        lines.append("## Dependency Graph")
        lines.append("")
        dep_stats = dep_graph.get("stats", {})
        integrity = dep_graph.get("integrity", {})
        lines.append(f"- **Files:** {dep_stats.get('total_files', 0)}")
        lines.append(f"- **Edges:** {dep_stats.get('total_edges', 0)}")
        lines.append(f"- **Orphan files:** {dep_stats.get('orphan_count', 0)}")
        lines.append(f"- **Integrity:** {'OK' if integrity.get('forward_reverse_match') else 'MISMATCH'}")
        lines.append("")

    if not code_graph and not gap_report and not dep_graph:
        lines.append("No intelligence data found. Run `warden refresh --force` first.")
        lines.append("")

    return "\n".join(lines)


def _check_gaps(gap_report: dict[str, Any]) -> int:
    """
    Check gap report for critical issues.

    Returns:
        0 if no critical gaps, 1 if critical gaps found.
    """
    if not gap_report:
        return 0

    broken = gap_report.get("broken_imports", [])
    if broken:
        console.print(f"[red]CRITICAL: {len(broken)} broken imports[/red]")
        for bi in broken[:10]:
            console.print(f"  - {bi}")
        return 1

    coverage = gap_report.get("coverage", 0)
    unreachable = gap_report.get("unreachable_from_entry", [])
    if coverage > 0 and len(unreachable) > 0.2 * (1 / max(coverage, 0.01)):
        console.print(f"[yellow]WARNING: {len(unreachable)} unreachable files (coverage: {coverage:.1%})[/yellow]")
        return 1

    circular = gap_report.get("circular_deps", [])
    if len(circular) > 5:
        console.print(f"[yellow]WARNING: {len(circular)} circular dependency cycles[/yellow]")
        return 1

    return 0


def audit_context_command(
    format: str = typer.Option("yaml", "--format", "-f", help="Output format: yaml, json, markdown"),
    full: bool = typer.Option(False, "--full", help="Include detailed symbol lists"),
    check: bool = typer.Option(False, "--check", help="Check for critical gaps (exit code 1 if found)"),
) -> None:
    """
    Display audit context from code graph intelligence.

    Reads .warden/intelligence/ data (code_graph, gap_report, dependency_graph)
    and renders in the chosen format.

    Examples:
        warden audit-context                    # Compact YAML summary
        warden audit-context --format markdown  # LLM audit prompt
        warden audit-context --format json      # Machine-readable
        warden audit-context --full             # Include symbol details
        warden audit-context --check            # CI gate check
    """
    root = Path.cwd()
    intel_dir = root / ".warden" / "intelligence"

    if not intel_dir.exists():
        console.print("[yellow]No intelligence data found.[/yellow]")
        console.print("[dim]Run 'warden refresh --force' or 'warden init' first.[/dim]")
        raise typer.Exit(1)

    code_graph, gap_report, dep_graph = _load_intelligence(root)

    if not code_graph and not gap_report and not dep_graph:
        console.print("[yellow]Intelligence directory exists but contains no data.[/yellow]")
        console.print("[dim]Run 'warden refresh --force' to regenerate.[/dim]")
        raise typer.Exit(1)

    # Check mode
    if check:
        exit_code = _check_gaps(gap_report)
        if exit_code == 0:
            console.print("[green]No critical gaps found.[/green]")
        raise typer.Exit(exit_code)

    # Render
    fmt = format.lower().strip()
    if fmt == "json":
        output = _render_json(code_graph, gap_report, dep_graph, full=full)
    elif fmt in ("md", "markdown"):
        output = _render_markdown(code_graph, gap_report, dep_graph, full=full)
    else:
        output = _render_yaml(code_graph, gap_report, dep_graph, full=full)

    # Print to stdout (no Rich markup for piping compatibility)
    sys.stdout.write(output)
    if not output.endswith("\n"):
        sys.stdout.write("\n")
