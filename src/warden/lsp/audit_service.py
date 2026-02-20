"""
LSP Audit Service.

Cross-references CodeGraph edges against LSP call hierarchy
and type hierarchy to confirm or refute relationships.

Features:
- build_call_chains_async: Validate CALLS edges via LSP
- build_type_hierarchy_async: Validate INHERITS/IMPLEMENTS edges via LSP
- detect_dead_symbols_async: Find unreferenced symbols
- validate_dependency_chain_async: Full validation pass
- Health check + circuit breaker (3 failures -> disable)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from warden.analysis.domain.code_graph import (
    ChainValidation,
    ChainValidationEntry,
    EdgeRelation,
)
from warden.lsp.semantic_analyzer import SemanticAnalyzer

if TYPE_CHECKING:
    from warden.analysis.domain.code_graph import CodeGraph

logger = structlog.get_logger(__name__)

# Circuit breaker thresholds
_MAX_FAILURES = 3


class LSPAuditService:
    """
    Validates CodeGraph edges using LSP semantic analysis.

    Health check + circuit breaker: after _MAX_FAILURES consecutive
    LSP errors, the service disables itself to avoid wasting time.
    """

    def __init__(self, project_root: str | None = None) -> None:
        self._project_root = project_root or ""
        self._failure_count = 0
        self._disabled = False
        self._analyzer: SemanticAnalyzer | None = None

    def _get_analyzer(self) -> SemanticAnalyzer | None:
        """Lazy-init SemanticAnalyzer with circuit breaker check."""
        if self._disabled:
            return None
        if self._analyzer is None:
            try:
                self._analyzer = SemanticAnalyzer.get_instance()
            except Exception as e:
                logger.warning("lsp_audit_analyzer_init_failed", error=str(e))
                self._record_failure()
                return None
        return self._analyzer

    def _record_failure(self) -> None:
        """Record an LSP failure and potentially trip circuit breaker."""
        self._failure_count += 1
        if self._failure_count >= _MAX_FAILURES:
            logger.warning(
                "lsp_audit_circuit_breaker_tripped",
                failures=self._failure_count,
            )
            self._disabled = True

    def _reset_failures(self) -> None:
        """Reset failure count on success."""
        self._failure_count = 0

    @property
    def is_available(self) -> bool:
        """Check if LSP audit service is available."""
        return not self._disabled

    async def health_check_async(self) -> bool:
        """
        Check if LSP is operational.

        Returns:
            True if LSP can be used for auditing.
        """
        if self._disabled:
            return False
        analyzer = self._get_analyzer()
        if analyzer is None:
            return False
        # Check if at least Python LSP is available
        from warden.lsp.manager import LSPManager

        mgr = LSPManager.get_instance()
        return mgr.is_available("python")

    async def validate_dependency_chain_async(
        self,
        code_graph: CodeGraph,
        *,
        max_checks: int = 100,
    ) -> ChainValidation:
        """
        Validate CodeGraph edges against LSP data.

        Checks CALLS, INHERITS, and IMPLEMENTS edges.
        Also detects dead (unreferenced) symbols.

        Args:
            code_graph: The code graph to validate.
            max_checks: Maximum number of edges to check (performance cap).

        Returns:
            ChainValidation with confirmation results.
        """
        validation = ChainValidation()

        analyzer = self._get_analyzer()
        if analyzer is None:
            logger.info("lsp_audit_skipped", reason="analyzer_unavailable")
            return validation

        validation.lsp_available = True
        edges_to_check = code_graph.edges[:max_checks]
        validation.total_chains_checked = len(edges_to_check)

        for edge in edges_to_check:
            if self._disabled:
                break

            entry = ChainValidationEntry(
                source_fqn=edge.source,
                target_fqn=edge.target,
                chain_depth=0,
            )

            try:
                source_node = code_graph.nodes.get(edge.source)
                if not source_node:
                    entry.lsp_error = "source_node_missing"
                    validation.errors += 1
                    validation.entries.append(entry)
                    continue

                confirmed = await self._check_edge_async(
                    analyzer, edge.relation, source_node.file_path, source_node.line
                )

                if confirmed is True:
                    entry.lsp_confirmed = True
                    validation.confirmed += 1
                    self._reset_failures()
                elif confirmed is False:
                    validation.unconfirmed += 1
                else:
                    # None = LSP couldn't determine
                    entry.lsp_error = "undetermined"
                    validation.errors += 1

            except Exception as e:
                entry.lsp_error = str(e)
                validation.errors += 1
                self._record_failure()

            validation.entries.append(entry)

        # Detect dead symbols
        validation.dead_symbols = await self._detect_dead_symbols_async(
            analyzer, code_graph
        )

        logger.info(
            "lsp_audit_complete",
            checked=validation.total_chains_checked,
            confirmed=validation.confirmed,
            unconfirmed=validation.unconfirmed,
            dead=len(validation.dead_symbols),
        )

        return validation

    async def _check_edge_async(
        self,
        analyzer: SemanticAnalyzer,
        relation: EdgeRelation,
        file_path: str,
        line: int,
    ) -> bool | None:
        """
        Check a single edge via LSP.

        Returns:
            True if confirmed, False if refuted, None if undetermined.
        """
        if relation == EdgeRelation.CALLS:
            return await self._check_call_async(analyzer, file_path, line)
        elif relation in (EdgeRelation.INHERITS, EdgeRelation.IMPLEMENTS):
            return await self._check_hierarchy_async(analyzer, file_path, line)
        # IMPORTS, DEFINES, RE_EXPORTS - not LSP-checkable
        return None

    async def _check_call_async(
        self,
        analyzer: SemanticAnalyzer,
        file_path: str,
        line: int,
    ) -> bool | None:
        """Check a CALLS edge via LSP call hierarchy."""
        try:
            callees = await analyzer.get_callees_async(file_path, line, 0)
            if callees:
                self._reset_failures()
                return True
            # No callees found doesn't necessarily mean refuted
            return None
        except Exception:
            self._record_failure()
            return None

    async def _check_hierarchy_async(
        self,
        analyzer: SemanticAnalyzer,
        file_path: str,
        line: int,
    ) -> bool | None:
        """Check an INHERITS/IMPLEMENTS edge via LSP type hierarchy."""
        try:
            parents = await analyzer.get_parent_classes_async(file_path, line, 0)
            if parents:
                self._reset_failures()
                return True
            return None
        except Exception:
            self._record_failure()
            return None

    async def _detect_dead_symbols_async(
        self,
        analyzer: SemanticAnalyzer,
        code_graph: CodeGraph,
        max_checks: int = 50,
    ) -> list[str]:
        """
        Detect symbols that have zero references via LSP.

        Only checks non-test, non-module symbols.
        """
        dead: list[str] = []
        checked = 0

        for fqn, node in code_graph.nodes.items():
            if checked >= max_checks or self._disabled:
                break
            if node.is_test:
                continue
            if node.kind.value == "module":
                continue

            try:
                is_used = await analyzer.is_symbol_used_async(
                    node.file_path, node.line, 0
                )
                checked += 1
                if is_used is False:
                    dead.append(fqn)
                    self._reset_failures()
                elif is_used is True:
                    self._reset_failures()
            except Exception:
                self._record_failure()

        return dead
