#!/usr/bin/env python3
"""HTTP Server wrapper for Warden CLI Bridge"""

import asyncio
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from aiohttp import web
from .bridge import WardenBridge
import structlog

import structlog

# Verify credentials using SecretManager (environment-aware)
# This respects the environment: .env for local, env vars for CI/CD, Key Vault for production
async def verify_credentials():
    """Verify Azure OpenAI credentials are available using SecretManager."""
    from warden.secrets import SecretManager
    
    manager = SecretManager()
    
    secrets = await manager.get_secrets([
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
    ])
    
    azure_key = secrets["AZURE_OPENAI_API_KEY"]
    azure_endpoint = secrets["AZURE_OPENAI_ENDPOINT"]
    
    if azure_key.found:
        print(f"✅ Azure OpenAI credentials loaded successfully")
        print(f"   Source: {azure_key.source.value}")
        print(f"   Endpoint: {azure_endpoint.value if azure_endpoint.found else 'not set'}")
        print(f"   Key: {azure_key.value[:10]}...")
    else:
        print("⚠️ Azure OpenAI credentials not found")
        print(f"   Checked sources: {[p.__class__.__name__ for p in manager.providers]}")

# Run verification
import asyncio
asyncio.run(verify_credentials())

logger = structlog.get_logger()

class HTTPServer:
    def __init__(self):
        self.bridge = WardenBridge()
        self.app = web.Application()
        self.setup_routes()

    def setup_routes(self):
        """Setup HTTP routes"""
        self.app.router.add_post('/rpc', self.handle_rpc)
        self.app.router.add_get('/health', self.handle_health)

    async def handle_health(self, request):
        """Health check endpoint"""
        return web.json_response({
            "status": "healthy",
            "service": "warden-backend",
            "version": "2.0.0"
        })

    async def handle_rpc(self, request):
        """Handle JSON-RPC requests"""
        try:
            data = await request.json()
            method = data.get('method')
            params = data.get('params', {})
            request_id = data.get('id')

            logger.info("rpc_request_received", method=method, params=params)

            # Handle different methods
            if method == 'scan':
                result = await self.handle_scan(params)
            elif method == 'get_config':
                result = await self.handle_get_config(params)
            elif method == 'execute_pipeline_stream':
                # Handle streaming via SSE
                return await self.handle_stream(request, params)
            else:
                return web.json_response({
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    },
                    "id": request_id
                })

            return web.json_response({
                "jsonrpc": "2.0",
                "result": result,
                "id": request_id
            })

        except Exception as e:
            logger.error("rpc_error", error=str(e))
            return web.json_response({
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": str(e)
                },
                "id": data.get('id')
            })

    async def handle_stream(self, request, params):
        """Handle streaming pipeline execution via Server-Sent Events"""
        response = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Access-Control-Allow-Origin': '*',
            }
        )
        await response.prepare(request)

        path = params.get('path')
        if not path:
            error_msg = json.dumps({'error': 'Path is required'})
            await response.write(f"event: error\ndata: {error_msg}\n\n".encode('utf-8'))
            return response

        # Resolve path
        path = Path(path).resolve()
        if not path.exists():
            # Try relative to project root
            project_root = Path.cwd()
            path = project_root / params.get('path')
            if not path.exists():
                error_msg = json.dumps({'error': f'File not found: {params.get("path")}'})
                await response.write(f"event: error\ndata: {error_msg}\n\n".encode('utf-8'))
                return response

        logger.info("streaming_pipeline", path=str(path))

        # Prepare frames list
        frames = params.get('frames')

        try:
            # Execute pipeline with streaming
            async for event in self.bridge.execute_pipeline_stream(str(path), frames=frames):
                # Send SSE event
                event_type = event.get('type', 'progress')
                event_data = json.dumps(event)
                await response.write(f"event: {event_type}\ndata: {event_data}\n\n".encode('utf-8'))
                await response.drain()  # Ensure data is sent immediately

            # Send complete event
            await response.write(b"event: complete\ndata: {\"status\": \"completed\"}\n\n")

        except Exception as e:
            logger.error("stream_error", error=str(e))
            error_data = json.dumps({"error": str(e)})
            await response.write(f"event: error\ndata: {error_data}\n\n".encode('utf-8'))

        finally:
            await response.write_eof()

        return response

    async def handle_scan(self, params):
        """Handle scan request"""
        path = params.get('path')
        frames = params.get('frames')

        # Resolve path
        if not path:
            raise ValueError("Path is required")

        path = Path(path).resolve()
        if not path.exists():
            # Try relative to project root
            project_root = Path.cwd()
            path = project_root / params.get('path')
            if not path.exists():
                raise FileNotFoundError(f"File not found: {params.get('path')}")

        logger.info("scanning_file", path=str(path), frames=frames)

        # Perform scan
        result = await self.bridge.scan(str(path), frames=frames)

        return result

    async def handle_get_config(self, params):
        """Handle get_config request"""
        try:
            config = await self.bridge.get_config()

            # Extract available frames
            frames_available = []
            if config and 'frames' in config:
                # Get all configured frames
                for frame in config.get('frames', []):
                    frames_available.append(frame)

            # Also check frames_config for enabled frames
            frames_config = config.get('frames_config', {})
            for frame_id, frame_cfg in frames_config.items():
                if frame_cfg.get('enabled', False) and frame_id not in frames_available:
                    frames_available.append(frame_id)

            return {
                "config": config,
                "frames_available": frames_available,
                "project": config.get('project', {}),
                "llm": config.get('llm', {})
            }
        except Exception as e:
            logger.error("config_error", error=str(e))
            return {
                "config": {},
                "frames_available": ['security', 'chaos', 'orphan'],
                "error": str(e)
            }

    async def start(self, host='localhost', port=6173):
        """Start the HTTP server"""
        logger.info("http_server_starting", host=host, port=port)

        # Bridge is already initialized in __init__

        # Start HTTP server
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()

        logger.info("http_server_started", url=f"http://{host}:{port}")

        # Keep server running
        try:
            await asyncio.Future()  # Run forever
        except KeyboardInterrupt:
            logger.info("http_server_stopping")
            await runner.cleanup()

async def main():
    """Main entry point"""
    server = HTTPServer()
    await server.start()

if __name__ == "__main__":
    # Configure logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    asyncio.run(main())