"""E2E tests for the MCP AuditAdapter (warden_get_audit_context, warden_query_symbol).

These test the adapter directly without a running MCP server,
verifying the tools produce correct results from intelligence files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from warden.mcp.infrastructure.adapters.audit_adapter import AuditAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_intel_dir(base: Path) -> Path:
    intel_dir = base / ".warden" / "intelligence"
    intel_dir.mkdir(parents=True, exist_ok=True)
    return intel_dir


def _write_code_graph(intel_dir: Path) -> None:
    data = {
        "schema_version": "1.0.0",
        "generated_at": "2026-02-20T10:00:00Z",
        "nodes": {
            "src/app.py::App": {
                "fqn": "src/app.py::App",
                "name": "App",
                "kind": "class",
                "file_path": "src/app.py",
                "line": 10,
                "module": "app",
            },
            "src/service.py::Service": {
                "fqn": "src/service.py::Service",
                "name": "Service",
                "kind": "class",
                "file_path": "src/service.py",
                "line": 5,
                "module": "service",
            },
        },
        "edges": [
            {
                "source": "src/app.py::App",
                "target": "src/service.py::Service",
                "relation": "calls",
            },
        ],
        "stats": {
            "total_nodes": 2,
            "total_edges": 1,
            "classes": 2,
            "functions": 0,
            "test_nodes": 0,
        },
    }
    (intel_dir / "code_graph.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_gap_report(intel_dir: Path, broken_imports: list[str] | None = None) -> None:
    data = {
        "orphanFiles": [],
        "orphanSymbols": [],
        "brokenImports": broken_imports or [],
        "circularDeps": [],
        "unreachableFromEntry": [],
        "missingMixinImpl": [],
        "coverage": 0.85,
        "starImports": [],
        "dynamicImports": [],
        "typeCheckingOnly": [],
        "unparseableFiles": [],
        "testOnlyConsumers": {},
    }
    (intel_dir / "gap_report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_dependency_graph(intel_dir: Path) -> None:
    data = {
        "schema_version": "1.0.0",
        "generated_at": "2026-02-20T10:00:00Z",
        "forward": {"src/app.py": ["src/service.py"]},
        "reverse": {"src/service.py": ["src/app.py"]},
        "orphan_files": [],
        "stats": {"total_files": 2, "total_edges": 1, "orphan_count": 0},
        "integrity": {"forward_reverse_match": True, "missing_targets": []},
    }
    (intel_dir / "dependency_graph.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_chain_validation(intel_dir: Path, dead_symbols: list[str] | None = None) -> None:
    data = {
        "schema_version": "1.0.0",
        "confirmed": 5,
        "unconfirmed": 1,
        "dead_symbols": dead_symbols or [],
        "lsp_available": True,
    }
    (intel_dir / "chain_validation.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_all(
    intel_dir: Path,
    include_chain: bool = False,
    dead_symbols: list[str] | None = None,
) -> None:
    _write_code_graph(intel_dir)
    _write_gap_report(intel_dir)
    _write_dependency_graph(intel_dir)
    if include_chain:
        _write_chain_validation(intel_dir, dead_symbols=dead_symbols)


def _make_adapter(project_root: Path) -> AuditAdapter:
    """Create an AuditAdapter pointed at the given project root."""
    return AuditAdapter(project_root=project_root)


# ---------------------------------------------------------------------------
# Tests: warden_get_audit_context
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestMCPGetAuditContext:

    @pytest.mark.asyncio
    async def test_no_intelligence_returns_error(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        result = await adapter._execute_tool_async("warden_get_audit_context", {})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_json_format_returns_valid_json(self, tmp_path):
        intel_dir = _make_intel_dir(tmp_path)
        _write_all(intel_dir)
        adapter = _make_adapter(tmp_path)

        result = await adapter._execute_tool_async("warden_get_audit_context", {"format": "json"})
        assert not result.is_error
        # Result content should be JSON-parseable
        content = result.content[0]
        assert content["type"] == "text"
        data = json.loads(content["text"])
        assert "code_graph" in data

    @pytest.mark.asyncio
    async def test_markdown_format_returns_text(self, tmp_path):
        intel_dir = _make_intel_dir(tmp_path)
        _write_all(intel_dir)
        adapter = _make_adapter(tmp_path)

        result = await adapter._execute_tool_async("warden_get_audit_context", {"format": "markdown"})
        assert not result.is_error
        text = result.content[0]["text"]
        assert "# Warden Audit Context" in text

    @pytest.mark.asyncio
    async def test_markdown_uses_project_root_for_template(self, tmp_path):
        """Regression: MCP adapter should use project_root not CWD for custom templates."""
        intel_dir = _make_intel_dir(tmp_path)
        _write_all(intel_dir)

        # Create a custom template at the project root
        tmpl_dir = tmp_path / ".warden" / "templates"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "audit_prompt.md").write_text("# Custom\n$stats\n", encoding="utf-8")

        adapter = _make_adapter(tmp_path)
        result = await adapter._execute_tool_async("warden_get_audit_context", {"format": "markdown"})
        assert not result.is_error
        text = result.content[0]["text"]
        assert "# Custom" in text

    @pytest.mark.asyncio
    async def test_full_flag_includes_details(self, tmp_path):
        intel_dir = _make_intel_dir(tmp_path)
        _write_all(intel_dir)
        adapter = _make_adapter(tmp_path)

        compact = await adapter._execute_tool_async("warden_get_audit_context", {"format": "json", "full": False})
        full = await adapter._execute_tool_async("warden_get_audit_context", {"format": "json", "full": True})

        compact_data = json.loads(compact.content[0]["text"])
        full_data = json.loads(full.content[0]["text"])

        # Full should have at least as much data
        assert len(json.dumps(full_data)) >= len(json.dumps(compact_data))

    @pytest.mark.asyncio
    async def test_chain_validation_included(self, tmp_path):
        intel_dir = _make_intel_dir(tmp_path)
        _write_all(intel_dir, include_chain=True, dead_symbols=["OldClass"])
        adapter = _make_adapter(tmp_path)

        result = await adapter._execute_tool_async("warden_get_audit_context", {"format": "json"})
        data = json.loads(result.content[0]["text"])
        assert "chain_validation" in data
        assert data["chain_validation"]["confirmed"] == 5


# ---------------------------------------------------------------------------
# Tests: warden_query_symbol
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestMCPQuerySymbol:

    @pytest.mark.asyncio
    async def test_missing_name_returns_error(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        result = await adapter._execute_tool_async("warden_query_symbol", {})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_no_code_graph_returns_error(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        result = await adapter._execute_tool_async("warden_query_symbol", {"name": "App"})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_found_symbol(self, tmp_path):
        intel_dir = _make_intel_dir(tmp_path)
        _write_code_graph(intel_dir)
        adapter = _make_adapter(tmp_path)

        result = await adapter._execute_tool_async("warden_query_symbol", {"name": "App"})
        assert not result.is_error
        data = json.loads(result.content[0]["text"])
        assert data["found"] is True
        assert len(data["matches"]) == 1
        assert data["matches"][0]["name"] == "App"

    @pytest.mark.asyncio
    async def test_not_found_symbol(self, tmp_path):
        intel_dir = _make_intel_dir(tmp_path)
        _write_code_graph(intel_dir)
        adapter = _make_adapter(tmp_path)

        result = await adapter._execute_tool_async("warden_query_symbol", {"name": "NonExistent"})
        assert not result.is_error
        data = json.loads(result.content[0]["text"])
        assert data["found"] is False

    @pytest.mark.asyncio
    async def test_symbol_with_lsp_confirmation(self, tmp_path):
        intel_dir = _make_intel_dir(tmp_path)
        _write_code_graph(intel_dir)
        _write_chain_validation(intel_dir, dead_symbols=["OldClass"])
        adapter = _make_adapter(tmp_path)

        # App is not in dead list → lsp_confirmed = True
        result = await adapter._execute_tool_async("warden_query_symbol", {"name": "App"})
        data = json.loads(result.content[0]["text"])
        assert data["lsp_confirmed"] is True

    @pytest.mark.asyncio
    async def test_symbol_in_dead_list(self, tmp_path):
        intel_dir = _make_intel_dir(tmp_path)
        _write_code_graph(intel_dir)
        _write_chain_validation(intel_dir, dead_symbols=["App"])
        adapter = _make_adapter(tmp_path)

        result = await adapter._execute_tool_async("warden_query_symbol", {"name": "App"})
        data = json.loads(result.content[0]["text"])
        assert data["lsp_confirmed"] is False

    @pytest.mark.asyncio
    async def test_edges_included_for_found_symbol(self, tmp_path):
        intel_dir = _make_intel_dir(tmp_path)
        _write_code_graph(intel_dir)
        adapter = _make_adapter(tmp_path)

        result = await adapter._execute_tool_async("warden_query_symbol", {"name": "App"})
        data = json.loads(result.content[0]["text"])
        assert "edges" in data
        assert len(data["edges"]) >= 1


# ---------------------------------------------------------------------------
# Tests: unknown tool
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestMCPUnknownTool:

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        result = await adapter._execute_tool_async("warden_nonexistent", {})
        assert result.is_error
