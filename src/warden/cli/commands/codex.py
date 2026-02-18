"""
Codex Integration (lightweight) for Warden

Generates a small manifest under .agent/codex.json that points Codex to
project context, configuration and reports. This is file-based and does
not require MCP.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

console = Console()

codex_app = typer.Typer(name="codex", help="Codex (file-based) integration helpers", no_args_is_help=True)


@codex_app.command("init")
def codex_init() -> None:
    """
    Create .agent/codex.json manifest pointing to important Warden resources.
    """
    root = Path.cwd()
    agent_dir = root / ".agent"
    agent_dir.mkdir(exist_ok=True)
    manifest_path = agent_dir / "codex.json"

    if manifest_path.exists():
        console.print("[dim]Codex manifest already exists — skipped.[/dim]")
        return

    manifest = {
        "name": "Warden Codex Integration",
        "version": 1,
        "resources": {
            "context": str(Path(".warden/context.yaml")),
            "config": str(Path(".warden/config.yaml")),
            "report_json": str(Path(".warden/reports/warden-report.json")),
            "report_sarif": str(Path(".warden/reports/warden-report.sarif")),
        },
        "protocol": {
            "verify_loop": ["PLAN", "EXECUTE", "VERIFY (warden scan)"]
        },
        "notes": "Codex: Read resources->context first; keep context updated via 'warden context detect'",
    }

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    console.print(f"[green]Created Codex manifest:[/green] {manifest_path}")

