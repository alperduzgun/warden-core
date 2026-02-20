"""
Tests for LSPAuditService and ChainValidation/ChainValidationEntry models.

Strategy:
- All LSP I/O is mocked via unittest.mock.AsyncMock / patch so no real
  LSP servers are required.
- SemanticAnalyzer.get_instance and LSPManager.get_instance are patched at
  the module level used by the service under test.
- Tests follow the Arrange-Act-Assert pattern and are independent (no shared
  mutable state between tests).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.analysis.domain.code_graph import (
    ChainValidation,
    ChainValidationEntry,
    CodeGraph,
    EdgeRelation,
    SymbolEdge,
    SymbolKind,
    SymbolNode,
)
from warden.lsp.audit_service import LSPAuditService, _MAX_FAILURES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    fqn: str,
    name: str = "func",
    kind: SymbolKind = SymbolKind.FUNCTION,
    file_path: str = "src/module.py",
    line: int = 10,
    is_test: bool = False,
) -> SymbolNode:
    return SymbolNode(
        fqn=fqn,
        name=name,
        kind=kind,
        file_path=file_path,
        line=line,
        is_test=is_test,
    )


def _make_edge(
    source: str,
    target: str,
    relation: EdgeRelation = EdgeRelation.CALLS,
) -> SymbolEdge:
    return SymbolEdge(source=source, target=target, relation=relation)


def _make_graph_with_calls_edge() -> tuple[CodeGraph, SymbolNode, SymbolEdge]:
    """Return a graph that has one CALLS edge between two known nodes."""
    graph = CodeGraph()
    src_node = _make_node("src/a.py::caller", name="caller", file_path="src/a.py", line=5)
    tgt_node = _make_node("src/b.py::callee", name="callee", file_path="src/b.py", line=20)
    edge = _make_edge("src/a.py::caller", "src/b.py::callee", EdgeRelation.CALLS)
    graph.add_node(src_node)
    graph.add_node(tgt_node)
    graph.add_edge(edge)
    return graph, src_node, edge


# ---------------------------------------------------------------------------
# ChainValidationEntry model tests
# ---------------------------------------------------------------------------


class TestChainValidationEntry:
    """Unit tests for the ChainValidationEntry domain model."""

    def test_entry_defaults(self) -> None:
        """Default field values must be correct without explicit assignment."""
        entry = ChainValidationEntry(
            source_fqn="src/a.py::Foo",
            target_fqn="src/b.py::Bar",
        )

        assert entry.chain_depth == 0
        assert entry.lsp_confirmed is False
        assert entry.lsp_error == ""

    def test_entry_stores_provided_values(self) -> None:
        """Explicitly provided values are stored and accessible."""
        entry = ChainValidationEntry(
            source_fqn="pkg::A",
            target_fqn="pkg::B",
            chain_depth=3,
            lsp_confirmed=True,
            lsp_error="timeout",
        )

        assert entry.source_fqn == "pkg::A"
        assert entry.target_fqn == "pkg::B"
        assert entry.chain_depth == 3
        assert entry.lsp_confirmed is True
        assert entry.lsp_error == "timeout"

    def test_entry_lsp_error_is_empty_string_not_none(self) -> None:
        """lsp_error default is an empty string, not None."""
        entry = ChainValidationEntry(source_fqn="a", target_fqn="b")
        assert entry.lsp_error == ""
        assert entry.lsp_error is not None


# ---------------------------------------------------------------------------
# ChainValidation model tests
# ---------------------------------------------------------------------------


class TestChainValidation:
    """Unit tests for the ChainValidation domain model."""

    def test_confirmation_rate_zero_when_no_checks(self) -> None:
        """confirmation_rate must be 0.0 when total_chains_checked is 0."""
        validation = ChainValidation()

        assert validation.total_chains_checked == 0
        assert validation.confirmation_rate == 0.0

    def test_confirmation_rate_correct_ratio(self) -> None:
        """confirmation_rate returns confirmed / total_chains_checked."""
        validation = ChainValidation(
            total_chains_checked=10,
            confirmed=7,
        )

        assert validation.confirmation_rate == pytest.approx(0.7)

    def test_confirmation_rate_full_confirmation(self) -> None:
        """confirmation_rate is 1.0 when all checked are confirmed."""
        validation = ChainValidation(
            total_chains_checked=5,
            confirmed=5,
        )

        assert validation.confirmation_rate == 1.0

    def test_confirmation_rate_no_confirmations(self) -> None:
        """confirmation_rate is 0.0 when none were confirmed."""
        validation = ChainValidation(
            total_chains_checked=8,
            confirmed=0,
        )

        assert validation.confirmation_rate == 0.0

    def test_summary_contains_expected_keys(self) -> None:
        """summary() must return a dict with every documented key."""
        validation = ChainValidation(
            total_chains_checked=4,
            confirmed=2,
            unconfirmed=1,
            errors=1,
            lsp_available=True,
            dead_symbols=["src/mod.py::unused"],
        )

        result = validation.summary()

        expected_keys = {
            "total_checked",
            "confirmed",
            "unconfirmed",
            "errors",
            "confirmation_rate",
            "dead_symbols",
            "lsp_available",
        }
        assert expected_keys == set(result.keys())

    def test_summary_values_match_fields(self) -> None:
        """summary() values must reflect the actual field values."""
        validation = ChainValidation(
            total_chains_checked=6,
            confirmed=3,
            unconfirmed=2,
            errors=1,
            lsp_available=True,
            dead_symbols=["a", "b"],
        )

        result = validation.summary()

        assert result["total_checked"] == 6
        assert result["confirmed"] == 3
        assert result["unconfirmed"] == 2
        assert result["errors"] == 1
        assert result["lsp_available"] is True
        assert result["dead_symbols"] == 2

    def test_summary_confirmation_rate_is_rounded(self) -> None:
        """summary() rounds confirmation_rate to 3 decimal places."""
        validation = ChainValidation(
            total_chains_checked=3,
            confirmed=1,
        )

        result = validation.summary()

        # 1/3 = 0.333...
        assert result["confirmation_rate"] == pytest.approx(0.333, abs=1e-3)

    def test_lsp_available_defaults_to_false(self) -> None:
        """lsp_available is False by default (before any LSP check)."""
        validation = ChainValidation()
        assert validation.lsp_available is False

    def test_dead_symbols_defaults_to_empty(self) -> None:
        """dead_symbols starts as an empty list."""
        validation = ChainValidation()
        assert validation.dead_symbols == []


# ---------------------------------------------------------------------------
# LSPAuditService — circuit breaker tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """Tests for the LSPAuditService failure tracking and circuit breaker."""

    def test_service_starts_enabled(self) -> None:
        """A freshly constructed service must be available."""
        svc = LSPAuditService(project_root="/tmp/proj")

        assert svc.is_available is True
        assert svc._disabled is False
        assert svc._failure_count == 0

    def test_record_failure_increments_count(self) -> None:
        """_record_failure increments _failure_count each time."""
        svc = LSPAuditService()

        svc._record_failure()
        svc._record_failure()

        assert svc._failure_count == 2
        assert svc._disabled is False

    def test_service_disabled_after_max_failures(self) -> None:
        """Circuit breaker trips when _failure_count reaches _MAX_FAILURES."""
        svc = LSPAuditService()

        for _ in range(_MAX_FAILURES):
            svc._record_failure()

        assert svc._disabled is True
        assert svc.is_available is False

    def test_extra_failures_beyond_threshold_keep_disabled(self) -> None:
        """Additional failures after the breaker trips do not un-disable."""
        svc = LSPAuditService()

        for _ in range(_MAX_FAILURES + 5):
            svc._record_failure()

        assert svc._disabled is True

    def test_circuit_breaker_reset_on_success(self) -> None:
        """_reset_failures sets failure count back to zero."""
        svc = LSPAuditService()
        svc._failure_count = 2

        svc._reset_failures()

        assert svc._failure_count == 0

    def test_reset_does_not_re_enable_after_disable(self) -> None:
        """Resetting failures does not re-enable a tripped breaker (by design)."""
        svc = LSPAuditService()
        for _ in range(_MAX_FAILURES):
            svc._record_failure()

        # _reset_failures only clears the counter, not the _disabled flag
        svc._reset_failures()

        assert svc._failure_count == 0
        # _disabled flag is sticky — this documents the current contract
        assert svc._disabled is True


# ---------------------------------------------------------------------------
# LSPAuditService — health check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """Tests for health_check_async."""

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_disabled(self) -> None:
        """health_check_async must return False when the circuit breaker is open."""
        svc = LSPAuditService()
        svc._disabled = True

        result = await svc.health_check_async()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_analyzer_unavailable(self) -> None:
        """health_check_async returns False when SemanticAnalyzer cannot init."""
        svc = LSPAuditService()

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            side_effect=RuntimeError("pyright not found"),
        ):
            result = await svc.health_check_async()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_python_lsp_unavailable(self) -> None:
        """health_check_async is False when LSPManager says Python LSP is missing."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        mock_mgr = MagicMock()
        mock_mgr.is_available.return_value = False

        # LSPManager is imported locally inside health_check_async, so we must
        # patch it at its definition site (warden.lsp.manager), not as a
        # module-level attribute of audit_service (where it does not exist).
        with (
            patch(
                "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
                return_value=mock_analyzer,
            ),
            patch(
                "warden.lsp.manager.LSPManager.get_instance",
                return_value=mock_mgr,
            ),
        ):
            result = await svc.health_check_async()

        assert result is False
        mock_mgr.is_available.assert_called_once_with("python")

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_python_lsp_available(self) -> None:
        """health_check_async is True when Python LSP is available."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        mock_mgr = MagicMock()
        mock_mgr.is_available.return_value = True

        with (
            patch(
                "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
                return_value=mock_analyzer,
            ),
            patch(
                "warden.lsp.manager.LSPManager.get_instance",
                return_value=mock_mgr,
            ),
        ):
            result = await svc.health_check_async()

        assert result is True


# ---------------------------------------------------------------------------
# LSPAuditService — validate_dependency_chain_async
# ---------------------------------------------------------------------------


class TestValidateDependencyChain:
    """Tests for the main validate_dependency_chain_async method."""

    @pytest.mark.asyncio
    async def test_validate_empty_graph_returns_empty_validation(self) -> None:
        """An empty CodeGraph produces a ChainValidation with zero checks."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ):
            result = await svc.validate_dependency_chain_async(CodeGraph())

        assert result.total_chains_checked == 0
        assert result.confirmed == 0
        assert result.unconfirmed == 0
        assert result.errors == 0
        assert result.entries == []
        assert result.dead_symbols == []

    @pytest.mark.asyncio
    async def test_validate_returns_empty_when_analyzer_unavailable(self) -> None:
        """If analyzer cannot be obtained, return an empty ChainValidation."""
        svc = LSPAuditService()

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            side_effect=RuntimeError("no LSP"),
        ):
            result = await svc.validate_dependency_chain_async(CodeGraph())

        assert result.total_chains_checked == 0
        assert result.lsp_available is False

    @pytest.mark.asyncio
    async def test_validate_sets_lsp_available_flag(self) -> None:
        """lsp_available must be True when the analyzer is successfully obtained."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        # No callees found → edge treated as undetermined (None)
        mock_analyzer.get_callees_async = AsyncMock(return_value=[])
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=True)

        graph, _, _ = _make_graph_with_calls_edge()

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ):
            result = await svc.validate_dependency_chain_async(graph)

        assert result.lsp_available is True

    @pytest.mark.asyncio
    async def test_validate_with_mocked_analyzer_confirmed_call(self) -> None:
        """When get_callees_async returns results, the edge is marked confirmed."""
        svc = LSPAuditService()
        mock_sym = MagicMock()
        mock_analyzer = MagicMock()
        mock_analyzer.get_callees_async = AsyncMock(return_value=[mock_sym])
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=True)

        graph, src_node, edge = _make_graph_with_calls_edge()

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ):
            result = await svc.validate_dependency_chain_async(graph)

        assert result.confirmed == 1
        assert result.unconfirmed == 0
        assert result.errors == 0
        assert len(result.entries) == 1
        assert result.entries[0].lsp_confirmed is True

    @pytest.mark.asyncio
    async def test_validate_counts_unconfirmed_when_no_callees(self) -> None:
        """Empty callee list → edge is neither confirmed nor an error (undetermined)."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        # get_callees returns [] → _check_call_async returns None (undetermined)
        mock_analyzer.get_callees_async = AsyncMock(return_value=[])
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=True)

        graph, _, _ = _make_graph_with_calls_edge()

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ):
            result = await svc.validate_dependency_chain_async(graph)

        # Undetermined edges increment errors (None path in the main loop)
        assert result.confirmed == 0
        assert result.errors == 1

    @pytest.mark.asyncio
    async def test_validate_records_error_on_missing_source_node(self) -> None:
        """An edge whose source_fqn has no node in graph.nodes gets an error entry."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=True)

        graph = CodeGraph()
        # Add only the target node, not the source node
        target_node = _make_node("src/b.py::callee")
        graph.add_node(target_node)
        # Edge references a source that doesn't exist in nodes
        graph.add_edge(_make_edge("src/a.py::missing", "src/b.py::callee"))

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ):
            result = await svc.validate_dependency_chain_async(graph)

        assert result.errors == 1
        assert result.entries[0].lsp_error == "source_node_missing"

    @pytest.mark.asyncio
    async def test_validate_respects_max_checks_limit(self) -> None:
        """Only up to max_checks edges are processed."""
        svc = LSPAuditService()
        mock_sym = MagicMock()
        mock_analyzer = MagicMock()
        mock_analyzer.get_callees_async = AsyncMock(return_value=[mock_sym])
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=True)

        graph = CodeGraph()
        for i in range(10):
            node = _make_node(f"src/mod.py::func_{i}", name=f"func_{i}")
            graph.add_node(node)
        # Add 10 self-loop edges for simplicity
        for i in range(10):
            fqn = f"src/mod.py::func_{i}"
            graph.add_edge(_make_edge(fqn, fqn))

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ):
            result = await svc.validate_dependency_chain_async(graph, max_checks=3)

        assert result.total_chains_checked == 3

    @pytest.mark.asyncio
    async def test_validate_increments_errors_on_analyzer_exception(self) -> None:
        """Exceptions from the LSP call propagate as errors with failure tracking.

        _check_call_async catches the raw exception internally and returns None.
        The outer validate loop therefore takes the `else` branch and marks the
        entry as "undetermined".  _check_call_async also calls _record_failure,
        so the failure counter rises.  The dead-symbol pass uses is_symbol_used_async
        returning None (undetermined) so it does not reset the failure counter.
        """
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        mock_analyzer.get_callees_async = AsyncMock(side_effect=ConnectionError("LSP died"))
        # Return None so the dead-symbol pass neither resets nor increments
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=None)

        graph, _, _ = _make_graph_with_calls_edge()

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ):
            result = await svc.validate_dependency_chain_async(graph)

        # The exception is absorbed by _check_call_async, which returns None.
        # The outer loop marks it as "undetermined" → errors += 1.
        assert result.errors >= 1
        assert result.entries[0].lsp_error == "undetermined"
        # _check_call_async called _record_failure on the exception
        assert svc._failure_count >= 1

    @pytest.mark.asyncio
    async def test_validate_handles_inherits_edge(self) -> None:
        """INHERITS edges are dispatched to _check_hierarchy_async."""
        svc = LSPAuditService()
        mock_sym = MagicMock()
        mock_analyzer = MagicMock()
        mock_analyzer.get_parent_classes_async = AsyncMock(return_value=[mock_sym])
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=True)

        graph = CodeGraph()
        parent = _make_node("src/base.py::Base", name="Base", kind=SymbolKind.CLASS)
        child = _make_node("src/child.py::Child", name="Child", kind=SymbolKind.CLASS)
        graph.add_node(parent)
        graph.add_node(child)
        graph.add_edge(_make_edge("src/child.py::Child", "src/base.py::Base", EdgeRelation.INHERITS))

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ):
            result = await svc.validate_dependency_chain_async(graph)

        assert result.confirmed == 1
        mock_analyzer.get_parent_classes_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_imports_edge_is_undetermined(self) -> None:
        """IMPORTS edges cannot be verified by LSP — they become errors (None)."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=True)

        graph = CodeGraph()
        mod_a = _make_node("src/a.py::a", name="a")
        mod_b = _make_node("src/b.py::b", name="b")
        graph.add_node(mod_a)
        graph.add_node(mod_b)
        graph.add_edge(_make_edge("src/a.py::a", "src/b.py::b", EdgeRelation.IMPORTS))

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ):
            result = await svc.validate_dependency_chain_async(graph)

        # None returned by _check_edge_async increments errors
        assert result.errors == 1
        assert result.confirmed == 0


