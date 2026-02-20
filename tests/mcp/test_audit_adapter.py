"""
Tests for the AuditAdapter MCP adapter.

Covers:
- SUPPORTED_TOOLS declaration
- get_tool_definitions() structure
- warden_get_audit_context: no data, JSON format, markdown format
- warden_query_symbol: found, not found, error handling
- warden_query_symbol: query_type modes (who_uses, who_inherits, etc.)
- warden_graph_search: fuzzy/prefix search, kind filter
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
                "fqn": "warden.foo::SecurityFrame",
                "name": "SecurityFrame",
                "kind": "class",
                "file_path": "src/warden/validation/frames/security/frame.py",
                "line": 10,
            },
            "warden.foo::validate": {
                "fqn": "warden.foo::validate",
                "name": "validate",
                "kind": "function",
                "file_path": "src/warden/validation/frames/security/frame.py",
                "line": 25,
            },
            "warden.bar::helper": {
                "fqn": "warden.bar::helper",
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


def _make_rich_code_graph(project_root: Path) -> Path:
    """Create intelligence dir with a richer graph for relationship queries.

    Graph topology:
      BaseFrame (class)
        ^--- SecurityFrame (class, INHERITS BaseFrame)
        ^--- ResilienceFrame (class, INHERITS BaseFrame)
      TaintAware (mixin)
        ^--- SecurityFrame (IMPLEMENTS TaintAware)
      SecurityFrame --CALLS--> validate_input (function)
      validate_input --CALLS--> helper (function)
      TestSecurityFrame (class, is_test=True) --CALLS--> SecurityFrame

    Total: 7 nodes, 6 edges
    """
    intel_dir = project_root / ".warden" / "intelligence"
    intel_dir.mkdir(parents=True, exist_ok=True)

    code_graph = {
        "schema_version": "1.0.0",
        "nodes": {
            "app.base::BaseFrame": {
                "fqn": "app.base::BaseFrame",
                "name": "BaseFrame",
                "kind": "class",
                "file_path": "src/app/base.py",
                "line": 1,
            },
            "app.security::SecurityFrame": {
                "fqn": "app.security::SecurityFrame",
                "name": "SecurityFrame",
                "kind": "class",
                "file_path": "src/app/security.py",
                "line": 5,
            },
            "app.resilience::ResilienceFrame": {
                "fqn": "app.resilience::ResilienceFrame",
                "name": "ResilienceFrame",
                "kind": "class",
                "file_path": "src/app/resilience.py",
                "line": 1,
            },
            "app.mixins::TaintAware": {
                "fqn": "app.mixins::TaintAware",
                "name": "TaintAware",
                "kind": "mixin",
                "file_path": "src/app/mixins.py",
                "line": 1,
            },
            "app.security::validate_input": {
                "fqn": "app.security::validate_input",
                "name": "validate_input",
                "kind": "function",
                "file_path": "src/app/security.py",
                "line": 20,
            },
            "app.utils::helper": {
                "fqn": "app.utils::helper",
                "name": "helper",
                "kind": "function",
                "file_path": "src/app/utils.py",
                "line": 1,
            },
            "tests.test_security::TestSecurityFrame": {
                "fqn": "tests.test_security::TestSecurityFrame",
                "name": "TestSecurityFrame",
                "kind": "class",
                "file_path": "tests/test_security.py",
                "line": 1,
                "is_test": True,
            },
        },
        "edges": [
            {
                "source": "app.security::SecurityFrame",
                "target": "app.base::BaseFrame",
                "relation": "inherits",
            },
            {
                "source": "app.resilience::ResilienceFrame",
                "target": "app.base::BaseFrame",
                "relation": "inherits",
            },
            {
                "source": "app.security::SecurityFrame",
                "target": "app.mixins::TaintAware",
                "relation": "implements",
            },
            {
                "source": "app.security::SecurityFrame",
                "target": "app.security::validate_input",
                "relation": "calls",
            },
            {
                "source": "app.security::validate_input",
                "target": "app.utils::helper",
                "relation": "calls",
            },
            {
                "source": "tests.test_security::TestSecurityFrame",
                "target": "app.security::SecurityFrame",
                "relation": "calls",
            },
        ],
    }

    (intel_dir / "code_graph.json").write_text(
        json.dumps(code_graph), encoding="utf-8"
    )

    # Minimal gap/dep data so audit_context doesn't fail
    (intel_dir / "gap_report.json").write_text(
        json.dumps({"coverage": 0.9}), encoding="utf-8"
    )
    (intel_dir / "dependency_graph.json").write_text(
        json.dumps({"stats": {"total_files": 5}}), encoding="utf-8"
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


@pytest.fixture
def rich_adapter(tmp_path: Path) -> AuditAdapter:
    """Adapter instance with rich code graph for relationship queries."""
    _make_rich_code_graph(tmp_path)
    return AuditAdapter(project_root=tmp_path)


# ---------------------------------------------------------------------------
# 1. SUPPORTED_TOOLS & definitions
# ---------------------------------------------------------------------------

class TestSupportedToolsAndDefinitions:
    def test_supported_tools_has_exactly_three_entries(self, adapter: AuditAdapter) -> None:
        assert len(AuditAdapter.SUPPORTED_TOOLS) == 3

    def test_supports_method_returns_true_for_known_tools(self, adapter: AuditAdapter) -> None:
        assert adapter.supports("warden_get_audit_context") is True
        assert adapter.supports("warden_query_symbol") is True
        assert adapter.supports("warden_graph_search") is True

    def test_supports_method_returns_false_for_unknown_tool(self, adapter: AuditAdapter) -> None:
        assert adapter.supports("warden_nonexistent") is False

    def test_returns_three_definitions(self, adapter: AuditAdapter) -> None:
        defs = adapter.get_tool_definitions()
        assert len(defs) == 3

    def test_audit_context_schema_has_format_and_full(self, adapter: AuditAdapter) -> None:
        defs = {d.name: d for d in adapter.get_tool_definitions()}
        schema = defs["warden_get_audit_context"].input_schema
        assert "format" in schema["properties"]
        assert "full" in schema["properties"]

    def test_query_symbol_schema_has_name_and_query_type(self, adapter: AuditAdapter) -> None:
        defs = {d.name: d for d in adapter.get_tool_definitions()}
        schema = defs["warden_query_symbol"].input_schema
        assert "name" in schema.get("required", [])
        assert "query_type" in schema["properties"]

    def test_graph_search_schema_requires_query(self, adapter: AuditAdapter) -> None:
        defs = {d.name: d for d in adapter.get_tool_definitions()}
        schema = defs["warden_graph_search"].input_schema
        assert "query" in schema.get("required", [])

    def test_definitions_do_not_require_bridge(self, adapter: AuditAdapter) -> None:
        for tool_def in adapter.get_tool_definitions():
            assert tool_def.requires_bridge is False

    def test_definitions_have_non_empty_descriptions(self, adapter: AuditAdapter) -> None:
        for tool_def in adapter.get_tool_definitions():
            assert tool_def.description.strip() != ""


# ---------------------------------------------------------------------------
# 2. warden_get_audit_context — no data
# ---------------------------------------------------------------------------

class TestGetAuditContextNoData:
    @pytest.mark.asyncio
    async def test_returns_error_when_no_intelligence_dir(self, adapter: AuditAdapter) -> None:
        result = await adapter._execute_tool_async("warden_get_audit_context", {})
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_returns_error_when_intelligence_dir_empty(self, tmp_path: Path) -> None:
        (tmp_path / ".warden" / "intelligence").mkdir(parents=True)
        adapter = AuditAdapter(project_root=tmp_path)
        result = await adapter._execute_tool_async("warden_get_audit_context", {})
        assert result.is_error is True


# ---------------------------------------------------------------------------
# 3. warden_get_audit_context — JSON format
# ---------------------------------------------------------------------------

class TestGetAuditContextJson:
    @pytest.mark.asyncio
    async def test_json_result_contains_all_keys(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "json"}
        )
        assert result.is_error is False
        parsed = json.loads(result.content[0]["text"])
        assert "code_graph" in parsed
        assert "gap_report" in parsed
        assert "dependency_graph" in parsed

    @pytest.mark.asyncio
    async def test_json_default_format_omits_full_node_list(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "json", "full": False}
        )
        parsed = json.loads(result.content[0]["text"])
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
    async def test_json_default_format_when_not_specified(
        self, adapter_with_data: AuditAdapter
    ) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {}
        )
        assert result.is_error is False
        parsed = json.loads(result.content[0]["text"])
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# 4. warden_get_audit_context — markdown format
# ---------------------------------------------------------------------------

class TestGetAuditContextMarkdown:
    @pytest.mark.asyncio
    async def test_markdown_has_heading_and_sections(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_get_audit_context", {"format": "markdown"}
        )
        assert result.is_error is False
        text = result.content[0]["text"]
        assert text.startswith("# Warden Audit Context")
        assert "Code Graph Overview" in text
        assert "Gap Analysis" in text
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
        assert "3" in text
        assert "2" in text


# ---------------------------------------------------------------------------
# 5. warden_query_symbol — search (default query_type)
# ---------------------------------------------------------------------------

class TestQuerySymbolSearch:
    @pytest.mark.asyncio
    async def test_found_with_metadata_and_edges(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": "SecurityFrame"}
        )
        assert result.is_error is False
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True
        match = parsed["matches"][0]
        assert "fqn" in match and "SecurityFrame" in match["fqn"]
        assert match.get("kind") == "class"
        assert "file_path" in match
        assert len(parsed["edges"]) >= 1

    @pytest.mark.asyncio
    async def test_not_found_for_nonexistent_symbol(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": "DoesNotExist"}
        )
        assert result.is_error is False
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is False

    @pytest.mark.asyncio
    async def test_fqn_exact_match_via_double_colon(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol", {"name": "app.security::SecurityFrame"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True
        assert parsed["matches"][0]["fqn"] == "app.security::SecurityFrame"

    @pytest.mark.asyncio
    async def test_error_when_code_graph_missing(self, tmp_path: Path) -> None:
        (tmp_path / ".warden" / "intelligence").mkdir(parents=True)
        adapter = AuditAdapter(project_root=tmp_path)
        result = await adapter._execute_tool_async(
            "warden_query_symbol", {"name": "SecurityFrame"}
        )
        assert result.is_error is True


# ---------------------------------------------------------------------------
# 6. warden_query_symbol — error handling
# ---------------------------------------------------------------------------

class TestQuerySymbolErrors:
    @pytest.mark.asyncio
    async def test_returns_error_when_name_is_empty(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": ""}
        )
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_unknown_tool_name_returns_error(self, adapter: AuditAdapter) -> None:
        result = await adapter._execute_tool_async("warden_nonexistent_tool", {})
        assert result.is_error is True
        assert "Unknown tool" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_invalid_query_type_returns_error(self, adapter_with_data: AuditAdapter) -> None:
        result = await adapter_with_data._execute_tool_async(
            "warden_query_symbol", {"name": "Foo", "query_type": "invalid_mode"}
        )
        assert result.is_error is True


# ---------------------------------------------------------------------------
# 7. warden_query_symbol — who_uses
# ---------------------------------------------------------------------------

class TestQuerySymbolWhoUses:
    @pytest.mark.asyncio
    async def test_who_uses_include_tests(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol",
            {"name": "SecurityFrame", "query_type": "who_uses", "include_tests": True},
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["count"] >= 1
        sources = [r["source"] for r in parsed["results"]]
        assert any("TestSecurityFrame" in s for s in sources)

    @pytest.mark.asyncio
    async def test_who_uses_not_found_returns_empty(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol",
            {"name": "NonExistentSymbol", "query_type": "who_uses"},
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is False
        assert parsed["count"] == 0

    @pytest.mark.asyncio
    async def test_who_uses_base_frame_returns_inheritors(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol",
            {"name": "BaseFrame", "query_type": "who_uses"},
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["count"] >= 2


# ---------------------------------------------------------------------------
# 8. warden_query_symbol — who_inherits
# ---------------------------------------------------------------------------

class TestQuerySymbolWhoInherits:
    @pytest.mark.asyncio
    async def test_who_inherits_finds_children(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol",
            {"name": "BaseFrame", "query_type": "who_inherits"},
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True
        assert parsed["count"] == 2
        names = [r["name"] for r in parsed["results"]]
        assert "SecurityFrame" in names
        assert "ResilienceFrame" in names

    @pytest.mark.asyncio
    async def test_who_inherits_leaf_class_returns_empty(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol",
            {"name": "SecurityFrame", "query_type": "who_inherits"},
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["count"] == 0


# ---------------------------------------------------------------------------
# 9. warden_query_symbol — who_implements
# ---------------------------------------------------------------------------

class TestQuerySymbolWhoImplements:
    @pytest.mark.asyncio
    async def test_who_implements_finds_implementor(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol",
            {"name": "TaintAware", "query_type": "who_implements"},
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True
        assert parsed["count"] == 1
        assert parsed["results"][0]["name"] == "SecurityFrame"

    @pytest.mark.asyncio
    async def test_who_implements_non_mixin_returns_empty(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol",
            {"name": "helper", "query_type": "who_implements"},
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["count"] == 0


# ---------------------------------------------------------------------------
# 10. warden_query_symbol — callers / callees
# ---------------------------------------------------------------------------

class TestQuerySymbolCallersCallees:
    @pytest.mark.asyncio
    async def test_callers_filters_to_calls_only(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol",
            {"name": "validate_input", "query_type": "callers"},
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True
        assert parsed["count"] >= 1
        assert all(r["relation"] == "calls" for r in parsed["results"])

    @pytest.mark.asyncio
    async def test_callees_returns_outgoing_calls(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol",
            {"name": "SecurityFrame", "query_type": "callees"},
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True
        assert parsed["count"] >= 1
        targets = [r["target"] for r in parsed["results"]]
        assert any("validate_input" in t for t in targets)


# ---------------------------------------------------------------------------
# 11. warden_query_symbol — dependency_chain
# ---------------------------------------------------------------------------

class TestQuerySymbolDependencyChain:
    @pytest.mark.asyncio
    async def test_dependency_chain_returns_chains(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol",
            {"name": "SecurityFrame", "query_type": "dependency_chain"},
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True
        assert parsed["count"] >= 1

    @pytest.mark.asyncio
    async def test_dependency_chain_max_depth_capped(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol",
            {"name": "SecurityFrame", "query_type": "dependency_chain", "max_depth": 1},
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["max_depth"] == 1
        for chain in parsed["results"]:
            assert len(chain) <= 1

    @pytest.mark.asyncio
    async def test_dependency_chain_max_depth_clamped_to_10(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_query_symbol",
            {"name": "SecurityFrame", "query_type": "dependency_chain", "max_depth": 999},
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["max_depth"] == 10


# ---------------------------------------------------------------------------
# 12. warden_graph_search
# ---------------------------------------------------------------------------

class TestGraphSearch:
    @pytest.mark.asyncio
    async def test_prefix_match(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_graph_search", {"query": "Security"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True
        names = [r["name"] for r in parsed["results"]]
        assert "SecurityFrame" in names

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_graph_search", {"query": "securityframe"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True
        assert any(r["name"] == "SecurityFrame" for r in parsed["results"])

    @pytest.mark.asyncio
    async def test_substring_match(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_graph_search", {"query": "Frame"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True
        assert parsed["count"] >= 3

    @pytest.mark.asyncio
    async def test_kind_filter(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_graph_search", {"query": "validate", "kind": "function"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True
        assert all(r["kind"] == "function" for r in parsed["results"])

    @pytest.mark.asyncio
    async def test_kind_filter_excludes_non_matching(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_graph_search", {"query": "SecurityFrame", "kind": "function"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["count"] == 0

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_graph_search", {"query": "ZzzNonexistent"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is False
        assert parsed["count"] == 0

    @pytest.mark.asyncio
    async def test_missing_query_returns_error(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_graph_search", {"query": ""}
        )
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_limit_caps_results(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_graph_search", {"query": "e", "limit": 2}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["count"] <= 2

    @pytest.mark.asyncio
    async def test_exact_match_ranked_first(self, rich_adapter: AuditAdapter) -> None:
        result = await rich_adapter._execute_tool_async(
            "warden_graph_search", {"query": "helper"}
        )
        parsed = json.loads(result.content[0]["text"])
        assert parsed["found"] is True
        assert parsed["results"][0]["name"] == "helper"

    @pytest.mark.asyncio
    async def test_missing_code_graph_returns_error(self, tmp_path: Path) -> None:
        adapter = AuditAdapter(project_root=tmp_path)
        result = await adapter._execute_tool_async(
            "warden_graph_search", {"query": "Foo"}
        )
        assert result.is_error is True
