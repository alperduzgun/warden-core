"""
LSP Manager - Language Server Protocol client management.

Provides singleton access to language servers for semantic code analysis.
Supports 30+ languages including:
- Primary: Python, TypeScript, JavaScript, Rust, Go
- JVM: Java, Kotlin, Scala
- .NET: C#, F#
- Web: HTML, CSS, Vue
- Scripting: Ruby, PHP, Perl, Lua
- Systems: C, C++, Zig
- Shell/Config: Bash, YAML, TOML, JSON
- Functional: Haskell, Elixir, Erlang, Clojure
- Mobile: Dart, Swift
"""

import shutil
import threading
from typing import Optional

import structlog

from warden.lsp.client import LanguageServerClient

logger = structlog.get_logger()


# LSP server configurations: language -> {binary_name: args}
# Dict iteration order defines discovery priority (first found wins).
# Each binary carries its own args so mixed-binary languages (e.g. python
# has both pyright and pylsp) don't get wrong flags.
LSP_SERVER_CONFIG: dict[str, dict[str, list[str]]] = {
    # --- Primary Languages ---
    "python": {
        "pyright-langserver":   ["--stdio"],
        "pylsp":                [],           # reads stdin directly, no --stdio flag
        "pyls":                 [],           # legacy pylsp, same behaviour
        "jedi-language-server": ["--stdio"],
    },
    "typescript": {
        "typescript-language-server": ["--stdio"],
    },
    "javascript": {
        "typescript-language-server": ["--stdio"],
    },
    "rust": {
        "rust-analyzer": [],  # stdio by default
    },
    "go": {
        "gopls": ["serve"],
    },
    # --- JVM Languages ---
    "java": {
        "jdtls":                [],
        "java-language-server": [],
    },
    "kotlin": {
        "kotlin-language-server": [],
    },
    "scala": {
        "metals": [],
    },
    # --- .NET Languages ---
    "csharp": {
        "OmniSharp":  ["--languageserver"],
        "omnisharp":  ["--languageserver"],
        "csharp-ls":  ["--stdio"],
    },
    "fsharp": {
        "fsautocomplete": ["--background-service-enabled"],
    },
    # --- Web Languages ---
    "html": {
        "vscode-html-language-server": ["--stdio"],
        "html-languageserver":         ["--stdio"],
    },
    "css": {
        "vscode-css-language-server": ["--stdio"],
        "css-languageserver":         ["--stdio"],
    },
    "vue": {
        "vue-language-server": ["--stdio"],
        "vls":                 [],   # vls does not accept --stdio
    },
    # --- Scripting Languages ---
    "ruby": {
        "solargraph": ["stdio"],    # no leading dash
        "ruby-lsp":   ["--stdio"],
    },
    "php": {
        "phpactor":    ["language-server"],
        "intelephense": ["--stdio"],
    },
    "perl": {
        "perl-language-server": [],
    },
    "lua": {
        "lua-language-server": [],
    },
    # --- Systems Languages ---
    "cpp": {
        "clangd": [],
        "ccls":   [],
    },
    "c": {
        "clangd": [],
        "ccls":   [],
    },
    "zig": {
        "zls": [],
    },
    # --- Shell/Config ---
    "bash": {
        "bash-language-server": ["start"],
    },
    "shell": {
        "bash-language-server": ["start"],
    },
    "yaml": {
        "yaml-language-server": ["--stdio"],
    },
    "toml": {
        "taplo": ["lsp", "stdio"],
    },
    "json": {
        "vscode-json-language-server": ["--stdio"],
    },
    # --- Functional Languages ---
    "haskell": {
        "haskell-language-server-wrapper": ["--lsp"],
        "hls":                             ["--lsp"],
    },
    "elixir": {
        "elixir-ls":        [],
        "language_server.sh": [],
    },
    "erlang": {
        "erlang_ls": [],
    },
    "clojure": {
        "clojure-lsp": [],
    },
    # --- Mobile ---
    "dart": {
        "dart":                 ["language-server", "--protocol=lsp"],
        "dart-language-server": ["--stdio"],
    },
    "swift": {
        "sourcekit-lsp": [],
    },
}