# ---------------------------------------------------------------------------
# LSPAuditService — dead symbol detection
# ---------------------------------------------------------------------------


class TestDeadSymbolDetection:
    """Tests for _detect_dead_symbols_async behaviour."""

    @pytest.mark.asyncio
    async def test_dead_symbol_detection_finds_unused_symbol(self) -> None:
        """Symbols where is_symbol_used_async returns False are reported as dead."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        # All calls checked → treated as unused
        mock_analyzer.get_callees_async = AsyncMock(return_value=[])
        # is_symbol_used_async: first call (for the source node) returns False
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=False)

        graph = CodeGraph()
        unused_node = _make_node("src/util.py::orphan", name="orphan")
        graph.add_node(unused_node)

        dead = await svc._detect_dead_symbols_async(mock_analyzer, graph)

        assert "src/util.py::orphan" in dead

    @pytest.mark.asyncio
    async def test_dead_symbol_detection_skips_test_nodes(self) -> None:
        """Test nodes are skipped during dead symbol detection."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=False)

        graph = CodeGraph()
        test_node = _make_node(
            "tests/test_mod.py::test_thing",
            name="test_thing",
            is_test=True,
        )
        graph.add_node(test_node)

        dead = await svc._detect_dead_symbols_async(mock_analyzer, graph)

        assert dead == []
        mock_analyzer.is_symbol_used_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_dead_symbol_detection_skips_module_kind(self) -> None:
        """Module-kind nodes are skipped (they are always 'imported')."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=False)

        graph = CodeGraph()
        mod_node = _make_node(
            "src/pkg/__init__.py::pkg",
            name="pkg",
            kind=SymbolKind.MODULE,
        )
        graph.add_node(mod_node)

        dead = await svc._detect_dead_symbols_async(mock_analyzer, graph)

        assert dead == []
        mock_analyzer.is_symbol_used_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_dead_symbol_detection_used_symbol_not_dead(self) -> None:
        """Symbols where is_symbol_used_async returns True are not reported."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=True)

        graph = CodeGraph()
        used_node = _make_node("src/mod.py::active_func", name="active_func")
        graph.add_node(used_node)

        dead = await svc._detect_dead_symbols_async(mock_analyzer, graph)

        assert dead == []

    @pytest.mark.asyncio
    async def test_dead_symbol_detection_none_result_skipped(self) -> None:
        """When is_symbol_used_async returns None (undetermined), symbol is not marked dead."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=None)

        graph = CodeGraph()
        node = _make_node("src/mod.py::maybe", name="maybe")
        graph.add_node(node)

        dead = await svc._detect_dead_symbols_async(mock_analyzer, graph)

        assert dead == []

    @pytest.mark.asyncio
    async def test_dead_symbol_detection_stops_when_disabled(self) -> None:
        """If the circuit breaker trips during detection, the loop exits early."""
        svc = LSPAuditService()
        # Trip the breaker immediately
        svc._disabled = True

        mock_analyzer = MagicMock()
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=False)

        graph = CodeGraph()
        for i in range(5):
            graph.add_node(_make_node(f"src/mod.py::f{i}", name=f"f{i}"))

        dead = await svc._detect_dead_symbols_async(mock_analyzer, graph)

        assert dead == []
        mock_analyzer.is_symbol_used_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_dead_symbol_detection_exception_triggers_failure(self) -> None:
        """Exceptions from is_symbol_used_async call _record_failure."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        mock_analyzer.is_symbol_used_async = AsyncMock(side_effect=TimeoutError("timeout"))

        graph = CodeGraph()
        graph.add_node(_make_node("src/mod.py::func", name="func"))

        original_count = svc._failure_count
        await svc._detect_dead_symbols_async(mock_analyzer, graph)

        assert svc._failure_count > original_count

    @pytest.mark.asyncio
    async def test_dead_symbol_detection_respects_max_checks(self) -> None:
        """At most max_checks symbols are inspected."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=True)

        graph = CodeGraph()
        for i in range(20):
            graph.add_node(_make_node(f"src/mod.py::f{i}", name=f"f{i}"))

        await svc._detect_dead_symbols_async(mock_analyzer, graph, max_checks=5)

        assert mock_analyzer.is_symbol_used_async.call_count == 5


# ---------------------------------------------------------------------------
# LSPAuditService — circuit breaker integration (via full validate)
# ---------------------------------------------------------------------------


class TestCircuitBreakerIntegration:
    """Integration-level circuit breaker tests that exercise the full flow."""

    @pytest.mark.asyncio
    async def test_failures_accumulated_across_edges(self) -> None:
        """Each failing edge increments failure count.

        _check_call_async catches the exception and calls _record_failure.
        To prevent the subsequent dead-symbol pass from resetting the counter
        (which would happen if is_symbol_used_async returned True), we return
        None (undetermined) so neither _reset_failures nor _record_failure is
        called during the dead-symbol phase.
        """
        svc = LSPAuditService()
        mock_analyzer = MagicMock()
        mock_analyzer.get_callees_async = AsyncMock(
            side_effect=RuntimeError("connection lost")
        )
        # None: undetermined → does not call _reset_failures
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=None)

        graph = CodeGraph()
        for i in range(2):
            node = _make_node(f"src/mod.py::fn{i}", name=f"fn{i}")
            graph.add_node(node)
            graph.add_edge(_make_edge(f"src/mod.py::fn{i}", f"src/mod.py::fn{i}"))

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ):
            await svc.validate_dependency_chain_async(graph)

        assert svc._failure_count >= 2

    @pytest.mark.asyncio
    async def test_circuit_breaker_stops_processing_mid_graph(self) -> None:
        """Once the breaker trips, remaining edges are skipped."""
        svc = LSPAuditService()
        # Pre-set failure count to one below the threshold
        svc._failure_count = _MAX_FAILURES - 1

        call_count = 0

        async def failing_callees(*args: Any, **kwargs: Any) -> list[Any]:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("LSP error")

        mock_analyzer = MagicMock()
        mock_analyzer.get_callees_async = failing_callees
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=True)

        # Build a graph with 5 CALLS edges; only 1 should be processed before disable
        graph = CodeGraph()
        for i in range(5):
            node = _make_node(f"src/mod.py::f{i}", name=f"f{i}")
            graph.add_node(node)
            graph.add_edge(_make_edge(f"src/mod.py::f{i}", f"src/mod.py::f{i}"))

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ):
            result = await svc.validate_dependency_chain_async(graph)

        # Should have been disabled after first failure and stopped iterating
        assert svc._disabled is True
        # Not all 5 edges should have been checked
        assert result.total_chains_checked < 5 or call_count < 5

    @pytest.mark.asyncio
    async def test_successful_check_resets_failure_count(self) -> None:
        """A confirmed edge resets the failure counter to zero."""
        svc = LSPAuditService()
        svc._failure_count = 2  # Approaching threshold but not there yet

        mock_sym = MagicMock()
        mock_analyzer = MagicMock()
        mock_analyzer.get_callees_async = AsyncMock(return_value=[mock_sym])
        mock_analyzer.is_symbol_used_async = AsyncMock(return_value=True)

        graph, _, _ = _make_graph_with_calls_edge()

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ):
            result = await svc.validate_dependency_chain_async(graph)

        assert result.confirmed == 1
        assert svc._failure_count == 0

    @pytest.mark.asyncio
    async def test_get_analyzer_returns_none_when_disabled(self) -> None:
        """_get_analyzer returns None immediately when service is disabled."""
        svc = LSPAuditService()
        svc._disabled = True

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance"
        ) as mock_get:
            result = svc._get_analyzer()

        assert result is None
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_analyzer_caches_instance(self) -> None:
        """_get_analyzer does not call get_instance twice when instance exists."""
        svc = LSPAuditService()
        mock_analyzer = MagicMock()

        with patch(
            "warden.lsp.audit_service.SemanticAnalyzer.get_instance",
            return_value=mock_analyzer,
        ) as mock_get:
            first = svc._get_analyzer()
            second = svc._get_analyzer()

        assert first is second
        # get_instance was only called once (second call uses cached _analyzer)
        assert mock_get.call_count == 1
