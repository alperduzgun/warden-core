
import structlog
from typing import Dict, Any, Optional
from pathlib import Path
from warden.validation.domain.frame import CodeFile
from warden.lsp import LSPManager

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
        ast_tree: Optional[Any] = None
    ) -> Dict[str, Any]:
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
            client = await lsp_manager.get_client(language, str(path.cwd()))
            
            if not client:
                return {"diagnostics": [], "score": 10.0}

            uri = f"file://{code_file.path}"
            
            # Open file (if not already)
            await client.send_notification("textDocument/didOpen", {
                "textDocument": {
                    "uri": uri,
                    "languageId": language,
                    "version": 1,
                    "text": path.read_text() # TODO: Pass content from CodeFile if in memory
                }
            })
            
            # Wait for diagnostics notification
            # Diagnostics come asynchronously via textDocument/publishDiagnostics
            # We need a way to capturing them.
            # Client has `on_notification`. We need to subscribe.
            
            diagnostics = []
            
            def handle_diagnostics(params):
                if params and params['uri'] == uri:
                    diagnostics.extend(params['diagnostics'])
            
            client.on_notification("textDocument/publishDiagnostics", handle_diagnostics)
            
            try:
                # Wait a bit? Or trigger a change?
                # Usually didOpen triggers diagnostics.
                # We might need to wait a small amount of time.
                # This is tricky in async 'one-shot' mode.
                # For now, simplistic wait.
                import asyncio
                await asyncio.sleep(0.5) 
                
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
