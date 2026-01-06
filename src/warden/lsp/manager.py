
import asyncio
import structlog
from pathlib import Path
from typing import Dict, Optional
from warden.lsp.client import LanguageServerClient

logger = structlog.get_logger()

class LSPManager:
    """
    Manages Language Server instances.
    Singleton-like service that provides clients for detected languages.
    """
    
    _instance = None
    
    def __init__(self):
        self._clients: Dict[str, LanguageServerClient] = {}
        self._binaries: Dict[str, str] = {}
        self._discover_binaries()

    @classmethod
    def get_instance(cls) -> 'LSPManager':
        if not cls._instance:
            cls._instance = LSPManager()
        return cls._instance

    def _discover_binaries(self):
        """Auto-discover LSP binaries in PATH or local venv."""
        # Simple heuristic: Check venv first, then PATH
        # In a real impl, we might use shutil.which or strict configuration
        
        # Determine internal venv path
        venv_bin = Path.cwd() / ".venv" / "bin"
        
        # Python: pyright-langserver
        if (venv_bin / "pyright-langserver").exists():
            self._binaries["python"] = str(venv_bin / "pyright-langserver")
        else:
            # Assumes it's in PATH if not in venv
            self._binaries["python"] = "pyright-langserver"

        # JS/TS: typescript-language-server
        if (venv_bin / "typescript-language-server").exists():
             self._binaries["javascript"] = str(venv_bin / "typescript-language-server")
             self._binaries["typescript"] = str(venv_bin / "typescript-language-server")
        else:
             self._binaries["javascript"] = "typescript-language-server"
             self._binaries["typescript"] = "typescript-language-server"

    async def get_client(self, language: str, root_path: str) -> Optional[LanguageServerClient]:
        """
        Get or spawn a client for the given language.
        """
        if language not in self._binaries:
            logger.debug("lsp_unsupported_language", language=language)
            return None
        
        if language in self._clients:
            return self._clients[language]
        
        # Spawn new client
        binary = self._binaries[language]
        args = ["--stdio"]
        
        try:
            client = LanguageServerClient(binary, args, cwd=root_path)
            await client.start()
            
            # Initialize
            resp = await client.initialize(root_path)
            # await client.initialized() # Some servers require this notification
            client._send_notification("initialized", {})
            
            self._clients[language] = client
            return client
            
        except Exception as e:
            logger.error("lsp_spawn_failed", language=language, error=str(e))
            return None

    async def shutdown_all(self):
        """Shutdown all active servers."""
        for lang, client in self._clients.items():
            await client.shutdown()
        self._clients.clear()
