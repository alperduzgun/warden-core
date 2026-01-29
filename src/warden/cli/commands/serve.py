import typer
import asyncio
import json
import shutil
from pathlib import Path
from typing import Optional
from warden.services.ipc_entry import main_async as ipc_main
from warden.services.grpc_entry import main_async as grpc_main

serve_app = typer.Typer(name="serve", help="Start Warden backend services")
mcp_app = typer.Typer(name="mcp", help="MCP (Model Context Protocol) commands", invoke_without_command=True)
serve_app.add_typer(mcp_app, name="mcp")


@mcp_app.callback()
def mcp_callback(ctx: typer.Context):
    """
    MCP (Model Context Protocol) commands for AI assistant integration.

    Without subcommand, starts the MCP server (same as 'warden serve mcp start').
    """
    # If no subcommand provided, run start by default (backward compatibility)
    if ctx.invoked_subcommand is None:
        serve_mcp(project_root=None)

@serve_app.command("ipc")
def serve_ipc():
    """Start the IPC server (used by CLI/GUI integration)."""
    try:
        asyncio.run(ipc_main())
    except KeyboardInterrupt:
        pass

@serve_app.command("grpc")
def serve_grpc(port: int = typer.Option(50051, help="Port to listen on")):
    """Start the gRPC server (for C#/.NET integration)."""
    try:
        asyncio.run(grpc_main(port))
    except KeyboardInterrupt:
        pass

