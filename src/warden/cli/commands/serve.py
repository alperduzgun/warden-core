import typer
import asyncio
from warden.services.ipc_entry import main as ipc_main
from warden.services.grpc_entry import main as grpc_main

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
