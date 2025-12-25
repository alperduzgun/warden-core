#!/usr/bin/env python3
"""
Start Warden gRPC Server

Usage:
    python start_grpc_server.py [--port 50051]

This server enables C# Panel and other clients to communicate
with the Warden Python backend via gRPC.
"""

import asyncio
import argparse
import signal
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from warden.grpc.server import GrpcServer


async def main(port: int = 50051):
    """Main entry point."""
    print(f"""
================================================================================
                         Warden gRPC Server
================================================================================

   Port:      {port}
   Protocol:  gRPC + Protocol Buffers
   For:       C# Panel, .NET clients

================================================================================
    """)

    server = GrpcServer(port=port, project_root=Path.cwd())

    # Handle shutdown signals
    loop = asyncio.get_running_loop()

    def shutdown_handler():
        print("\nShutting down gRPC server...")
        asyncio.create_task(server.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown_handler)

    try:
        await server.start()
        print(f"Server listening on localhost:{port}")
        print("Press Ctrl+C to stop\n")
        await server.wait_for_termination()
    except KeyboardInterrupt:
        await server.stop()
        print("Server stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start Warden gRPC Server")
    parser.add_argument("--port", type=int, default=50051, help="Port to listen on")
    args = parser.parse_args()

    asyncio.run(main(args.port))
