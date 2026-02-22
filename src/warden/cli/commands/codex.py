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
        "protocol": {"verify_loop": ["PLAN", "EXECUTE", "VERIFY (warden scan)"]},
        "notes": "Codex: Read resources->context first; keep context updated via 'warden context detect'",
    }

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    console.print(f"[green]Created Codex manifest:[/green] {manifest_path}")
    console.print("[dim]Tip: run 'warden codex mcp-setup' to register Warden as an MCP tool in Codex.[/dim]")


@codex_app.command("mcp-setup")
def codex_mcp_setup() -> None:
    """
    Register Warden as an MCP server in ~/.codex/config.toml.

    After setup, Codex will have access to all Warden tools (scan, suppression,
    configuration, etc.) via the MCP protocol.
    """
    import shutil as _shutil

    from warden.mcp.domain.services.mcp_registration_service import MCPRegistrationService
    from warden.mcp.infrastructure.mcp_config_paths import get_mcp_config_paths

    warden_path = _shutil.which("warden") or "warden"
    codex_config = get_mcp_config_paths().get("Codex")

    if codex_config is None:
        console.print("[red]Could not determine Codex config path.[/red]")
        raise SystemExit(1)

    service = MCPRegistrationService(warden_path)
    result = service._register_single_tool("Codex", codex_config, {})

    if result.status == "registered":
        console.print(f"[green]✓ Warden registered in Codex MCP:[/green] {codex_config}")
        console.print("[dim]Start the MCP server with: warden serve mcp start[/dim]")
    elif result.status == "skipped":
        console.print(f"[dim]Already registered in {codex_config}[/dim]")
    else:
        console.print(f"[red]✗ Registration failed:[/red] {result.message}")
        raise SystemExit(1)
