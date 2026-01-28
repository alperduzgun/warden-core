"""
LSP Semantic Analyzer - High-level semantic analysis using LSP.

Provides cheap, fast structural analysis that frames can use BEFORE
falling back to expensive LLM analysis. Uses LSP for:
- Call graph analysis (who calls what)
- Type hierarchy (class relationships)
- Symbol search (find definitions)
- Dead code detection (unreferenced symbols)

Usage:
    analyzer = SemanticAnalyzer.get_instance()

    # Get call graph for a function
    callers = await analyzer.get_callers_async(file_path, line, char)
    callees = await analyzer.get_callees_async(file_path, line, char)

    # Check if a symbol is used anywhere
    is_used = await analyzer.is_symbol_used_async(file_path, line, char)

    # Get class hierarchy
    parents = await analyzer.get_parent_classes_async(file_path, line, char)
    children = await analyzer.get_child_classes_async(file_path, line, char)
"""

import structlog
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from pathlib import Path

from warden.lsp.manager import LSPManager

logger = structlog.get_logger()


@dataclass
class SymbolInfo:
    """Simplified symbol information."""
    name: str
    kind: str  # function, class, variable, etc.
    file_path: str
    line: int
    character: int

    @classmethod
    def from_lsp(cls, item: Dict[str, Any]) -> 'SymbolInfo':
        """Create from LSP CallHierarchyItem or TypeHierarchyItem."""
        uri = item.get("uri", "")
        file_path = uri.replace("file://", "") if uri.startswith("file://") else uri

        # Get position from range or selectionRange
        range_data = item.get("selectionRange", item.get("range", {}))
        start = range_data.get("start", {})

        # Map LSP SymbolKind to string
        kind_map = {
            1: "file", 2: "module", 3: "namespace", 4: "package",
            5: "class", 6: "method", 7: "property", 8: "field",
            9: "constructor", 10: "enum", 11: "interface", 12: "function",
            13: "variable", 14: "constant", 15: "string", 16: "number",
            17: "boolean", 18: "array", 19: "object", 20: "key",
            21: "null", 22: "enum_member", 23: "struct", 24: "event",
            25: "operator", 26: "type_parameter"
        }

        return cls(
            name=item.get("name", "unknown"),
            kind=kind_map.get(item.get("kind", 0), "unknown"),
            file_path=file_path,
            line=start.get("line", 0),
            character=start.get("character", 0)
        )


@dataclass
class CallInfo:
    """Call relationship information."""
    caller: SymbolInfo
    callee: SymbolInfo
    call_sites: List[Dict[str, int]]  # [{line, character}, ...]


