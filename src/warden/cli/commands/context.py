"""
Context Commands for Warden CLI

Generate and manage machine-readable project context under .warden/context.yaml.

KISS/DRY/SOLID/YAGNI:
- Minimal schema, idempotent writes, dry-run/check modes.
- No external network calls.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console

console = Console()

context_app = typer.Typer(name="context", help="Detect and manage project context", no_args_is_help=True)


def _safe_yaml_dump(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        try:
            return yaml.safe_load(f) or {}
        except yaml.YAMLError:
            return {}


def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge: prefer values from b, keep a's other keys."""
    out = dict(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def detect_structure(root: Path) -> dict[str, Any]:
    return {
        "src": ["src"] if (root / "src").exists() else [],
        "tests": ["tests"] if (root / "tests").exists() else [],
        "docs": ["docs"] if (root / "docs").exists() else [],
        "scripts": ["scripts"] if (root / "scripts").exists() else [],
    }


_detect_structure = detect_structure


def detect_style(pyproject: dict[str, Any]) -> dict[str, Any]:
    tool = pyproject.get("tool") or {}
    ruff = tool.get("ruff") or {}
    fmt = ruff.get("format") or {}
    return {
        "line_length": int(ruff.get("line-length", 120)),
        "indent": fmt.get("indent-style", "space"),
        "quotes": fmt.get("quote-style", "double"),
    }


_detect_style = detect_style


def _detect_testing(pyproject: dict[str, Any]) -> dict[str, Any]:
    pytest = (pyproject.get("tool") or {}).get("pytest", {}).get("ini_options", {})
    markers = pytest.get("markers") or []
    naming = pytest.get("python_files") or ["test_*.py"]
    return {"framework": "pytest", "markers": markers, "naming": naming}


def _detect_commands() -> dict[str, Any]:
    return {
        "lint": "ruff check .",
        "format": "ruff format .",
        "test": "pytest -q",
        "scan": "warden scan",
    }


def _detect_commit_convention(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "log", "-n", "10", "--pretty=%s"], cwd=root, text=True, capture_output=True, timeout=2
        )
        if out.returncode == 0 and re.search(r"^(feat|fix|chore|docs|refactor|style|test)(\(.+\))?:", out.stdout, re.M):
            return "conventional"
    except Exception:
        pass
    return "unknown"


def read_pyproject(root: Path) -> dict[str, Any]:
    pth = root / "pyproject.toml"
    if not pth.exists():
        return {}
    try:
        try:
            import tomllib  # py311+
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore[no-redef]
            except ImportError:
                return {}
        return tomllib.loads(pth.read_text(encoding="utf-8"))
    except Exception:
        return {}


# Backward-compat alias (private name used in init.py import)
_read_pyproject = read_pyproject


def _extract_from_agents_md(md_path: Path) -> dict[str, Any]:
    if not md_path.exists():
        return {}
    text = md_path.read_text(encoding="utf-8")
    commands = {}
    if "ruff check" in text:
        commands["lint"] = "ruff check ."
    if "ruff format" in text:
        commands["format"] = "ruff format ."
    if re.search(r"pytest\s+-q", text):
        commands["test"] = "pytest -q"
    if re.search(r"warden\s+scan", text):
        commands["scan"] = "warden scan"
    return {"commands": commands}


@context_app.command("detect")
def detect(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Detect project context and print or write suggestions."""
    root = Path.cwd()
    pyproj = read_pyproject(root)
    context = {
        "structure": detect_structure(root),
        "style": detect_style(pyproj),
        "testing": _detect_testing(pyproj),
        "commands": _detect_commands(),
        "repo": {"commit_convention": _detect_commit_convention(root)},
    }
    if dry_run:
        console.print(_safe_yaml_dump(context))
        return
    ctx_path = root / ".warden" / "context.yaml"
    ctx_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_yaml(ctx_path)
    merged = _merge(existing, context)
    if merged != existing:
        ctx_path.write_text(_safe_yaml_dump(merged), encoding="utf-8")
        console.print(f"[green]Updated[/green] {ctx_path}")
    else:
        console.print("[dim]No changes to .warden/context.yaml[/dim]")


@context_app.command("apply")
def apply_from_agents(
    agents_md: Path = typer.Option(Path("AGENTS.md"), exists=False, readable=True, help="Path to AGENTS-like guide"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Import hints from AGENTS.md-like file into .warden/context.yaml (merge)."""
    root = Path.cwd()
    data = _extract_from_agents_md(agents_md)
    if not data:
        console.print("[yellow]No importable hints found in AGENTS.md[/yellow]")
        return
    ctx_path = root / ".warden" / "context.yaml"
    existing = _load_yaml(ctx_path)
    merged = _merge(existing, data)
    if dry_run:
        console.print(_safe_yaml_dump(merged))
        return
    ctx_path.parent.mkdir(parents=True, exist_ok=True)
    ctx_path.write_text(_safe_yaml_dump(merged), encoding="utf-8")
    console.print(f"[green]Updated[/green] {ctx_path}")


@context_app.command("status")
def status() -> None:
    """Show current context summary from .warden/context.yaml."""
    ctx = _load_yaml(Path.cwd() / ".warden" / "context.yaml")
    if not ctx:
        console.print("[yellow].warden/context.yaml not found[/yellow]")
        raise typer.Exit(1)
    console.print(_safe_yaml_dump(ctx))
