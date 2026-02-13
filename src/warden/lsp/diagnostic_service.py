"""
LSP Diagnostic Service - Collect and convert LSP diagnostics to Warden findings.

Provides integration between LSP language servers and Warden's validation pipeline.
Runs alongside validation frames to provide additional diagnostics.
"""

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from warden.lsp.manager import LSPManager
from warden.validation.domain.frame import CodeFile, Finding

logger = structlog.get_logger()


class LSPDiagnosticService:
    """
    Collects LSP diagnostics and converts them to Warden findings.

    This service provides optional LSP integration into the pipeline.
    It gracefully handles missing language servers.
    """

    def __init__(self, enabled: bool = False, servers: list[str] | None = None):
        """
        Initialize LSP diagnostic service.

        Args:
            enabled: Whether LSP integration is enabled
            servers: List of language servers to use (auto-detect if None)
        """
        self.enabled = enabled
        self.servers = servers or []
        self.manager = LSPManager.get_instance() if enabled else None

        if self.enabled:
            logger.info(
                "lsp_diagnostic_service_initialized",
                enabled=enabled,
                configured_servers=self.servers,
            )

    async def collect_diagnostics_async(
        self,
        code_files: list[CodeFile],
        project_root: Path,
    ) -> list[Finding]:
        """
        Collect LSP diagnostics for code files.

        Args:
            code_files: List of code files to analyze
            project_root: Project root path for LSP initialization

        Returns:
            List of findings from LSP diagnostics
        """
        if not self.enabled or not self.manager:
            logger.debug("lsp_diagnostics_disabled", enabled=self.enabled)
            return []

        findings: list[Finding] = []

        # Group files by language
        files_by_language = self._group_files_by_language(code_files)

        # Collect diagnostics for each language
        for language, files in files_by_language.items():
            if not self.manager.is_available(language):
                logger.debug("lsp_server_unavailable", language=language)
                continue

            try:
                lang_findings = await self._collect_language_diagnostics_async(language, files, project_root)
                findings.extend(lang_findings)
            except Exception as e:
                logger.warning(
                    "lsp_diagnostics_collection_failed",
                    language=language,
                    error=str(e),
                )

        logger.info(
            "lsp_diagnostics_collected",
            total_findings=len(findings),
            languages=list(files_by_language.keys()),
        )

        return findings

    async def _collect_language_diagnostics_async(
        self,
        language: str,
        files: list[CodeFile],
        project_root: Path,
    ) -> list[Finding]:
        """Collect diagnostics for a specific language."""
        findings: list[Finding] = []

        try:
            # Get or spawn LSP client
            client = await self.manager.get_client_async(language, str(project_root))

            if not client:
                logger.debug("lsp_client_unavailable", language=language)
                return findings

            # Register diagnostic handler
            diagnostics_received = []

            def diagnostic_handler(params: dict[str, Any]) -> None:
                """Handle textDocument/publishDiagnostics notifications."""
                diagnostics_received.append(params)

            client.on_notification("textDocument/publishDiagnostics", diagnostic_handler)

            # Open documents and collect diagnostics
            for file in files:
                try:
                    # Convert path to absolute
                    file_path = Path(file.path)
                    if not file_path.is_absolute():
                        file_path = project_root / file_path

                    # Open document in LSP
                    await client.open_document_async(str(file_path), language, file.content)

                    # Wait a bit for diagnostics to arrive
                    await asyncio.sleep(0.5)

                except Exception as e:
                    logger.warning(
                        "lsp_document_open_failed",
                        file=file.path,
                        error=str(e),
                    )

            # Remove handler
            client.remove_notification_handler("textDocument/publishDiagnostics", diagnostic_handler)

            # Convert diagnostics to findings
            for diagnostic_params in diagnostics_received:
                file_findings = self._convert_diagnostics_to_findings(diagnostic_params, language)
                findings.extend(file_findings)

            # Close documents
            for file in files:
                try:
                    file_path = Path(file.path)
                    if not file_path.is_absolute():
                        file_path = project_root / file_path
                    await client.close_document_async(str(file_path))
                except Exception:
                    pass

        except Exception as e:
            logger.error(
                "lsp_language_diagnostics_failed",
                language=language,
                error=str(e),
            )

        return findings

    def _convert_diagnostics_to_findings(
        self,
        diagnostic_params: dict[str, Any],
        language: str,
    ) -> list[Finding]:
        """
        Convert LSP diagnostics to Warden findings.

        Args:
            diagnostic_params: LSP publishDiagnostics notification params
            language: Language identifier

        Returns:
            List of findings
        """
        findings: list[Finding] = []

        uri = diagnostic_params.get("uri", "")
        diagnostics = diagnostic_params.get("diagnostics", [])

        # Extract file path from URI
        file_path = uri.replace("file://", "")

        for diagnostic in diagnostics:
            try:
                finding = self._convert_single_diagnostic(diagnostic, file_path, language)
                if finding:
                    findings.append(finding)
            except Exception as e:
                logger.warning(
                    "lsp_diagnostic_conversion_failed",
                    diagnostic=diagnostic,
                    error=str(e),
                )

        return findings

    def _convert_single_diagnostic(
        self,
        diagnostic: dict[str, Any],
        file_path: str,
        language: str,
    ) -> Finding | None:
        """Convert a single LSP diagnostic to a Warden finding."""
        # Map LSP severity to Warden severity (strings)
        lsp_severity = diagnostic.get("severity", 2)  # 1=Error, 2=Warning, 3=Info, 4=Hint
        severity_map = {
            1: "critical",  # Error
            2: "medium",  # Warning
            3: "low",  # Info
            4: "low",  # Hint
        }
        severity = severity_map.get(lsp_severity, "low")

        # Extract location
        range_data = diagnostic.get("range", {})
        start = range_data.get("start", {})
        line = start.get("line", 0) + 1  # LSP is 0-indexed, Warden is 1-indexed
        character = start.get("character", 0)

        # Extract message and code
        message = diagnostic.get("message", "")
        code = diagnostic.get("code", "")
        source = diagnostic.get("source", language)

        # Create finding
        finding = Finding(
            id=str(uuid4()),
            severity=severity,
            message=f"[{source}] {message}",
            location=f"{file_path}:{line}",
            detail=f"LSP diagnostic from {source}" + (f" (code: {code})" if code else ""),
            code=f"Line {line}, Column {character}",
            line=line,
            column=character,
        )

        return finding

    def _group_files_by_language(self, code_files: list[CodeFile]) -> dict[str, list[CodeFile]]:
        """Group code files by language."""
        groups: dict[str, list[CodeFile]] = {}

        for file in code_files:
            language = file.language or "unknown"
            if language == "unknown":
                # Try to detect from file extension
                language = self._detect_language_from_path(file.path)

            if language not in groups:
                groups[language] = []
            groups[language].append(file)

        return groups

    def _detect_language_from_path(self, path: str) -> str:
        """Detect language from file path extension."""
        from warden.ast.domain.enums import CodeLanguage
        from warden.shared.languages.registry import LanguageRegistry

        lang_enum = LanguageRegistry.get_language_from_path(path)
        if lang_enum != CodeLanguage.UNKNOWN:
            return lang_enum.value.lower()

        return "unknown"

    async def shutdown_async(self) -> None:
        """Gracefully shutdown LSP manager."""
        if self.manager:
            await self.manager.shutdown_all_async()
            logger.info("lsp_diagnostic_service_shutdown")
