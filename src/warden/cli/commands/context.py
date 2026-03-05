"""
Context Commands for Warden CLI

Generate and manage machine-readable project context under .warden/context.yaml.

KISS/DRY/SOLID/YAGNI:
- Minimal schema, idempotent writes, dry-run/check modes.
- No external network calls.
"""

from __future__ import annotations

import json
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
    """Detect testing configuration from pyproject.toml.

    Auto-populates:
    - testing.markers from [tool.pytest.ini_options].markers
    - testing.framework (pytest detected from config or presence)
    - testing.naming from python_files option
    """
    tool = pyproject.get("tool") or {}
    pytest_opts = tool.get("pytest", {}).get("ini_options", {})

    # Extract markers - they can be a list of strings like "slow: marks slow tests"
    raw_markers = pytest_opts.get("markers") or []
    markers: list[str] = []
    for m in raw_markers:
        if isinstance(m, str):
            # Extract just the marker name (before the colon description)
            marker_name = m.split(":")[0].strip()
            if marker_name:
                markers.append(marker_name)

    naming = pytest_opts.get("python_files") or ["test_*.py"]

    return {"framework": "pytest", "markers": markers, "naming": naming}


def _detect_commands(root: Path | None = None) -> dict[str, Any]:
    """Detect lint/format/test/scan commands from common tool configs.

    Checks for the presence of tool configuration files (ruff, black, flake8,
    eslint, prettier, etc.) and generates appropriate command suggestions.
    """
    if root is None:
        root = Path.cwd()

    commands: dict[str, str] = {}

    # --- Lint command detection ---
    # Python linters (prefer ruff > flake8 > pylint)
    if _has_tool_config(root, "ruff"):
        commands["lint"] = "ruff check ."
    elif (root / ".flake8").exists() or (root / "setup.cfg").exists():
        commands["lint"] = "flake8 ."
    elif (root / ".pylintrc").exists():
        commands["lint"] = "pylint src/"
    # JS/TS linters
    elif (root / ".eslintrc.js").exists() or (root / ".eslintrc.json").exists() or (root / ".eslintrc.yml").exists():
        commands["lint"] = "eslint ."
    else:
        commands["lint"] = "ruff check ."

    # --- Format command detection ---
    # Python formatters (prefer ruff > black > yapf)
    if _has_tool_config(root, "ruff"):
        commands["format"] = "ruff format ."
    elif _has_tool_config(root, "black"):
        commands["format"] = "black ."
    elif (root / ".style.yapf").exists():
        commands["format"] = "yapf -r -i ."
    # JS/TS formatters
    elif (root / ".prettierrc").exists() or (root / ".prettierrc.json").exists():
        commands["format"] = "prettier --write ."
    else:
        commands["format"] = "ruff format ."

    # --- Test command detection ---
    # Python test runners (prefer pytest > unittest)
    if _has_tool_config(root, "pytest"):
        commands["test"] = "pytest -q"
    elif (root / "package.json").exists():
        # Check for test script in package.json
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                commands["test"] = "npm test"
            else:
                commands["test"] = "pytest -q"
        except Exception:
            commands["test"] = "npm test"
    elif (root / "Makefile").exists():
        commands["test"] = "make test"
    else:
        commands["test"] = "pytest -q"

    # Scan is always warden
    commands["scan"] = "warden scan"

    return commands


def _has_tool_config(root: Path, tool: str) -> bool:
    """Check if a tool has configuration in pyproject.toml or dedicated config files."""
    # Check pyproject.toml
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        try:
            content = pyproject_path.read_text(encoding="utf-8")
            if f"[tool.{tool}]" in content:
                return True
        except Exception:
            pass

    # Tool-specific config files
    config_files: dict[str, list[str]] = {
        "ruff": ["ruff.toml", ".ruff.toml"],
        "black": [".black.toml", "black.toml"],
        "pytest": ["pytest.ini", "setup.cfg", "tox.ini"],
    }
    for cfg_file in config_files.get(tool, []):
        if (root / cfg_file).exists():
            return True

    # For pytest, also check pyproject.toml [tool.pytest]
    if tool == "pytest" and pyproject_path.exists():
        try:
            content = pyproject_path.read_text(encoding="utf-8")
            if "[tool.pytest" in content:
                return True
        except Exception:
            pass

    return False


def _detect_commit_convention(root: Path) -> str:
    """Detect commit convention from config files and git history.

    Checks (in order):
    1. .commitlintrc, .commitlintrc.json, .commitlintrc.yml, .commitlintrc.yaml
    2. commitlint.config.js / commitlint.config.ts
    3. Git log pattern matching for conventional commits
    """
    # Check commitlint config files first
    commitlint_files = [
        ".commitlintrc",
        ".commitlintrc.json",
        ".commitlintrc.yml",
        ".commitlintrc.yaml",
        "commitlint.config.js",
        "commitlint.config.ts",
        "commitlint.config.cjs",
        "commitlint.config.mjs",
    ]
    for cfg_file in commitlint_files:
        cfg_path = root / cfg_file
        if cfg_path.exists():
            # If commitlint is configured, check for conventional-commits preset
            try:
                content = cfg_path.read_text(encoding="utf-8")
                if "conventional" in content.lower():
                    return "conventional"
                # commitlint presence alone implies conventional
                return "conventional"
            except Exception:
                return "conventional"

    # Check package.json for commitlint config
    pkg_path = root / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
            if "commitlint" in pkg:
                return "conventional"
            # Also check devDependencies for commitlint
            deps = {**pkg.get("devDependencies", {}), **pkg.get("dependencies", {})}
            if any("commitlint" in dep for dep in deps):
                return "conventional"
        except Exception:
            pass

    # Fall back to git log analysis
    try:
        out = subprocess.run(
            ["git", "log", "-n", "10", "--pretty=%s"], cwd=root, text=True, capture_output=True, timeout=2
        )
        if out.returncode == 0 and re.search(
            r"^(feat|fix|chore|docs|refactor|style|test|ci|perf|build)(\(.+\))?:", out.stdout, re.M
        ):
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
        "commands": _detect_commands(root),
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
