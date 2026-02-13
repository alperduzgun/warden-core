
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from warden.lsp import LSPManager
from warden.validation.domain.frame import CodeFile

logger = structlog.get_logger()

class LSPDiagnosticsAnalyzer:
    """
    Analyzer that captures compiler-grade diagnostics from LSP servers.
    """

    def __init__(self):
        pass

    async def analyze_async(
        self,
        code_file: CodeFile,
        ast_tree: Any | None = None
    ) -> dict[str, Any]:
        """
        Analyze file using LSP for diagnostics.
        """
        path = Path(code_file.path)

        # Determine language
        language = None
        if path.suffix == ".py": language = "python"
        elif path.suffix in [".ts", ".tsx"]: language = "typescript"
        elif path.suffix in [".js", ".jsx"]: language = "javascript"

        if not language:
            return {"diagnostics": [], "score": 10.0}

        try:
            lsp_manager = LSPManager.get_instance()
            # Need project root for LSP. Assuming 2 levels up for now or cwd
            client = await lsp_manager.get_client_async(language, str(path.cwd()))

            if not client:
                return {"diagnostics": [], "score": 10.0}

            uri = f"file://{code_file.path}"

            # Setup event to wait for diagnostics
            import asyncio
            diagnostics = []
            diagnostics_received = asyncio.Event()

            def handle_diagnostics(params):
                if params and params['uri'] == uri:
                    diagnostics.extend(params['diagnostics'])
                    diagnostics_received.set()

            client.on_notification("textDocument/publishDiagnostics", handle_diagnostics)

            try:
                # Open file (if not already)
                await client.send_notification_async("textDocument/didOpen", {
                    "textDocument": {
                        "uri": uri,
                        "languageId": language,
                        "version": 1,
                        "text": path.read_text() # TODO: Pass content from CodeFile if in memory
                    }
                })

                # Wait for diagnostics notification with timeout
                # LSP servers typically send diagnostics within 1-2 seconds
                try:
                    await asyncio.wait_for(diagnostics_received.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    logger.debug("lsp_diagnostics_timeout", file=code_file.path, language=language)
                    # Continue with empty diagnostics if no response

                # Calculate score based on errors
                error_count = len([d for d in diagnostics if d.get('severity') == 1])
                warning_count = len([d for d in diagnostics if d.get('severity') == 2])

                # Simple scoring: Start at 10, deduct for errors
                score = max(0.0, 10.0 - (error_count * 2.0) - (warning_count * 0.5))

                return {
                    "diagnostics": diagnostics,
                    "score": score,
                    "error_count": error_count,
                    "warning_count": warning_count
                }
            finally:
                # Cleanup handler to prevent memory leak
                client.remove_notification_handler("textDocument/publishDiagnostics", handle_diagnostics)

        except Exception as e:
            logger.error("lsp_analyzer_failed", error=str(e), file=code_file.path)
            return {"diagnostics": [], "score": 10.0, "error": str(e)}
