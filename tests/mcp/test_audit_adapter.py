"""
Tests for the AuditAdapter MCP adapter.

Covers:
- SUPPORTED_TOOLS declaration
- get_tool_definitions() structure
- warden_get_audit_context: no data, JSON format, markdown format
- warden_query_symbol: found, not found, missing name parameter
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from warden.mcp.infrastructure.adapters.audit_adapter import AuditAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intelligence_dir(project_root: Path) -> Path:
    """Create .warden/intelligence/ with minimal mock data files."""
    intel_dir = project_root / ".warden" / "intelligence"
    intel_dir.mkdir(parents=True)

    code_graph = {
        "schema_version": "1.0.0",
        "generated_at": "2026-02-20T00:00:00Z",
        "stats": {
            "total_nodes": 3,
            "total_edges": 2,
            "classes": 1,
            "functions": 2,
            "test_nodes": 0,
        },
        "nodes": {
            "warden.foo::SecurityFrame": {
                "name": "SecurityFrame",
                "kind": "class",
                "file_path": "src/warden/validation/frames/security/frame.py",
                "line": 10,
            },
            "warden.foo::validate": {
                "name": "validate",
                "kind": "function",
                "file_path": "src/warden/validation/frames/security/frame.py",
                "line": 25,
            },
            "warden.bar::helper": {
                "name": "helper",
                "kind": "function",
                "file_path": "src/warden/utils.py",
                "line": 5,
            },
        },
        "edges": [
            {
                "source": "warden.foo::SecurityFrame",
                "target": "warden.foo::validate",
                "relation": "calls",
            },
            {
                "source": "warden.foo::validate",
                "target": "warden.bar::helper",
                "relation": "calls",
            },
        ],
    }

    gap_report = {
        "coverage": 0.85,
        "orphan_files": ["src/warden/unused.py"],
        "orphan_symbols": [],
        "broken_imports": ["src/warden/missing_module.py"],
        "circular_deps": [],
        "unreachable_from_entry": [],
        "missing_mixin_impl": [],
        "star_imports": [],
        "dynamic_imports": [],
        "unparseable_files": [],
    }

    dep_graph = {
        "stats": {
            "total_files": 10,
            "total_edges": 15,
            "orphan_count": 1,
        },
        "integrity": {
            "forward_reverse_match": True,
        },
    }

    (intel_dir / "code_graph.json").write_text(
        json.dumps(code_graph), encoding="utf-8"
    )
    (intel_dir / "gap_report.json").write_text(
        json.dumps(gap_report), encoding="utf-8"
    )
    (intel_dir / "dependency_graph.json").write_text(
        json.dumps(dep_graph), encoding="utf-8"
    )

    return intel_dir


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def adapter(tmp_path: Path) -> AuditAdapter:
    """Adapter instance with no intelligence data."""
    return AuditAdapter(project_root=tmp_path)


@pytest.fixture
def adapter_with_data(tmp_path: Path) -> AuditAdapter:
    """Adapter instance with a fully populated intelligence directory."""
    _make_intelligence_dir(tmp_path)
    return AuditAdapter(project_root=tmp_path)


# ---------------------------------------------------------------------------
# 1. SUPPORTED_TOOLS
# ---------------------------------------------------------------------------

class TestSupportedTools:
    def test_supported_tools_contains_get_audit_context(self, adapter: AuditAdapter) -> None:
        assert "warden_get_audit_context" in AuditAdapter.SUPPORTED_TOOLS

    def test_supported_tools_contains_query_symbol(self, adapter: AuditAdapter) -> None:
        assert "warden_query_symbol" in AuditAdapter.SUPPORTED_TOOLS

    def test_supported_tools_has_exactly_two_entries(self, adapter: AuditAdapter) -> None:
        assert len(AuditAdapter.SUPPORTED_TOOLS) == 2

    def test_supports_method_returns_true_for_known_tool(self, adapter: AuditAdapter) -> None:
        assert adapter.supports("warden_get_audit_context") is True
        assert adapter.supports("warden_query_symbol") is True

    def test_supports_method_returns_false_for_unknown_tool(self, adapter: AuditAdapter) -> None:
        assert adapter.supports("warden_nonexistent") is False


# ---------------------------------------------------------------------------
# 2. get_tool_definitions
# ---------------------------------------------------------------------------

class TestGetToolDefinitions:
    def test_returns_two_definitions(self, adapter: AuditAdapter) -> None:
        defs = adapter.get_tool_definitions()
        assert len(defs) == 2

    def test_first_definition_is_get_audit_context(self, adapter: AuditAdapter) -> None:
        defs = adapter.get_tool_definitions()
        names = [d.name for d in defs]
        assert "warden_get_audit_context" in names

    def test_second_definition_is_query_symbol(self, adapter: AuditAdapter) -> None:
        defs = adapter.get_tool_definitions()
        names = [d.name for d in defs]
        assert "warden_query_symbol" in names

    def test_get_audit_context_schema_has_format_property(self, adapter: AuditAdapter) -> None:
        defs = {d.name: d for d in adapter.get_tool_definitions()}
        schema = defs["warden_get_audit_context"].input_schema
        assert "format" in schema["properties"]

    def test_get_audit_context_schema_has_full_property(self, adapter: AuditAdapter) -> None:
        defs = {d.name: d for d in adapter.get_tool_definitions()}
        schema = defs["warden_get_audit_context"].input_schema
        assert "full" in schema["properties"]

    def test_query_symbol_schema_requires_name(self, adapter: AuditAdapter) -> None:
        defs = {d.name: d for d in adapter.get_tool_definitions()}
        schema = defs["warden_query_symbol"].input_schema
        assert "name" in schema.get("required", [])

    def test_definitions_do_not_require_bridge(self, adapter: AuditAdapter) -> None:
        for tool_def in adapter.get_tool_definitions():
            assert tool_def.requires_bridge is False

    def test_definitions_have_non_empty_descriptions(self, adapter: AuditAdapter) -> None:
        for tool_def in adapter.get_tool_definitions():
            assert tool_def.description.strip() != ""


# ---------------------------------------------------------------------------
# 3. warden_get_audit_context — no data
# ---------------------------------------------------------------------------

class TestGetAuditContextNoData:
    @pytest.mark.asyncio
    async def test_returns_error_when_no_intelligence_dir(self, adapter: AuditAdapter) -> None:
        result = await adapter._execute_tool_async(
            "warden_get_audit_context", {}
        )
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_error_message_mentions_refresh(self, adapter: AuditAdapter) -> None:
        result = await adapter._execute_tool_async(
            "warden_get_audit_context", {}
        )
        assert result.is_error is True
        text = result.content[0]["text"]
        assert "refresh" in text.lower() or "No intelligence data" in text

    @pytest.mark.asyncio
    async def test_returns_error_when_intelligence_dir_empty(self, tmp_path: Path) -> None:
        # Create the directory but leave it empty (no JSON files)
        empty_dir = tmp_path / ".warden" / "intelligence"
        empty_dir.mkdir(parents=True)
        adapter = AuditAdapter(project_root=tmp_path)

        result = await adapter._execute_tool_async(
            "warden_get_audit_context", {}
        )
        assert result.is_error is True


# ---------------------------------------------------------------------------
# 4. warden_get_audit_context — JSON format
# ---------------------------------------------------------------------------

class TestGetAuditContextJson:
    @pytest.mark.asyncio
    async def test_returns_non_error_result(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "json"}
        )
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_result_content_is_valid_json(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "json"}
        )
        text = result.content[0]["text"]
        parsed = json.loads(text)
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_json_result_contains_code_graph_key(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "json"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert "code_graph" in parsed

    @pytest.mark.asyncio
    async def test_json_result_contains_gap_report_key(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "json"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert "gap_report" in parsed

    @pytest.mark.asyncio
    async def test_json_result_contains_dependency_graph_key(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "json"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert "dependency_graph" in parsed

    @pytest.mark.asyncio
    async def test_json_default_format_omits_full_node_list(self, adapter_with_data: AuditAdapter) -> None:
        # In default (non-full) mode the code_graph entry should be a summary, not the raw graph.
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "json", "full": False}
        )
        parsed = json.loads(result.content[0]["text"])
        # Summary mode: code_graph should NOT include all node details
        assert "nodes" not in parsed["code_graph"]

    @pytest.mark.asyncio
    async def test_json_full_mode_includes_nodes(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "json", "full": True}
        )
        parsed = json.loads(result.content[0]["text"])
        assert "nodes" in parsed["code_graph"]

    @pytest.mark.asyncio
    async def test_json_gap_report_coverage_reflects_mock_data(
        self, adapter_with_data: AuditAdapter
    ) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "json"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["gap_report"]["coverage"] == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_json_default_format_used_when_format_not_specified(
        self, adapter_with_data: AuditAdapter
    ) -> None:
        # No "format" argument — should default to JSON.
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {}
        )
        assert result.is_error is False
        text = result.content[0]["text"]
        parsed = json.loads(text)
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# 5. warden_get_audit_context — markdown format
# ---------------------------------------------------------------------------

class TestGetAuditContextMarkdown:
    @pytest.mark.asyncio
    async def test_returns_non_error_result(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "markdown"}
        )
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_result_starts_with_markdown_heading(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "markdown"}
        )
        text = result.content[0]["text"]
        assert text.startswith("# Warden Audit Context")

    @pytest.mark.asyncio
    async def test_markdown_contains_code_graph_section(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "markdown"}
        )
        text = result.content[0]["text"]
        assert "Code Graph Overview" in text

    @pytest.mark.asyncio
    async def test_markdown_contains_gap_analysis_section(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "markdown"}
        )
        text = result.content[0]["text"]
        assert "Gap Analysis" in text

    @pytest.mark.asyncio
    async def test_markdown_contains_dependency_section(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "markdown"}
        )
        text = result.content[0]["text"]
        assert "Dependency Graph" in text

    @pytest.mark.asyncio
    async def test_markdown_content_type_is_text(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "markdown"}
        )
        assert result.content[0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_markdown_reflects_mock_stats(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "markdown"}
        )
        text = result.content[0]["text"]
        # The mock data has 3 nodes and 2 edges
        assert "3" in text
        assert "2" in text


# ---------------------------------------------------------------------------
# 6. warden_query_symbol — found
# ---------------------------------------------------------------------------

class TestQuerySymbolFound:
    @pytest.mark.asyncio
    async def test_found_is_true_for_existing_symbol(
        self, adapter_with_data: AuditAdapter
    ) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": "SecurityFrame"}
        )
        assert result.is_error is False
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True

    @pytest.mark.asyncio
    async def test_matches_list_is_non_empty_for_existing_symbol(
        self, adapter_with_data: AuditAdapter
    ) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": "SecurityFrame"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert len(parsed["matches"]) >= 1

    @pytest.mark.asyncio
    async def test_match_includes_fqn(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": "SecurityFrame"}
        )
        parsed = json.loads(result.content[0]["text"])
        match = parsed["matches"][0]
        assert "fqn" in match
        assert "SecurityFrame" in match["fqn"]

    @pytest.mark.asyncio
    async def test_match_includes_node_metadata(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": "SecurityFrame"}
        )
        parsed = json.loads(result.content[0]["text"])
        match = parsed["matches"][0]
        assert match.get("kind") == "class"
        assert "file_path" in match
        assert "line" in match

    @pytest.mark.asyncio
    async def test_related_edges_returned_for_matched_symbol(
        self, adapter_with_data: AuditAdapter
    ) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": "SecurityFrame"}
        )
        parsed = json.loads(result.content[0]["text"])
        # The mock graph has 1 edge sourcing from SecurityFrame's FQN
        assert "edges" in parsed
        assert len(parsed["edges"]) >= 1

    @pytest.mark.asyncio
    async def test_symbol_name_echoed_in_result(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": "SecurityFrame"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["symbol"] == "SecurityFrame"


# ---------------------------------------------------------------------------
# 7. warden_query_symbol — not found
# ---------------------------------------------------------------------------

class TestQuerySymbolNotFound:
    @pytest.mark.asyncio
    async def test_found_is_false_for_nonexistent_symbol(
        self, adapter_with_data: AuditAdapter
    ) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": "DoesNotExist"}
        )
        assert result.is_error is False
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is False

    @pytest.mark.asyncio
    async def test_matches_list_is_empty_for_nonexistent_symbol(
        self, adapter_with_data: AuditAdapter
    ) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": "DoesNotExist"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["matches"] == []

    @pytest.mark.asyncio
    async def test_symbol_name_echoed_even_when_not_found(
        self, adapter_with_data: AuditAdapter
    ) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": "DoesNotExist"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["symbol"] == "DoesNotExist"

    @pytest.mark.asyncio
    async def test_not_found_when_code_graph_missing(self, tmp_path: Path) -> None:
        # Intelligence dir exists but has no code_graph.json
        (tmp_path / ".warden" / "intelligence").mkdir(parents=True)
        adapter = AuditAdapter(project_root=tmp_path)

        result = await adapter._execute_tool_async(
            "warden_query_symbol", {"name": "SecurityFrame"}
        )
        assert result.is_error is True
        assert "warden refresh" in result.content[0]["text"] or "not found" in result.content[0]["text"].lower()


# ---------------------------------------------------------------------------
# 8. warden_query_symbol — missing name parameter
# ---------------------------------------------------------------------------

class TestQuerySymbolMissingName:
    @pytest.mark.asyncio
    async def test_returns_error_when_name_is_empty_string(
        self, adapter_with_data: AuditAdapter
    ) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": ""}
        )
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_error_message_mentions_name_parameter(
        self, adapter_with_data: AuditAdapter
    ) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": ""}
        )
        text = result.content[0]["text"]
        assert "name" in text.lower()

    @pytest.mark.asyncio
    async def test_returns_error_when_name_key_absent(
        self, adapter_with_data: AuditAdapter
    ) -> None:
        # Omitting the "name" key entirely — arguments.get("name", "") → ""
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {}
        )
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_unknown_tool_name_returns_error(self, adapter: AuditAdapter) -> None:
        result = await adapter._execute_tool_async(
            "warden_nonexistent_tool", {}
        )
        assert result.is_error is True
        assert "Unknown tool" in result.content[0]["text"]
