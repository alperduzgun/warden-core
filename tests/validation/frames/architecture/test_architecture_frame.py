"""Tests for ArchitectureFrame."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from warden.analysis.domain.code_graph import (
    CodeGraph,
    EdgeRelation,
    GapReport,
    SymbolEdge,
    SymbolKind,
    SymbolNode,
)
from warden.validation.domain.frame import CodeFile
from warden.validation.frames.architecture.architecture_frame import (
    ArchitectureFrame,
    FileGaps,
    _build_file_gap_map,
    _finding_id_to_gap_type,
    _gaps_to_findings,
    _parse_llm_verdict,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_code_file(path: str = "src/app/main.py", content: str = "# empty") -> CodeFile:
    return CodeFile(path=path, content=content, language="python")


def _make_context(
    gap_report: GapReport | None = None,
    code_graph: CodeGraph | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.gap_report = gap_report
    ctx.code_graph = code_graph
    return ctx


def _make_node(fqn: str, file_path: str, kind: SymbolKind = SymbolKind.CLASS) -> SymbolNode:
    name = fqn.split("::")[-1] if "::" in fqn else fqn
    return SymbolNode(fqn=fqn, name=name, kind=kind, file_path=file_path)


# ---------------------------------------------------------------------------
# Unit tests: _build_file_gap_map
# ---------------------------------------------------------------------------


class TestBuildFileGapMap:
    """Tests for the _build_file_gap_map helper."""

    def test_empty_gap_report(self):
        report = GapReport()
        result = _build_file_gap_map(report, None)
        assert result == {}

    def test_orphan_files_mapped(self):
        report = GapReport(orphan_files=["src/utils.py", "src/dead.py"])
        result = _build_file_gap_map(report, None)
        assert result["src/utils.py"].is_orphan is True
        assert result["src/dead.py"].is_orphan is True

    def test_unreachable_files_mapped(self):
        report = GapReport(unreachable_from_entry=["src/internal.py"])
        result = _build_file_gap_map(report, None)
        assert result["src/internal.py"].is_unreachable is True

    def test_unparseable_files_mapped(self):
        report = GapReport(unparseable_files=["src/broken.py"])
        result = _build_file_gap_map(report, None)
        assert result["src/broken.py"].is_unparseable is True

    def test_star_imports_mapped(self):
        report = GapReport(star_imports=["src/init.py"])
        result = _build_file_gap_map(report, None)
        assert result["src/init.py"].has_star_imports is True

    def test_dynamic_imports_mapped(self):
        report = GapReport(dynamic_imports=["src/loader.py"])
        result = _build_file_gap_map(report, None)
        assert result["src/loader.py"].has_dynamic_imports is True

    def test_broken_imports_attributed_to_source_file(self):
        """Broken imports should be attributed to the file doing the import."""
        graph = CodeGraph()
        graph.add_node(_make_node(
            "src/app/main.py::Main",
            "src/app/main.py",
        ))
        graph.add_edge(SymbolEdge(
            source="src/app/main.py::Main",
            target="warden.missing.Module",
            relation=EdgeRelation.IMPORTS,
        ))

        report = GapReport(broken_imports=["warden.missing.Module"])
        result = _build_file_gap_map(report, graph)

        assert "src/app/main.py" in result
        assert "warden.missing.Module" in result["src/app/main.py"].broken_imports

    def test_broken_imports_no_code_graph(self):
        """Without code_graph, broken imports cannot be attributed."""
        report = GapReport(broken_imports=["warden.missing.Module"])
        result = _build_file_gap_map(report, None)
        # No file attribution possible without code_graph
        assert all(
            len(fg.broken_imports) == 0 for fg in result.values()
        )

    def test_circular_deps_attributed_to_cycle_files(self):
        graph = CodeGraph()
        graph.add_node(_make_node("src/a.py::A", "src/a.py"))
        graph.add_node(_make_node("src/b.py::B", "src/b.py"))

        cycle = ["src/a.py::A", "src/b.py::B", "src/a.py::A"]
        report = GapReport(circular_deps=[cycle])
        result = _build_file_gap_map(report, graph)

        assert "src/a.py" in result
        assert "src/b.py" in result
        assert len(result["src/a.py"].in_circular_dep) == 1
        assert len(result["src/b.py"].in_circular_dep) == 1

    def test_missing_mixin_impl_attributed_to_defining_file(self):
        graph = CodeGraph()
        graph.add_node(_make_node(
            "src/base.py::MyMixin",
            "src/base.py",
            kind=SymbolKind.MIXIN,
        ))

        report = GapReport(missing_mixin_impl=["src/base.py::MyMixin"])
        result = _build_file_gap_map(report, graph)

        assert "src/base.py" in result
        assert "src/base.py::MyMixin" in result["src/base.py"].missing_mixin_impls

    def test_multiple_gaps_same_file(self):
        """A single file can have multiple gap types."""
        graph = CodeGraph()
        graph.add_node(_make_node("src/messy.py::X", "src/messy.py"))
        graph.add_edge(SymbolEdge(
            source="src/messy.py::X",
            target="missing.mod",
            relation=EdgeRelation.IMPORTS,
        ))

        report = GapReport(
            orphan_files=["src/messy.py"],
            broken_imports=["missing.mod"],
            star_imports=["src/messy.py"],
        )
        result = _build_file_gap_map(report, graph)

        fg = result["src/messy.py"]
        assert fg.is_orphan is True
        assert fg.has_star_imports is True
        assert "missing.mod" in fg.broken_imports


# ---------------------------------------------------------------------------
# Unit tests: _gaps_to_findings
# ---------------------------------------------------------------------------


class TestGapsToFindings:
    """Tests for _gaps_to_findings helper."""

    def test_empty_gaps_no_findings(self):
        gaps = FileGaps()
        cf = _make_code_file()
        findings = _gaps_to_findings(gaps, cf, "architecture")
        assert findings == []

    def test_broken_import_finding(self):
        gaps = FileGaps(broken_imports=["foo.bar.Baz"])
        cf = _make_code_file()
        findings = _gaps_to_findings(gaps, cf, "architecture")
        assert len(findings) == 1
        assert findings[0].severity == "high"
        assert "foo.bar.Baz" in findings[0].message

    def test_circular_dep_finding(self):
        cycle = ["A::X", "B::Y", "A::X"]
        gaps = FileGaps(in_circular_dep=[cycle])
        cf = _make_code_file()
        findings = _gaps_to_findings(gaps, cf, "architecture")
        assert len(findings) == 1
        assert findings[0].severity == "medium"
        assert "A::X" in findings[0].message

    def test_unparseable_finding(self):
        gaps = FileGaps(is_unparseable=True)
        cf = _make_code_file()
        findings = _gaps_to_findings(gaps, cf, "architecture")
        assert len(findings) == 1
        assert findings[0].severity == "high"

    def test_orphan_finding(self):
        gaps = FileGaps(is_orphan=True)
        cf = _make_code_file()
        findings = _gaps_to_findings(gaps, cf, "architecture")
        assert len(findings) == 1
        assert findings[0].severity == "low"

    def test_unreachable_finding(self):
        gaps = FileGaps(is_unreachable=True)
        cf = _make_code_file()
        findings = _gaps_to_findings(gaps, cf, "architecture")
        assert len(findings) == 1
        assert findings[0].severity == "low"

    def test_star_import_finding(self):
        gaps = FileGaps(has_star_imports=True)
        cf = _make_code_file()
        findings = _gaps_to_findings(gaps, cf, "architecture")
        assert len(findings) == 1
        assert findings[0].severity == "low"

    def test_dynamic_import_finding(self):
        gaps = FileGaps(has_dynamic_imports=True)
        cf = _make_code_file()
        findings = _gaps_to_findings(gaps, cf, "architecture")
        assert len(findings) == 1
        assert findings[0].severity == "low"

    def test_missing_mixin_finding_uses_short_name(self):
        gaps = FileGaps(missing_mixin_impls=["src/base.py::MyMixin"])
        cf = _make_code_file()
        findings = _gaps_to_findings(gaps, cf, "architecture")
        assert len(findings) == 1
        assert "MyMixin" in findings[0].message
        assert findings[0].severity == "medium"

    def test_multiple_findings_unique_ids(self):
        gaps = FileGaps(
            broken_imports=["a.b", "c.d"],
            is_orphan=True,
            has_star_imports=True,
        )
        cf = _make_code_file()
        findings = _gaps_to_findings(gaps, cf, "architecture")
        assert len(findings) == 4
        ids = [f.id for f in findings]
        assert len(set(ids)) == 4  # All unique

    def test_finding_location_includes_file_path(self):
        gaps = FileGaps(is_orphan=True)
        cf = _make_code_file("my/file.py")
        findings = _gaps_to_findings(gaps, cf, "arch")
        assert findings[0].location == "my/file.py:1"


# ---------------------------------------------------------------------------
# Integration tests: ArchitectureFrame.execute_async
# ---------------------------------------------------------------------------


class TestArchitectureFrameExecute:
    """Integration tests for ArchitectureFrame.execute_async."""

    @pytest.mark.asyncio
    async def test_no_context_returns_passed(self):
        frame = ArchitectureFrame()
        cf = _make_code_file()
        result = await frame.execute_async(cf, context=None)
        assert result.status == "passed"
        assert result.findings == []

    @pytest.mark.asyncio
    async def test_context_without_gap_report_returns_passed(self):
        frame = ArchitectureFrame()
        ctx = _make_context(gap_report=None)
        cf = _make_code_file()
        result = await frame.execute_async(cf, context=ctx)
        assert result.status == "passed"
        assert result.metadata["reason"] == "no_gap_report"

    @pytest.mark.asyncio
    async def test_empty_gap_report_returns_passed(self):
        frame = ArchitectureFrame()
        ctx = _make_context(gap_report=GapReport(), code_graph=CodeGraph())
        cf = _make_code_file("src/clean.py")
        result = await frame.execute_async(cf, context=ctx)
        assert result.status == "passed"
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_file_with_gaps_returns_warning(self):
        report = GapReport(orphan_files=["src/dead.py"])
        frame = ArchitectureFrame()
        ctx = _make_context(gap_report=report, code_graph=CodeGraph())
        cf = _make_code_file("src/dead.py")
        result = await frame.execute_async(cf, context=ctx)
        assert result.status == "warning"
        assert result.issues_found == 1
        assert result.findings[0].severity == "low"

    @pytest.mark.asyncio
    async def test_file_without_gaps_returns_passed(self):
        """A file not in the gap map should pass."""
        report = GapReport(orphan_files=["src/dead.py"])
        frame = ArchitectureFrame()
        ctx = _make_context(gap_report=report, code_graph=CodeGraph())
        cf = _make_code_file("src/clean.py")
        result = await frame.execute_async(cf, context=ctx)
        assert result.status == "passed"
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_broken_import_produces_high_severity(self):
        graph = CodeGraph()
        graph.add_node(_make_node("src/app.py::App", "src/app.py"))
        graph.add_edge(SymbolEdge(
            source="src/app.py::App",
            target="missing.pkg",
            relation=EdgeRelation.IMPORTS,
        ))
        report = GapReport(broken_imports=["missing.pkg"])

        frame = ArchitectureFrame()
        ctx = _make_context(gap_report=report, code_graph=graph)
        cf = _make_code_file("src/app.py")
        result = await frame.execute_async(cf, context=ctx)

        assert result.status == "warning"
        assert any(f.severity == "high" for f in result.findings)
        assert "missing.pkg" in result.findings[0].message

    @pytest.mark.asyncio
    async def test_lazy_init_only_builds_once(self):
        """The gap map should only be built on the first call."""
        report = GapReport(orphan_files=["src/a.py"])
        frame = ArchitectureFrame()
        ctx = _make_context(gap_report=report, code_graph=CodeGraph())

        # First call: builds map
        r1 = await frame.execute_async(_make_code_file("src/a.py"), context=ctx)
        assert r1.status == "warning"

        # Second call: reuses map (even though we pass a different context)
        ctx2 = _make_context(gap_report=GapReport(), code_graph=CodeGraph())
        r2 = await frame.execute_async(_make_code_file("src/a.py"), context=ctx2)
        # Should still find the gap from the first build
        assert r2.status == "warning"

    @pytest.mark.asyncio
    async def test_frame_id_is_architecture(self):
        frame = ArchitectureFrame()
        assert frame.frame_id == "architecture"

    @pytest.mark.asyncio
    async def test_is_not_blocker(self):
        frame = ArchitectureFrame()
        assert frame.is_blocker is False

    @pytest.mark.asyncio
    async def test_metadata_contains_gap_counts(self):
        report = GapReport(
            orphan_files=["src/orphan.py"],
            star_imports=["src/orphan.py"],
        )
        frame = ArchitectureFrame()
        ctx = _make_context(gap_report=report, code_graph=CodeGraph())
        cf = _make_code_file("src/orphan.py")
        result = await frame.execute_async(cf, context=ctx)

        assert result.metadata is not None
        assert result.metadata["is_orphan"] is True
        assert result.metadata["has_star_imports"] is True

    @pytest.mark.asyncio
    async def test_path_normalization_with_src_prefix(self):
        """Path matching should work regardless of src/ prefix."""
        report = GapReport(orphan_files=["app/main.py"])
        frame = ArchitectureFrame()
        ctx = _make_context(gap_report=report, code_graph=CodeGraph())

        # Code file path has src/ prefix, gap report doesn't
        cf = _make_code_file("src/app/main.py")
        result = await frame.execute_async(cf, context=ctx)
        # Should match via normalization fallback
        assert result.status == "warning"

    @pytest.mark.asyncio
    async def test_circular_dep_with_code_graph(self):
        graph = CodeGraph()
        graph.add_node(_make_node("src/a.py::A", "src/a.py"))
        graph.add_node(_make_node("src/b.py::B", "src/b.py"))

        cycle = ["src/a.py::A", "src/b.py::B", "src/a.py::A"]
        report = GapReport(circular_deps=[cycle])

        frame = ArchitectureFrame()
        ctx = _make_context(gap_report=report, code_graph=graph)

        result_a = await frame.execute_async(_make_code_file("src/a.py"), context=ctx)
        assert result_a.status == "warning"
        assert any("Circular dependency" in f.message for f in result_a.findings)

        # New frame instance for file b (lazy init uses same map, but let's test fresh)
        frame2 = ArchitectureFrame()
        ctx2 = _make_context(gap_report=report, code_graph=graph)
        result_b = await frame2.execute_async(_make_code_file("src/b.py"), context=ctx2)
        assert result_b.status == "warning"


# ---------------------------------------------------------------------------
# Unit tests: _finding_id_to_gap_type
# ---------------------------------------------------------------------------


class TestFindingIdToGapType:
    def test_orphan_file(self):
        assert _finding_id_to_gap_type("architecture-orphan-file-0") == "orphan_file"

    def test_unreachable(self):
        assert _finding_id_to_gap_type("architecture-unreachable-0") == "unreachable"

    def test_broken_import(self):
        assert _finding_id_to_gap_type("architecture-broken-import-1") == "broken_import"

    def test_missing_mixin(self):
        assert _finding_id_to_gap_type("architecture-missing-mixin-0") == "missing_mixin"

    def test_short_id_returns_empty(self):
        assert _finding_id_to_gap_type("x") == ""


# ---------------------------------------------------------------------------
# Unit tests: _parse_llm_verdict
# ---------------------------------------------------------------------------


class TestParseLlmVerdict:
    def test_valid_json(self):
        result = _parse_llm_verdict('{"is_true_positive": false, "confidence": 0.9, "reason": "framework managed"}')
        assert result["is_true_positive"] is False
        assert result["confidence"] == 0.9

    def test_json_with_code_fence(self):
        result = _parse_llm_verdict('```json\n{"is_true_positive": true, "confidence": 0.8, "reason": "dead code"}\n```')
        assert result["is_true_positive"] is True

    def test_invalid_json_returns_default(self):
        result = _parse_llm_verdict("This is not JSON")
        assert result["is_true_positive"] is True
        assert result["reason"] == "parse_error"


# ---------------------------------------------------------------------------
# Integration tests: LLM verification
# ---------------------------------------------------------------------------


class TestArchitectureFrameLlmVerification:
    """Tests for opt-in LLM verification in ArchitectureFrame."""

    @pytest.mark.asyncio
    async def test_llm_verification_disabled_by_default(self):
        """Without use_llm_verification, no LLM calls are made."""
        report = GapReport(orphan_files=["src/dead.py"])
        frame = ArchitectureFrame()  # Default config
        ctx = _make_context(gap_report=report, code_graph=CodeGraph())
        cf = _make_code_file("src/dead.py")
        result = await frame.execute_async(cf, context=ctx)

        assert result.status == "warning"
        assert result.issues_found == 1
        # metadata should NOT have llm_verified key (or it's False)
        assert result.metadata.get("llm_verified") is not True

    @pytest.mark.asyncio
    async def test_llm_verification_filters_false_positive(self):
        """With LLM verification enabled, false positives are removed."""
        report = GapReport(orphan_files=["src/plugin.py"])
        graph = CodeGraph()
        graph.add_node(_make_node("src/plugin.py::Plugin", "src/plugin.py"))

        # Mock LLM service that says it's a false positive
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"is_true_positive": false, "confidence": 0.95, "reason": "dynamically loaded plugin"}'
        mock_llm.complete_async = AsyncMock(return_value=mock_response)

        ctx = _make_context(gap_report=report, code_graph=graph)
        ctx.llm_service = mock_llm

        frame = ArchitectureFrame(config={"use_llm_verification": True})
        cf = _make_code_file("src/plugin.py", content="# Plugin utilities\nclass Plugin:\n    pass")
        result = await frame.execute_async(cf, context=ctx)

        # Finding should be filtered out
        assert result.issues_found == 0
        assert result.metadata.get("llm_verified") is True

    @pytest.mark.asyncio
    async def test_llm_verification_keeps_true_positive(self):
        """LLM confirms a true positive — finding stays."""
        report = GapReport(orphan_files=["src/dead.py"])
        graph = CodeGraph()
        graph.add_node(_make_node("src/dead.py::Dead", "src/dead.py"))

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"is_true_positive": true, "confidence": 0.9, "reason": "unused code"}'
        mock_llm.complete_async = AsyncMock(return_value=mock_response)

        ctx = _make_context(gap_report=report, code_graph=graph)
        ctx.llm_service = mock_llm

        frame = ArchitectureFrame(config={"use_llm_verification": True})
        cf = _make_code_file("src/dead.py")
        result = await frame.execute_async(cf, context=ctx)

        assert result.issues_found == 1

    @pytest.mark.asyncio
    async def test_llm_verification_fail_open_on_error(self):
        """If LLM fails, findings are kept (fail-open)."""
        report = GapReport(orphan_files=["src/risky.py"])
        graph = CodeGraph()
        graph.add_node(_make_node("src/risky.py::Risky", "src/risky.py"))

        mock_llm = MagicMock()
        mock_llm.complete_async = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        ctx = _make_context(gap_report=report, code_graph=graph)
        ctx.llm_service = mock_llm

        frame = ArchitectureFrame(config={"use_llm_verification": True})
        cf = _make_code_file("src/risky.py")
        result = await frame.execute_async(cf, context=ctx)

        # Should still have the finding (fail-open)
        assert result.issues_found == 1

    @pytest.mark.asyncio
    async def test_non_verifiable_types_pass_through(self):
        """Broken imports and other types skip LLM verification."""
        graph = CodeGraph()
        graph.add_node(_make_node("src/app.py::App", "src/app.py"))
        graph.add_edge(SymbolEdge(
            source="src/app.py::App",
            target="missing.pkg",
            relation=EdgeRelation.IMPORTS,
        ))
        report = GapReport(broken_imports=["missing.pkg"])

        mock_llm = MagicMock()
        # LLM should not be called for broken imports
        mock_llm.complete_async = AsyncMock(side_effect=AssertionError("Should not be called"))

        ctx = _make_context(gap_report=report, code_graph=graph)
        ctx.llm_service = mock_llm

        frame = ArchitectureFrame(config={"use_llm_verification": True})
        cf = _make_code_file("src/app.py")
        result = await frame.execute_async(cf, context=ctx)

        # Broken import should be present (not sent to LLM)
        assert result.issues_found >= 1
        assert any("missing.pkg" in f.message for f in result.findings)
