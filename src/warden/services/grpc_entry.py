"""
Warden gRPC Server Service
=========================

Launched via: python -m warden.services.grpc_entry
"""

import asyncio
import argparse
import signal
import sys
from pathlib import Path

# Absolute imports
from warden.grpc.server import GrpcServer


async def main(port: int = 50051):
    """Main entry point."""
    print(f"""
================================================================================
                         Warden gRPC Server (Service Mode)
================================================================================

   Port:      {port}
   Protocol:  gRPC + Protocol Buffers
   For:       C# Panel, .NET clients

================================================================================
    """)

    # Project root calculation (up 3 levels from services/grpc_entry.py)
    project_root = Path(__file__).parents[3]
    
    server = GrpcServer(port=port, project_root=project_root)

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