@mcp_app.command("start")
def serve_mcp(
    project_root: Optional[str] = typer.Option(
        None,
        "--project-root",
        "-p",
        help="Project root directory (default: current directory)",
    ),
):
    """
    Start the MCP server for AI assistant integration (STDIO transport).

    The MCP (Model Context Protocol) server allows AI assistants like Claude
    to access Warden reports and execute validation tools.

    Resources exposed:
      - warden://reports/sarif - SARIF format scan results
      - warden://reports/json  - JSON format scan results
      - warden://reports/html  - HTML format scan results
      - warden://config        - Warden configuration
      - warden://ai-status     - AI security status

    Tools available:
      - warden_scan       - Run security scan
      - warden_status     - Get Warden status
      - warden_setup_status - Check setup completeness
      - warden_list_frames - List validation frames
    """
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()

    if not root.exists() or not root.is_dir():
        typer.secho(f"Error: Invalid project root: {root}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    from warden.mcp.entry import run as mcp_run
    try:
        mcp_run(str(root))
    except KeyboardInterrupt:
        pass


@mcp_app.command("register")
def mcp_register(
    global_only: bool = typer.Option(
        False,
        "--global",
        "-g",
        help="Only register globally (skip project-specific registration)",
    ),
):
    """
    Register Warden MCP server with AI tools (Claude, Cursor, Gemini, etc.).

    This command configures AI coding assistants to use Warden's MCP server,
    enabling automatic security scanning and setup detection.

    Run this after installing Warden to enable AI assistant integration.

    Supported tools:
      - Claude Desktop (macOS/Windows)
      - Claude Code CLI
      - Cursor
      - Windsurf
      - Gemini (Antigravity)
    """
    from rich.console import Console
    console = Console()

    console.print("\n[bold cyan]🔗 Registering Warden MCP Server[/bold cyan]\n")

    # Find warden executable path
    warden_path = shutil.which("warden")
    if not warden_path:
        # Try common installation paths
        common_paths = [
            Path("/opt/homebrew/bin/warden"),
            Path("/usr/local/bin/warden"),
            Path.home() / ".local" / "bin" / "warden",
            Path.home() / ".cargo" / "bin" / "warden",
        ]
        for p in common_paths:
            if p.exists():
                warden_path = str(p)
                break

    if not warden_path:
        warden_path = "warden"
        console.print("[yellow]Warning: Could not find warden in PATH. Using 'warden' as command.[/yellow]")

    # MCP config entry (global - no project root)
    mcp_global_config = {
        "command": warden_path,
        "args": ["serve", "mcp", "start"],
    }

    # AI tool config file locations
    config_locations = {
        "Claude Desktop (macOS)": Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        "Claude Desktop (Windows)": Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json",
        "Claude Desktop (Linux)": Path.home() / ".config" / "Claude" / "claude_desktop_config.json",
        "Claude Code CLI": Path.home() / ".config" / "claude-code" / "mcp_settings.json",
        "Cursor": Path.home() / ".cursor" / "mcp.json",
        "Windsurf": Path.home() / ".windsurf" / "mcp.json",
        "Gemini (Antigravity)": Path.home() / ".gemini" / "antigravity" / "mcp_config.json",
    }

    registered_count = 0
    skipped_count = 0

    for tool_name, config_path in config_locations.items():
        # Create parent directory if it doesn't exist
        if not config_path.parent.exists():
            # Only create if this is a reasonable location (user config dirs)
            if ".config" in str(config_path) or "Application Support" in str(config_path) or "AppData" in str(config_path):
                config_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                continue

        try:
            # Read existing config or create new
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    data = json.loads(content) if content else {}
            else:
                data = {}

            # Ensure mcpServers key exists
            if "mcpServers" not in data:
                data["mcpServers"] = {}

            # Check if already registered with same config
            existing = data["mcpServers"].get("warden")
            if existing and existing.get("command") == warden_path:
                console.print(f"  [dim]• {tool_name}: Already registered[/dim]")
                skipped_count += 1
                continue

            # Register Warden
            data["mcpServers"]["warden"] = mcp_global_config

            # Write config
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            console.print(f"  [green]✓ {tool_name}[/green]: {config_path}")
            registered_count += 1

        except PermissionError:
            console.print(f"  [red]✗ {tool_name}[/red]: Permission denied")
        except json.JSONDecodeError:
            console.print(f"  [yellow]! {tool_name}[/yellow]: Invalid JSON, skipped")
        except Exception as e:
            console.print(f"  [red]✗ {tool_name}[/red]: {e}")

    # Summary
    console.print()
    if registered_count > 0:
        console.print(f"[bold green]✨ Registered with {registered_count} AI tool(s)[/bold green]")
    if skipped_count > 0:
        console.print(f"[dim]Skipped {skipped_count} (already configured)[/dim]")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Restart your AI coding tool (Claude, Cursor, etc.)")
    console.print("  2. The AI will now have access to Warden via MCP")
    console.print("  3. Run 'warden init' in your project for full integration")
    console.print()


@mcp_app.command("status")
def mcp_status():
    """
    Check MCP registration status across AI tools.
    """
    from rich.console import Console
    from rich.table import Table
    console = Console()

    console.print("\n[bold cyan]🔍 Warden MCP Registration Status[/bold cyan]\n")

    config_locations = {
        "Claude Desktop (macOS)": Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        "Claude Desktop (Linux)": Path.home() / ".config" / "Claude" / "claude_desktop_config.json",
        "Claude Code CLI": Path.home() / ".config" / "claude-code" / "mcp_settings.json",
        "Cursor": Path.home() / ".cursor" / "mcp.json",
        "Windsurf": Path.home() / ".windsurf" / "mcp.json",
        "Gemini": Path.home() / ".gemini" / "antigravity" / "mcp_config.json",
    }

    table = Table(show_header=True, header_style="bold")
    table.add_column("AI Tool")
    table.add_column("Status")
    table.add_column("Config Path")

    for tool_name, config_path in config_locations.items():
        if not config_path.exists():
            table.add_row(tool_name, "[dim]Not installed[/dim]", str(config_path))
            continue

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if "mcpServers" in data and "warden" in data["mcpServers"]:
                table.add_row(tool_name, "[green]✓ Registered[/green]", str(config_path))
            else:
                table.add_row(tool_name, "[yellow]Not registered[/yellow]", str(config_path))
        except Exception:
            table.add_row(tool_name, "[red]Error reading[/red]", str(config_path))

    console.print(table)
    console.print("\n[dim]Run 'warden serve mcp register' to register Warden with AI tools.[/dim]\n")
