
from pathlib import Path
from typing import Any, Dict, List

import structlog

from warden.lsp import LSPManager

logger = structlog.get_logger()

class LSPSymbolGraph:
    """
    Builds a symbol graph of the project using LSP documentLetter capabilities.
    """

    def __init__(self):
        self.lsp_manager = LSPManager.get_instance()
        self._opened_files: set[str] = set()

    async def build_graph_async(self, root_path: str, files: list[str]) -> dict[str, list[dict[str, Any]]]:
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

            client = await self.lsp_manager.get_client_async(language, root_path)
            if not client:
                logger.debug("symbol_graph_lsp_unavailable", language=language)
                continue

            for file_path in lang_files:
                try:
                    uri = f"file://{file_path}"

                    # Only open if not already opened
                    if uri not in self._opened_files:
                        try:
                            text = Path(file_path).read_text()
                        except (FileNotFoundError, PermissionError, UnicodeDecodeError) as e:
                            logger.warning("lsp_file_read_failed", file=str(file_path), error=str(e))
                            continue

                        await client.send_notification_async("textDocument/didOpen", {
                            "textDocument": {
                                "uri": uri,
                                "languageId": language,
                                "version": 1,
                                "text": text
                            }
                        })
                        self._opened_files.add(uri)
                        logger.debug("lsp_file_opened", uri=uri, total_open=len(self._opened_files))

                    symbols = await client.send_request_async("textDocument/documentSymbol", {
                        "textDocument": {"uri": uri}
                    })

                    if symbols:
                        graph[file_path] = symbols

                except Exception as e:
                    logger.warning("symbol_extraction_failed", file=file_path, error=str(e))

        return graph

    def reset(self) -> None:
        """Reset tracked open files."""
        self._opened_files.clear()

    def print_graph(self, graph: dict[str, list[Any]]):
        """Debug helper to log graph structure."""
        import json
        logger.debug("symbol_graph_dump", graph=json.dumps(graph, indent=2))
