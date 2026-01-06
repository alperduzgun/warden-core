
import structlog
import asyncio
from typing import Dict, List, Any, Optional
from pathlib import Path
from warden.lsp import LSPManager

logger = structlog.get_logger()

class LSPSymbolGraph:
    """
    Builds a symbol graph of the project using LSP documentLetter capabilities.
    """
    
    def __init__(self):
        self.lsp_manager = LSPManager.get_instance()

    async def build_graph(self, root_path: str, files: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Build symbol hierarchy for a list of files.
        
        Returns:
            Dict[file_path, List[Symbol]]
        """
        graph = {}
        
        # Group files by language to optimize client retrieval
        files_by_lang = {"python": [], "typescript": [], "javascript": []}
        
        for f in files:
            path = Path(f)
            if path.suffix == ".py": files_by_lang["python"].append(f)
            elif path.suffix in [".ts", ".tsx"]: files_by_lang["typescript"].append(f)
            elif path.suffix in [".js", ".jsx"]: files_by_lang["javascript"].append(f)

        for language, lang_files in files_by_lang.items():
            if not lang_files: continue
            
            client = await self.lsp_manager.get_client(language, root_path)
            if not client:
                logger.debug("symbol_graph_lsp_unavailable", language=language)
                continue
                
            for file_path in lang_files:
                try:
                    uri = f"file://{file_path}"
                    # Ensure open
                    # TODO: optimize if already open
                    await client.send_notification("textDocument/didOpen", {
                        "textDocument": {
                            "uri": uri,
                            "languageId": language,
                            "version": 1,
                            "text": Path(file_path).read_text()
                        }
                    })
                    
                    symbols = await client.send_request("textDocument/documentSymbol", {
                        "textDocument": {"uri": uri}
                    })
                    
                    if symbols:
                        graph[file_path] = symbols
                        
                except Exception as e:
                    logger.warning("symbol_extraction_failed", file=file_path, error=str(e))
                    
        return graph

    def print_graph(self, graph: Dict[str, List[Any]]):
        """Debug helper to print graph."""
        import json
        print(json.dumps(graph, indent=2))