class LSPManager:
    """
    Manages Language Server instances.

    Singleton service providing LSP clients for semantic code analysis.
    Used by OrphanFrame for cross-file reference detection.

    Thread Safety: Thread-safe via double-checked locking pattern.
    """

    _instance: Optional["LSPManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self, auto_install: bool = True) -> None:
        self._clients: dict[str, LanguageServerClient] = {}
        self._binaries: dict[str, str] = {}       # language → binary path
        self._binary_names: dict[str, str] = {}   # language → binary name (for args lookup)
        self._root_path: str | None = None
        self._auto_install_enabled = auto_install
        self._discover_binaries()

    @classmethod
    def get_instance(cls) -> "LSPManager":
        """
        Get singleton instance (thread-safe).

        Uses double-checked locking for performance - lock only acquired
        on first access when instance is None.
        """
        # Fast path: instance already exists (no lock needed)
        if cls._instance is not None:
            return cls._instance

        # Slow path: acquire lock and create instance
        with cls._lock:
            # Double-check after acquiring lock
            if cls._instance is None:
                cls._instance = LSPManager()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            if cls._instance is not None:
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

        for language, binaries in LSP_SERVER_CONFIG.items():
            found = False
            for binary_name in binaries:  # dict key iteration = priority order
                binary_path = shutil.which(binary_name)
                if binary_path:
                    self._binaries[language] = binary_path
                    self._binary_names[language] = binary_name
                    available.append(f"{language}:{binary_name}")
                    found = True
                    break

            if not found:
                missing.append(language)

        logger.info("lsp_binaries_discovered", available=available, missing=missing, total=len(LSP_SERVER_CONFIG))

        # Auto-install critical LSP servers for detected project languages
        if missing and self._auto_install_enabled:
            self._auto_install_lsp_servers(missing)

    def _auto_install_lsp_servers(self, missing_languages: list[str]) -> None:
        """Auto-install LSP servers for project-critical languages."""
        import subprocess as _sp

        # Only auto-install for languages that have pip/npm packages
        _INSTALL_COMMANDS: dict[str, list[list[str]]] = {
            "python": [
                ["pip", "install", "-q", "python-lsp-server"],
            ],
            "typescript": [
                ["npm", "install", "-g", "typescript-language-server", "typescript"],
            ],
            "javascript": [
                ["npm", "install", "-g", "typescript-language-server", "typescript"],
            ],
        }

        for lang in missing_languages:
            cmds = _INSTALL_COMMANDS.get(lang)
            if not cmds:
                continue
            for cmd in cmds:
                if not shutil.which(cmd[0]):
                    continue
                try:
                    result = _sp.run(cmd, capture_output=True, text=True, timeout=120)
                    if result.returncode == 0:
                        # Re-discover after install
                        for binary_name in LSP_SERVER_CONFIG.get(lang, {}):
                            binary_path = shutil.which(binary_name)
                            if binary_path:
                                self._binaries[lang] = binary_path
                                self._binary_names[lang] = binary_name
                                logger.info("lsp_auto_installed", language=lang, binary=binary_name)
                                break
                        break
                    else:
                        logger.debug("lsp_auto_install_failed", language=lang, error=result.stderr[:200])
                except Exception as e:
                    logger.debug("lsp_auto_install_error", language=lang, error=str(e))

    def is_available(self, language: str) -> bool:
        """Check if LSP is available for a language."""
        return language.lower() in self._binaries

    def get_available_languages(self) -> list[str]:
        """Get list of languages with available LSP servers."""
        return list(self._binaries.keys())

    async def get_client_async(self, language: str, root_path: str) -> LanguageServerClient | None:
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

        # Spawn new client — look up args by the exact binary name that was found
        binary = self._binaries[language]
        binary_name = self._binary_names.get(language, "")
        args = LSP_SERVER_CONFIG.get(language, {}).get(binary_name, [])

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
            del self._binaries[language]
            self._binary_names.pop(language, None)
            return None
        except Exception as e:
            logger.error("lsp_spawn_failed", language=language, binary=binary, error=str(e))
            self._binaries.pop(language, None)
            self._binary_names.pop(language, None)
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
