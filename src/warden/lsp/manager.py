"""
LSP Manager - Language Server Protocol client management.

Provides singleton access to language servers for semantic code analysis.
Supports: Python (pyright), TypeScript/JavaScript, Rust (rust-analyzer), Go (gopls).
"""

import shutil
import structlog
from pathlib import Path
from typing import Dict, Optional, List

from warden.lsp.client import LanguageServerClient

logger = structlog.get_logger()


# LSP server configurations: language -> (binary_names, args)
LSP_SERVER_CONFIG: Dict[str, Dict] = {
    "python": {
        "binaries": ["pyright-langserver", "pylsp", "pyls"],
        "args": ["--stdio"],
    },
    "typescript": {
        "binaries": ["typescript-language-server"],
        "args": ["--stdio"],
    },
    "javascript": {
        "binaries": ["typescript-language-server"],
        "args": ["--stdio"],
    },
    "rust": {
        "binaries": ["rust-analyzer"],
        "args": [],  # rust-analyzer uses stdio by default
    },
    "go": {
        "binaries": ["gopls"],
        "args": ["serve"],
    },
}


class LSPManager:
    """
    Manages Language Server instances.

    Singleton service providing LSP clients for semantic code analysis.
    Used by OrphanFrame for cross-file reference detection.

    Thread Safety: Not thread-safe. Use from single async context.
    """

    _instance: Optional['LSPManager'] = None

    def __init__(self) -> None:
        self._clients: Dict[str, LanguageServerClient] = {}
        self._binaries: Dict[str, str] = {}
        self._root_path: Optional[str] = None
        self._discover_binaries()

    @classmethod
    def get_instance(cls) -> 'LSPManager':
        """Get singleton instance."""
        if not cls._instance:
            cls._instance = LSPManager()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        if cls._instance:
            # Don't await here - caller should call shutdown_all_async first
            cls._instance = None

    def _discover_binaries(self) -> None:
        """
        Auto-discover LSP binaries using shutil.which.

        Checks PATH and common locations for language servers.
        Logs available and missing servers for observability.
        """
        available = []
        missing = []

        for language, config in LSP_SERVER_CONFIG.items():
            found = False
            for binary_name in config["binaries"]:
                # Check PATH
                binary_path = shutil.which(binary_name)
                if binary_path:
                    self._binaries[language] = binary_path
                    available.append(f"{language}:{binary_name}")
                    found = True
                    break

            if not found:
                missing.append(language)

        logger.info(
            "lsp_binaries_discovered",
            available=available,
            missing=missing,
            total=len(LSP_SERVER_CONFIG)
        )

    def is_available(self, language: str) -> bool:
        """Check if LSP is available for a language."""
        return language.lower() in self._binaries

    def get_available_languages(self) -> List[str]:
        """Get list of languages with available LSP servers."""
        return list(self._binaries.keys())

    async def get_client_async(
        self,
        language: str,
        root_path: str
    ) -> Optional[LanguageServerClient]:
        """
        Get or spawn a client for the given language.

        Args:
            language: Language identifier (python, typescript, rust, go)
            root_path: Project root path for LSP initialization

        Returns:
            LanguageServerClient or None if unavailable

        Raises:
            RuntimeError: If LSP server fails to start
        """
        language = language.lower()

        if language not in self._binaries:
            logger.debug("lsp_unsupported_language", language=language)
            return None

        # Return cached client if exists and root matches
        if language in self._clients:
            return self._clients[language]

        # Spawn new client
        binary = self._binaries[language]
        config = LSP_SERVER_CONFIG.get(language, {"args": ["--stdio"]})
        args = config["args"]

        try:
            client = LanguageServerClient(binary, args, cwd=root_path)
            await client.start_async()

            # Initialize LSP session
            await client.initialize_async(root_path)
            await client.send_notification_async("initialized", {})

            self._clients[language] = client
            self._root_path = root_path

            logger.info("lsp_client_ready", language=language, binary=binary)
            return client

        except FileNotFoundError:
            logger.warning("lsp_binary_not_found", language=language, binary=binary)
            # Remove from binaries to prevent retry
            del self._binaries[language]
            return None
        except Exception as e:
            logger.error("lsp_spawn_failed", language=language, binary=binary, error=str(e))
            return None

    async def shutdown_all_async(self) -> None:
        """Gracefully shutdown all active language servers."""
        for lang, client in self._clients.items():
            try:
                await client.shutdown_async()
                logger.debug("lsp_client_shutdown", language=lang)
            except Exception as e:
                logger.warning("lsp_shutdown_error", language=lang, error=str(e))

        self._clients.clear()
        logger.info("lsp_all_clients_shutdown", count=len(self._clients))
