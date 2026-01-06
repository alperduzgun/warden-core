
import asyncio
import json
import os
import structlog
from typing import Optional, Dict, Any, Callable
from abc import ABC, abstractmethod

logger = structlog.get_logger()

class LanguageServerClient:
    """
    Robust JSON-RPC Client over Stdio for communicating with Language Servers.
    
    Features:
    - Async/Await Request/Response matching.
    - Notification handling via callbacks.
    - Content-Length header parsing.
    - Fail-fast process management.
    """
    
    def __init__(self, binary_path: str, args: list[str], cwd: str):
        self.binary_path = binary_path
        self.args = args
        self.cwd = cwd
        self.process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._notification_handlers: Dict[str, list[Callable]] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Start the language server subprocess."""
        try:
            full_cmd = [self.binary_path] + self.args
            logger.info("lsp_starting", cmd=full_cmd, cwd=self.cwd)
            
            self.process = await asyncio.create_subprocess_exec(
                *full_cmd,
                cwd=self.cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Start background reader
            self._reader_task = asyncio.create_task(self._read_loop())
            logger.info("lsp_started", pid=self.process.pid)
            
        except Exception as e:
            logger.error("lsp_start_failed", error=str(e))
            raise

    async def initialize(self, root_path: str) -> Dict[str, Any]:
        """Send initialize request."""
        params = {
            "processId": os.getpid(),
            "rootUri": f"file://{root_path}",
            "capabilities": {
                "textDocument": {
                    "synchronization": {"dynamicRegistration": False, "willSave": False, "didSave": False},
                    "references": {"dynamicRegistration": False},
                    "publishDiagnostics": {"relatedInformation": True},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True}
                },
                "workspace": {
                    "configuration": True
                }
            },
            "initializationOptions": {}
        }
        return await self.send_request("initialize", params)

    async def shutdown(self):
        """Graceful shutdown."""
        if not self.process: return
        
        try:
            logger.info("lsp_shutting_down")
            await self.send_request("shutdown", {})
            self._send_notification("exit", {})
            
            # Cancel reader
            if self._reader_task:
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except asyncio.CancelledError:
                    pass
            
            if self.process.returncode is None:
                self.process.terminate()
                await self.process.wait()
                
            logger.info("lsp_stopped")
            
        except Exception as e:
            logger.error("lsp_shutdown_error", error=str(e))
            # Force kill if needed
            if self.process and self.process.returncode is None:
                self.process.kill()

    async def send_request(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request and await result."""
        if not self.process or self.process.stdin.is_closing():
            raise RuntimeError("LSP process is not running")

        self._request_id += 1
        req_id = self._request_id
        
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }
        
        # Create future for response
        future = asyncio.Future()
        self._pending_requests[req_id] = future
        
        try:
            await self._write_message(request)
            # Timeout safety
            return await asyncio.wait_for(future, timeout=10.0) # 10s default timeout
        except asyncio.TimeoutError:
            del self._pending_requests[req_id]
            logger.error("lsp_request_timeout", method=method, id=req_id)
            raise
        except Exception as e:
            if req_id in self._pending_requests:
                del self._pending_requests[req_id]
            raise

    def _send_notification(self, method: str, params: Any):
        """Send a fire-and-forget notification."""
        if not self.process: return
        
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        asyncio.create_task(self._write_message(msg))

    def on_notification(self, method: str, handler: Callable):
        """Register a handler for a notification method."""
        if method not in self._notification_handlers:
            self._notification_handlers[method] = []
        self._notification_handlers[method].append(handler)

    def remove_notification_handler(self, method: str, handler: Callable):
        """Remove a registered handler."""
        if method in self._notification_handlers:
            try:
                self._notification_handlers[method].remove(handler)
            except ValueError:
                pass

    async def _write_message(self, msg: Dict[str, Any]):
        """Encode and write message to stdin."""
        body = json.dumps(msg)
        content = f"Content-Length: {len(body)}\r\n\r\n{body}"
        self.process.stdin.write(content.encode('utf-8'))
        await self.process.stdin.drain()

    async def _read_loop(self):
        """Continuous loop reading messages from stdout."""
        try:
            while True:
                # 1. Read Headers
                content_length = 0
                while True:
                    line = await self.process.stdout.readline()
                    if not line: raise EOFError("LSP process closed stdout")
                    
                    line = line.decode('utf-8').strip()
                    if not line: break # End of headers
                    
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":")[1].strip())
                
                # 2. Read Body
                if content_length > 0:
                    body_bytes = await self.process.stdout.readexactly(content_length)
                    msg = json.loads(body_bytes.decode('utf-8'))
                    self._handle_message(msg)
                    
        except asyncio.CancelledError:
            pass
        except EOFError:
            logger.warning("lsp_process_eof")
        except Exception as e:
            logger.error("lsp_read_loop_error", error=str(e))
        finally:
            if self.process and self.process.returncode is None:
                logger.info("lsp_process_unexpectedly_terminated")

    def _handle_message(self, msg: Dict[str, Any]):
        """Dispatcher for incoming messages."""
        # Response
        if "id" in msg and "method" not in msg:
            req_id = msg["id"]
            if req_id in self._pending_requests:
                if "error" in msg:
                    self._pending_requests[req_id].set_exception(
                        RuntimeError(f"LSP Error: {msg['error']}")
                    )
                else:
                    self._pending_requests[req_id].set_result(msg.get("result"))
                del self._pending_requests[req_id]
            else:
                logger.debug("lsp_unknown_response_id", id=req_id)
        
        # Notification or Request from Server
        elif "method" in msg:
            if "id" in msg:
                # Server Request (e.g. workspace/configuration) - Not responding yet
                logger.debug("lsp_server_request_ignored", method=msg["method"])
            else:
                # Notification
                handlers = self._notification_handlers.get(msg["method"], [])
                for handler in handlers:
                    try:
                        handler(msg.get("params"))
                    except Exception as e:
                        logger.error("lsp_notification_handler_error", error=str(e))