class SemanticAnalyzer:
    """
    High-level semantic code analyzer using LSP.

    Provides structural analysis that's 10-100x cheaper than LLM.
    Falls back gracefully if LSP is unavailable.
    """

    _instance: Optional['SemanticAnalyzer'] = None

    # File extension to language mapping
    EXTENSION_MAP: Dict[str, str] = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".kt": "kotlin",
        ".kts": "kotlin",
        ".scala": "scala",
        ".cs": "csharp",
        ".fs": "fsharp",
        ".rb": "ruby",
        ".php": "php",
        ".lua": "lua",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".c": "c",
        ".h": "c",
        ".hpp": "cpp",
        ".zig": "zig",
        ".sh": "bash",
        ".bash": "bash",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".json": "json",
        ".hs": "haskell",
        ".ex": "elixir",
        ".exs": "elixir",
        ".erl": "erlang",
        ".clj": "clojure",
        ".dart": "dart",
        ".swift": "swift",
        ".vue": "vue",
        ".html": "html",
        ".css": "css",
    }

    def __init__(self) -> None:
        self._lsp_manager = LSPManager.get_instance()
        self._opened_files: Dict[str, str] = {}  # file_path -> language

    @classmethod
    def get_instance(cls) -> 'SemanticAnalyzer':
        """Get singleton instance."""
        if not cls._instance:
            cls._instance = SemanticAnalyzer()
        return cls._instance

    def _get_language(self, file_path: str) -> Optional[str]:
        """Get language from file extension."""
        ext = Path(file_path).suffix.lower()
        return self.EXTENSION_MAP.get(ext)

    async def _ensure_file_open_async(
        self,
        file_path: str,
        content: Optional[str] = None
    ) -> Optional[Any]:
        """
        Ensure file is opened in LSP and return client.

        Returns None if LSP unavailable for this language.
        """
        language = self._get_language(file_path)
        if not language:
            return None

        if not self._lsp_manager.is_available(language):
            return None

        # Get project root (go up until we find .git or root)
        project_root = self._find_project_root(file_path)

        client = await self._lsp_manager.get_client_async(language, project_root)
        if not client:
            return None

        # Open file if not already open
        if file_path not in self._opened_files:
            if content is None:
                try:
                    content = Path(file_path).read_text()
                except Exception:
                    return None

            await client.open_document_async(file_path, language, content)
            self._opened_files[file_path] = language

        return client

    def _find_project_root(self, file_path: str) -> str:
        """Find project root by looking for .git, pyproject.toml, etc."""
        path = Path(file_path).parent
        markers = [".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod"]

        while path != path.parent:
            for marker in markers:
                if (path / marker).exists():
                    return str(path)
            path = path.parent

        return str(Path(file_path).parent)

    # ============================================================
    # Call Graph Analysis
    # ============================================================

    async def get_callers_async(
        self,
        file_path: str,
        line: int,
        character: int,
        content: Optional[str] = None
    ) -> List[SymbolInfo]:
        """
        Get all functions/methods that call the symbol at position.

        Returns empty list if LSP unavailable - allows graceful fallback.
        """
        client = await self._ensure_file_open_async(file_path, content)
        if not client:
            return []

        # Prepare call hierarchy
        items = await client.prepare_call_hierarchy_async(file_path, line, character)
        if not items:
            return []

        # Get incoming calls
        incoming = await client.get_incoming_calls_async(items[0])

        callers = []
        for call in incoming:
            from_item = call.get("from", {})
            if from_item:
                callers.append(SymbolInfo.from_lsp(from_item))

        logger.debug("semantic_callers_found",
                    file=file_path, line=line, count=len(callers))
        return callers

    async def get_callees_async(
        self,
        file_path: str,
        line: int,
        character: int,
        content: Optional[str] = None
    ) -> List[SymbolInfo]:
        """
        Get all functions/methods called by the symbol at position.

        Returns empty list if LSP unavailable.
        """
        client = await self._ensure_file_open_async(file_path, content)
        if not client:
            return []

        items = await client.prepare_call_hierarchy_async(file_path, line, character)
        if not items:
            return []

        outgoing = await client.get_outgoing_calls_async(items[0])

        callees = []
        for call in outgoing:
            to_item = call.get("to", {})
            if to_item:
                callees.append(SymbolInfo.from_lsp(to_item))

        logger.debug("semantic_callees_found",
                    file=file_path, line=line, count=len(callees))
        return callees

    async def is_symbol_used_async(
        self,
        file_path: str,
        line: int,
        character: int,
        content: Optional[str] = None
    ) -> Optional[bool]:
        """
        Check if symbol at position is used anywhere (not dead code).

        Returns:
            True: Symbol has references
            False: Symbol appears unused (dead code candidate)
            None: Could not determine (LSP unavailable)
        """
        client = await self._ensure_file_open_async(file_path, content)
        if not client:
            return None

        refs = await client.find_references_async(
            file_path, line, character,
            include_declaration=False
        )

        # More than 0 references means it's used
        return len(refs) > 0

    # ============================================================
    # Type Hierarchy Analysis
    # ============================================================

    async def get_parent_classes_async(
        self,
        file_path: str,
        line: int,
        character: int,
        content: Optional[str] = None
    ) -> List[SymbolInfo]:
        """
        Get parent classes/interfaces of class at position.

        Returns empty list if LSP unavailable.
        """
        client = await self._ensure_file_open_async(file_path, content)
        if not client:
            return []

        items = await client.prepare_type_hierarchy_async(file_path, line, character)
        if not items:
            return []

        supertypes = await client.get_supertypes_async(items[0])

        parents = [SymbolInfo.from_lsp(t) for t in supertypes]
        logger.debug("semantic_parents_found",
                    file=file_path, line=line, count=len(parents))
        return parents

    async def get_child_classes_async(
        self,
        file_path: str,
        line: int,
        character: int,
        content: Optional[str] = None
    ) -> List[SymbolInfo]:
        """
        Get child classes/implementations of class/interface at position.

        Returns empty list if LSP unavailable.
        """
        client = await self._ensure_file_open_async(file_path, content)
        if not client:
            return []

        items = await client.prepare_type_hierarchy_async(file_path, line, character)
        if not items:
            return []

        subtypes = await client.get_subtypes_async(items[0])

        children = [SymbolInfo.from_lsp(t) for t in subtypes]
        logger.debug("semantic_children_found",
                    file=file_path, line=line, count=len(children))
        return children

    # ============================================================
    # Symbol Search
    # ============================================================

    async def find_symbol_async(
        self,
        query: str,
        project_root: str
    ) -> List[SymbolInfo]:
        """
        Search for symbols matching query across project.

        Useful for finding definitions without knowing the file.
        """
        # Use Python client for workspace symbols (most common)
        if not self._lsp_manager.is_available("python"):
            return []

        client = await self._lsp_manager.get_client_async("python", project_root)
        if not client:
            return []

        symbols = await client.get_workspace_symbols_async(query)

        results = []
        for sym in symbols:
            # SymbolInformation has different structure
            location = sym.get("location", {})
            uri = location.get("uri", "")
            file_path = uri.replace("file://", "") if uri.startswith("file://") else uri
            range_data = location.get("range", {})
            start = range_data.get("start", {})

            results.append(SymbolInfo(
                name=sym.get("name", ""),
                kind=str(sym.get("kind", 0)),
                file_path=file_path,
                line=start.get("line", 0),
                character=start.get("character", 0)
            ))

        logger.debug("semantic_symbol_search",
                    query=query, count=len(results))
        return results

    # ============================================================
    # Hover Info (Type & Docs)
    # ============================================================

    async def get_type_info_async(
        self,
        file_path: str,
        line: int,
        character: int,
        content: Optional[str] = None
    ) -> Optional[str]:
        """
        Get type information for symbol at position.

        Cheaper than asking LLM "what type is this variable?"
        """
        client = await self._ensure_file_open_async(file_path, content)
        if not client:
            return None

        hover = await client.get_hover_async(file_path, line, character)
        if not hover:
            return None

        contents = hover.get("contents", {})

        # Contents can be string, MarkupContent, or MarkedString[]
        if isinstance(contents, str):
            return contents
        elif isinstance(contents, dict):
            return contents.get("value", "")
        elif isinstance(contents, list) and contents:
            first = contents[0]
            if isinstance(first, str):
                return first
            return first.get("value", "")

        return None

    # ============================================================
    # Cleanup
    # ============================================================

    async def close_file_async(self, file_path: str) -> None:
        """Close a file in LSP (free resources)."""
        if file_path not in self._opened_files:
            return

        language = self._opened_files[file_path]

        if self._lsp_manager.is_available(language):
            project_root = self._find_project_root(file_path)
            client = await self._lsp_manager.get_client_async(language, project_root)
            if client:
                await client.close_document_async(file_path)

        del self._opened_files[file_path]

    async def shutdown_async(self) -> None:
        """Shutdown all LSP connections."""
        self._opened_files.clear()
        await self._lsp_manager.shutdown_all_async()


# Convenience function
def get_semantic_analyzer() -> SemanticAnalyzer:
    """Get the global semantic analyzer instance."""
    return SemanticAnalyzer.get_instance()
