#!/usr/bin/env python3
"""HTTP Server wrapper for Warden CLI Bridge"""

import asyncio
import json
from aiohttp import web
from bridge import WardenBridge
import structlog
from pathlib import Path

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
                # For now, just return a non-streaming result
                result = await self.handle_scan(params)
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

        # Perform scan (bridge.scan doesn't accept frames parameter)
        result = await self.bridge.scan(str(path))

        return result

    async def handle_get_config(self, params):
        """Handle get_config request"""
        try:
            config = self.bridge.get_config()

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