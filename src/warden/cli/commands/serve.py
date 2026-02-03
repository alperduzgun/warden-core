import typer
import asyncio
import json
import shutil
import tempfile
import os
from pathlib import Path
from typing import Optional

from warden.services.ipc_entry import main_async as ipc_main
from warden.services.grpc_entry import main_async as grpc_main
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

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
def mcp_register():
    """
    Register Warden MCP server with AI tools (Claude, Cursor, Gemini, etc.).

    This command configures AI coding assistants to use Warden's MCP server,
    enabling automatic security scanning and setup detection.

    Run this after installing Warden to enable AI assistant integration.

    Supported tools:
      - Claude Desktop (macOS/Windows/Linux)
      - Claude Code CLI
      - Cursor
      - Windsurf
      - Gemini (Antigravity)
    """
    from rich.console import Console
    from warden.mcp.infrastructure.mcp_config_paths import (
        get_mcp_config_paths,
        is_safe_to_create_dir,
    )

    console = Console()
    logger.info("mcp_register_started")

    console.print("\n[bold cyan]🔗 Registering Warden MCP Server[/bold cyan]\n")

    # Find warden executable path (fail fast if not found)
    warden_path = _find_warden_executable()
    if not warden_path:
        warden_path = "warden"
        logger.warning("mcp_register_warden_not_in_path", fallback="warden")
        console.print("[yellow]Warning: Could not find warden in PATH. Using 'warden' as command.[/yellow]")

    # MCP config entry (idempotent - same config every time)
    mcp_global_config = {
        "command": warden_path,
        "args": ["serve", "mcp", "start"],
    }

    # Get config locations from centralized source (DRY)
    config_locations = get_mcp_config_paths()

    registered_count = 0
    skipped_count = 0
    error_count = 0

    for tool_name, config_path in config_locations.items():
        result = _register_mcp_for_tool(
            tool_name=tool_name,
            config_path=config_path,
            mcp_config=mcp_global_config,
            warden_path=warden_path,
            console=console,
        )

        if result == "registered":
            registered_count += 1
        elif result == "skipped":
            skipped_count += 1
        else:
            error_count += 1

    # Summary with structural logging
    logger.info(
        "mcp_register_completed",
        registered=registered_count,
        skipped=skipped_count,
        errors=error_count,
    )

    console.print()
    if registered_count > 0:
        console.print(f"[bold green]✨ Registered with {registered_count} AI tool(s)[/bold green]")
    if skipped_count > 0:
        console.print(f"[dim]Skipped {skipped_count} (already configured)[/dim]")
    if error_count > 0:
        console.print(f"[yellow]Failed: {error_count} (check logs for details)[/yellow]")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Restart your AI coding tool (Claude, Cursor, etc.)")
    console.print("  2. The AI will now have access to Warden via MCP")
    console.print("  3. Run 'warden init' in your project for full integration")
    console.print()


def _find_warden_executable() -> Optional[str]:
    """
    Find the warden executable path.

    Returns:
        Absolute path to warden executable, or None if not found.
    """
    # First try PATH
    warden_path = shutil.which("warden")
    if warden_path:
        return warden_path

    # Try common installation paths
    common_paths = [
        Path("/opt/homebrew/bin/warden"),
        Path("/usr/local/bin/warden"),
        Path.home() / ".local" / "bin" / "warden",
        Path.home() / ".cargo" / "bin" / "warden",
    ]
    for p in common_paths:
        if p.exists():
            return str(p)

    return None


def _register_mcp_for_tool(
    tool_name: str,
    config_path: Path,
    mcp_config: dict,
    warden_path: str,
    console,
) -> str:
    """
    Register Warden MCP for a single AI tool using the domain service.
    
    Args:
        tool_name: Display name of the tool
        config_path: Path to the tool's MCP config file
        mcp_config: MCP configuration dict (unused here, kept for signature compat if needed, 
                   but service constructs its own)
        warden_path: Path to warden executable
        console: Rich console for output

    Returns:
        "registered", "skipped", or "error"
    """
    from warden.mcp.domain.services.mcp_registration_service import MCPRegistrationService
    
    # Initialize service
    service = MCPRegistrationService(warden_path)
    
    # Call service to register single tool (service method needs to be exposed or we use register_all)
    # Since existing architecture iterates, we expose the single registration logic via the service
    # or better, refactor the caller.
    # For minimum friction, we'll use the service's internal method if accessible, 
    # or instantiate the service and call the public method for this specific tool.
    
    # Actually, the loop is in the caller `mcp_register`. 
    # Let's adapt this function to use the service.
    
    result = service._register_single_tool(tool_name, config_path, mcp_config)
    
    if result.status == "registered":
        logger.info("mcp_register_success", tool=tool_name, path=str(config_path))
        console.print(f"  [green]✓ {tool_name}[/green]: {config_path}")
        return "registered"
        
    elif result.status == "skipped":
        logger.debug("mcp_register_skipped", tool=tool_name, reason=result.message)
        console.print(f"  [dim]• {tool_name}: {result.message}[/dim]")
        return "skipped"
        
    else: # error
        logger.error("mcp_register_failed", tool=tool_name, error=result.message)
        console.print(f"  [red]✗ {tool_name}[/red]: {result.message}")
        return "error"


