import typer
import asyncio
from typing import Optional
from warden.services.ipc_entry import main_async as ipc_main
from warden.services.grpc_entry import main_async as grpc_main

serve_app = typer.Typer(name="serve", help="Start Warden backend services")

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

@serve_app.command("mcp")
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
      - warden_list_frames - List validation frames
    """
    from pathlib import Path
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    
    if not root.exists() or not root.is_dir():
        typer.secho(f"Error: Invalid project root: {root}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    from warden.mcp.entry import run as mcp_run
    try:
        mcp_run(str(root))
    except KeyboardInterrupt:
        pass
