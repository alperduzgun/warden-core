
import asyncio
import json
import os
import structlog
from typing import Optional, Dict, Any, Callable, List

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

    async def start_async(self):
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
            self._reader_task = asyncio.create_task(self._read_loop_async())
            logger.info("lsp_started", pid=self.process.pid)
            
        except Exception as e:
            logger.error("lsp_start_failed", error=str(e))
            raise

    async def initialize_async(self, root_path: str) -> Dict[str, Any]:
        """Send initialize request."""
        params = {
            "processId": os.getpid(),
            "rootUri": f"file://{root_path}",
            "capabilities": {
                "textDocument": {
                    "synchronization": {"dynamicRegistration": False, "willSave": False, "didSave": False},
                    "references": {"dynamicRegistration": False},
                    "publishDiagnostics": {"relatedInformation": True},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                    # Call Hierarchy support
                    "callHierarchy": {"dynamicRegistration": False},
                    # Type Hierarchy support
                    "typeHierarchy": {"dynamicRegistration": False},
                    # Hover support (for type info)
                    "hover": {
                        "dynamicRegistration": False,
                        "contentFormat": ["markdown", "plaintext"]
                    }
                },
                "workspace": {
                    "configuration": True,
                    # Workspace Symbols support
                    "symbol": {
                        "dynamicRegistration": False,
                        "symbolKind": {
                            "valueSet": list(range(1, 27))  # All symbol kinds
                        }
                    }
                }
            },
            "initializationOptions": {}
        }
        return await self.send_request_async("initialize", params)

    async def shutdown_async(self):
        """Graceful shutdown."""
        if not self.process: return
        
        try:
            logger.info("lsp_shutting_down")
            await self.send_request_async("shutdown", {})
            await self.send_notification_async("exit", {})
            
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

    async def send_request_async(self, method: str, params: Any) -> Any:
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
            await self._write_message_async(request)
            # Timeout safety
            return await asyncio.wait_for(future, timeout=30.0)  # 30s for large projects
        except asyncio.TimeoutError:
            del self._pending_requests[req_id]
            logger.error("lsp_request_timeout", method=method, id=req_id)
            raise
        except Exception:
            if req_id in self._pending_requests:
                del self._pending_requests[req_id]
            raise

    async def send_notification_async(self, method: str, params: Any):
        """Send a fire-and-forget notification."""
        if not self.process: return

        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        await self._write_message_async(msg)

    # ============================================================
    # Semantic LSP Methods (for OrphanFrame integration)
    # ============================================================

    async def open_document_async(self, file_path: str, language_id: str, content: str) -> None:
        """
        Open a document in the language server.

        Must be called before find_references or get_symbols.
        Idempotent: safe to call multiple times for same file.
        """
        uri = f"file://{file_path}"
        await self.send_notification_async("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": language_id,
                "version": 1,
                "text": content
            }
        })
        logger.debug("lsp_document_opened", uri=uri, language=language_id)

    async def close_document_async(self, file_path: str) -> None:
        """Close a document in the language server."""
        uri = f"file://{file_path}"
        await self.send_notification_async("textDocument/didClose", {
            "textDocument": {"uri": uri}
        })

    async def find_references_async(
        self,
        file_path: str,
        line: int,
        character: int,
        include_declaration: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Find all references to symbol at position.

        Args:
            file_path: Absolute path to file
            line: 0-indexed line number
            character: 0-indexed character position
            include_declaration: Include the declaration itself

        Returns:
            List of Location objects: [{"uri": "file://...", "range": {...}}]
        """
        uri = f"file://{file_path}"
        try:
            result = await self.send_request_async("textDocument/references", {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration}
            })
            refs = result or []
            logger.debug("lsp_references_found", uri=uri, line=line, count=len(refs))
            return refs
        except Exception as e:
            logger.warning("lsp_find_references_failed", uri=uri, error=str(e))
            return []

    async def get_document_symbols_async(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Get all symbols in a document.

        Returns:
            List of DocumentSymbol or SymbolInformation objects
        """
        uri = f"file://{file_path}"
        try:
            result = await self.send_request_async("textDocument/documentSymbol", {
                "textDocument": {"uri": uri}
            })
            symbols = result or []
            logger.debug("lsp_symbols_found", uri=uri, count=len(symbols))
            return symbols
        except Exception as e:
            logger.warning("lsp_get_symbols_failed", uri=uri, error=str(e))
            return []

    async def goto_definition_async(
        self,
        file_path: str,
        line: int,
        character: int
    ) -> List[Dict[str, Any]]:
        """
        Go to definition of symbol at position.

        Returns:
            List of Location objects
        """
        uri = f"file://{file_path}"
        try:
            result = await self.send_request_async("textDocument/definition", {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character}
            })
            # Result can be Location, Location[], or LocationLink[]
            if result is None:
                return []
            if isinstance(result, list):
                return result
            return [result]
        except Exception as e:
            logger.warning("lsp_goto_definition_failed", uri=uri, error=str(e))
            return []

    # ============================================================
    # Call Hierarchy (who calls what, what calls who)
    # ============================================================

    async def prepare_call_hierarchy_async(
        self,
        file_path: str,
        line: int,
        character: int
    ) -> List[Dict[str, Any]]:
        """
        Prepare call hierarchy at a position.

        Returns:
            List of CallHierarchyItem objects representing the symbol
        """
        uri = f"file://{file_path}"
        try:
            result = await self.send_request_async("textDocument/prepareCallHierarchy", {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character}
            })
            items = result or []
            logger.debug("lsp_call_hierarchy_prepared", uri=uri, count=len(items))
            return items
        except Exception as e:
            logger.warning("lsp_prepare_call_hierarchy_failed", uri=uri, error=str(e))
            return []

    async def get_incoming_calls_async(
        self,
        call_hierarchy_item: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Get incoming calls (who calls this function).

        Args:
            call_hierarchy_item: Item from prepare_call_hierarchy_async

        Returns:
            List of CallHierarchyIncomingCall objects
        """
        try:
            result = await self.send_request_async("callHierarchy/incomingCalls", {
                "item": call_hierarchy_item
            })
            calls = result or []
            logger.debug("lsp_incoming_calls_found", count=len(calls))
            return calls
        except Exception as e:
            logger.warning("lsp_incoming_calls_failed", error=str(e))
            return []

    async def get_outgoing_calls_async(
        self,
        call_hierarchy_item: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Get outgoing calls (what does this function call).

        Args:
            call_hierarchy_item: Item from prepare_call_hierarchy_async

        Returns:
            List of CallHierarchyOutgoingCall objects
        """
        try:
            result = await self.send_request_async("callHierarchy/outgoingCalls", {
                "item": call_hierarchy_item
            })
            calls = result or []
            logger.debug("lsp_outgoing_calls_found", count=len(calls))
            return calls
        except Exception as e:
            logger.warning("lsp_outgoing_calls_failed", error=str(e))
            return []

    # ============================================================
    # Type Hierarchy (class inheritance)
    # ============================================================

    async def prepare_type_hierarchy_async(
        self,
        file_path: str,
        line: int,
        character: int
    ) -> List[Dict[str, Any]]:
        """
        Prepare type hierarchy at a position.

        Returns:
            List of TypeHierarchyItem objects
        """
        uri = f"file://{file_path}"
        try:
            result = await self.send_request_async("textDocument/prepareTypeHierarchy", {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character}
            })
            items = result or []
            logger.debug("lsp_type_hierarchy_prepared", uri=uri, count=len(items))
            return items
        except Exception as e:
            logger.warning("lsp_prepare_type_hierarchy_failed", uri=uri, error=str(e))
            return []

    async def get_supertypes_async(
        self,
        type_hierarchy_item: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Get supertypes (parent classes/interfaces).

        Returns:
            List of TypeHierarchyItem objects
        """
        try:
            result = await self.send_request_async("typeHierarchy/supertypes", {
                "item": type_hierarchy_item
            })
            types = result or []
            logger.debug("lsp_supertypes_found", count=len(types))
            return types
        except Exception as e:
            logger.warning("lsp_supertypes_failed", error=str(e))
            return []

    async def get_subtypes_async(
        self,
        type_hierarchy_item: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Get subtypes (child classes/implementations).

        Returns:
            List of TypeHierarchyItem objects
        """
        try:
            result = await self.send_request_async("typeHierarchy/subtypes", {
                "item": type_hierarchy_item
            })
            types = result or []
            logger.debug("lsp_subtypes_found", count=len(types))
            return types
        except Exception as e:
            logger.warning("lsp_subtypes_failed", error=str(e))
            return []

    # ============================================================
    # Workspace Symbols (search symbols across project)
    # ============================================================

    async def get_workspace_symbols_async(
        self,
        query: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Search for symbols across the workspace.

        Args:
            query: Search query (empty string returns all symbols)

        Returns:
            List of SymbolInformation objects
        """
        try:
            result = await self.send_request_async("workspace/symbol", {
                "query": query
            })
            symbols = result or []
            logger.debug("lsp_workspace_symbols_found", query=query, count=len(symbols))
            return symbols
        except Exception as e:
            logger.warning("lsp_workspace_symbols_failed", query=query, error=str(e))
            return []

    # ============================================================
    # Hover (type info and documentation)
    # ============================================================

    async def get_hover_async(
        self,
        file_path: str,
        line: int,
        character: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get hover information (type info, docs) at position.

        Returns:
            Hover object with contents and optional range
        """
        uri = f"file://{file_path}"
        try:
            result = await self.send_request_async("textDocument/hover", {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character}
            })
            if result:
                logger.debug("lsp_hover_found", uri=uri, line=line)
            return result
        except Exception as e:
            logger.warning("lsp_hover_failed", uri=uri, error=str(e))
            return None

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

    async def _write_message_async(self, msg: Dict[str, Any]):
        """Encode and write message to stdin."""
        body = json.dumps(msg)
        content = f"Content-Length: {len(body)}\r\n\r\n{body}"
        self.process.stdin.write(content.encode('utf-8'))
        await self.process.stdin.drain()

    async def _read_loop_async(self):
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
