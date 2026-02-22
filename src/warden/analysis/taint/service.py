"""Shared TaintAnalysisService — per-project, lazy-init, consumed by all frames.

Pattern follows ``LinterService``: create once per pipeline run, call
``analyze_all_async`` with the file list, query results via
``get_paths_for_file``.

The catalog and analyser are loaded **once** (lazy, on first call) regardless
of how many files are scanned — a perf win over the previous per-file reload
inside SecurityFrame.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from warden.shared.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from warden.validation.domain.frame import CodeFile

    from .models import TaintAnalyzer, TaintCatalog, TaintPath

logger = get_logger(__name__)

_TAINT_SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"python", "javascript", "typescript", "go", "java"})


class TaintAnalysisService:
    """Project-scoped taint analysis service.

    Args:
        project_root: Project root directory (used to load user catalog).
        taint_config: Optional taint tuning overrides (confidence_threshold, etc.).
    """

    def __init__(
        self,
        project_root: Path,
        taint_config: dict[str, Any] | None = None,
    ) -> None:
        self._project_root = project_root
        self._taint_config = taint_config
        # Lazy-init fields — populated on first analyze call
        self._catalog: TaintCatalog | None = None
        self._analyzer: TaintAnalyzer | None = None
        # Results cache: file_path -> list[TaintPath]
        self._results: dict[str, list[TaintPath]] = {}

    # -- lazy init ---------------------------------------------------------

    def _ensure_initialized(self) -> None:
        """Load catalog + analyzer exactly once."""
        if self._analyzer is not None:
            return

        from .models import TaintAnalyzer, TaintCatalog

        self._catalog = TaintCatalog.load(self._project_root)
        self._analyzer = TaintAnalyzer(
            catalog=self._catalog,
            taint_config=self._taint_config,
        )
        logger.debug(
            "taint_service_initialized",
            project_root=str(self._project_root),
        )

    # -- public API --------------------------------------------------------

    async def analyze_all_async(
        self,
        code_files: list[CodeFile],
    ) -> dict[str, list[TaintPath]]:
        """Analyse every file and return ``{file_path: [TaintPath, ...]}``.

        Unsupported languages are silently skipped.  Syntax errors in
        individual files are caught — other files still proceed.
        """
        self._ensure_initialized()
        assert self._analyzer is not None

        results: dict[str, list[TaintPath]] = {}
        analyzed = 0
        total_paths = 0

        for cf in code_files:
            lang = (cf.language or "").lower()
            if lang not in _TAINT_SUPPORTED_LANGUAGES:
                continue

            try:
                paths = self._analyzer.analyze(cf.content, lang)
                if paths:
                    results[cf.path] = paths
                    total_paths += len(paths)
                analyzed += 1
            except Exception as exc:
                logger.debug(
                    "taint_service_file_error",
                    file=cf.path,
                    error=str(exc),
                )

        self._results = results

        logger.info(
            "taint_service_complete",
            files_analyzed=analyzed,
            files_with_paths=len(results),
            total_paths=total_paths,
        )
        return results

    def get_paths_for_file(self, file_path: str) -> list[TaintPath]:
        """Return cached taint paths for a single file (empty list if none)."""
        return self._results.get(file_path, [])