def _read_mcp_config_safe(config_path: Path, tool_name: str, console) -> dict:
    """
    Safely read MCP config file with backup on corruption.

    Args:
        config_path: Path to config file
        tool_name: Tool name for logging
        console: Rich console for output

    Returns:
        Parsed config dict (empty dict if file doesn't exist or is corrupt)
    """
    if not config_path.exists():
        return {}

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return {}
            parsed = json.loads(content)
            # Type safety: ensure we got a dict
            return parsed if isinstance(parsed, dict) else {}

    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # Backup corrupted file (self-healing)
        backup_path = config_path.parent / f"{config_path.stem}.backup{config_path.suffix}"
        try:
            shutil.copy2(config_path, backup_path)
            logger.warning(
                "mcp_register_corrupted_config_backed_up",
                tool=tool_name,
                backup=str(backup_path),
                error=str(e),
            )
            console.print(f"  [yellow]! {tool_name}: Backed up corrupted config to {backup_path.name}[/yellow]")
        except OSError:
            logger.warning("mcp_register_backup_failed", tool=tool_name)
        return {}


def _write_mcp_config_atomic(config_path: Path, data: dict) -> None:
    """
    Atomically write MCP config file.

    Uses temp file + rename pattern for crash safety.

    Args:
        config_path: Target config file path
        data: Config data to write

    Raises:
        OSError: If write fails
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        dir=config_path.parent,
        prefix='.mcp_',
        suffix='.tmp'
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        # Atomic rename (POSIX compliant)
        os.replace(temp_path, config_path)
        logger.debug("mcp_config_written", path=str(config_path))
    except Exception:
        # Clean up temp file on failure (dispose properly)
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _verify_mcp_registration(config_path: Path, expected_command: str) -> bool:
    """
    Verify MCP registration was successful.

    Args:
        config_path: Config file to verify
        expected_command: Expected warden command path

    Returns:
        True if verification passes, False otherwise
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        warden_config = data.get("mcpServers", {}).get("warden", {})
        return warden_config.get("command") == expected_command
    except Exception:
        return False


@mcp_app.command("status")
def mcp_status():
    """
    Check MCP registration status across AI tools.
    """
    from rich.console import Console
    from rich.table import Table
    from warden.mcp.infrastructure.mcp_config_paths import get_mcp_config_paths

    console = Console()
    logger.info("mcp_status_check_started")

    console.print("\n[bold cyan]🔍 Warden MCP Registration Status[/bold cyan]\n")

    # Use centralized config paths (DRY)
    config_locations = get_mcp_config_paths()

    table = Table(show_header=True, header_style="bold")
    table.add_column("AI Tool")
    table.add_column("Status")
    table.add_column("Config Path")

    registered_count = 0
    not_registered_count = 0

    for tool_name, config_path in config_locations.items():
        if not config_path.exists():
            table.add_row(tool_name, "[dim]Not installed[/dim]", str(config_path))
            continue

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Type-safe check
            mcp_servers = data.get("mcpServers") if isinstance(data, dict) else None
            if isinstance(mcp_servers, dict) and "warden" in mcp_servers:
                table.add_row(tool_name, "[green]✓ Registered[/green]", str(config_path))
                registered_count += 1
            else:
                table.add_row(tool_name, "[yellow]Not registered[/yellow]", str(config_path))
                not_registered_count += 1

        except json.JSONDecodeError as e:
            logger.warning("mcp_status_json_error", tool=tool_name, error=str(e))
            table.add_row(tool_name, "[red]Invalid JSON[/red]", str(config_path))
        except OSError as e:
            logger.warning("mcp_status_read_error", tool=tool_name, error=str(e))
            table.add_row(tool_name, "[red]Read error[/red]", str(config_path))

    logger.info("mcp_status_check_completed", registered=registered_count, not_registered=not_registered_count)

    console.print(table)
    console.print("\n[dim]Run 'warden serve mcp register' to register Warden with AI tools.[/dim]\n")
