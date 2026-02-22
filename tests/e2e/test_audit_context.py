"""E2E tests for `warden audit-context` CLI command.

Coverage:
- No intelligence directory → exit code 1 with clear message
- --format yaml with mock data → valid YAML with expected keys
- --format json with mock data → valid JSON with expected structure
- --format markdown with mock data → markdown with required headers
- --full flag → extended detail sections included in output
- --check with no critical gaps → exit code 0
- --check with broken imports → exit code 1
- Empty intelligence directory → exit code 1
- --help → exit code 0 with flag documentation
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from warden.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intelligence_dir(base: Path) -> Path:
    """Create .warden/intelligence/ under base and return its path."""
    intel_dir = base / ".warden" / "intelligence"
    intel_dir.mkdir(parents=True, exist_ok=True)
    return intel_dir


def _write_mock_code_graph(intel_dir: Path) -> None:
    """Write a minimal code_graph.json with 3 nodes and 2 edges."""
    code_graph = {
        "schema_version": "1.0.0",
        "generated_at": "2026-02-20T10:00:00Z",
        "nodes": {
            "warden::pipeline::Orchestrator": {
                "id": "warden::pipeline::Orchestrator",
                "name": "Orchestrator",
                "kind": "class",
                "file_path": "src/warden/pipeline/orchestrator.py",
                "line": 42,
            },
            "warden::pipeline::run_async": {
                "id": "warden::pipeline::run_async",
                "name": "run_async",
                "kind": "function",
                "file_path": "src/warden/pipeline/orchestrator.py",
                "line": 100,
            },
            "warden::validation::frame::ValidationFrame": {
                "id": "warden::validation::frame::ValidationFrame",
                "name": "ValidationFrame",
                "kind": "class",
                "file_path": "src/warden/validation/domain/frame.py",
                "line": 10,
            },
        },
        "edges": [
            {
                "source": "warden::pipeline::Orchestrator",
                "target": "warden::validation::frame::ValidationFrame",
                "relation": "inherits",
            },
            {
                "source": "warden::pipeline::run_async",
                "target": "warden::pipeline::Orchestrator",
                "relation": "calls",
            },
        ],
        "stats": {
            "total_nodes": 3,
            "total_edges": 2,
            "classes": 2,
            "functions": 1,
            "test_nodes": 0,
        },
    }
    (intel_dir / "code_graph.json").write_text(
        json.dumps(code_graph, indent=2), encoding="utf-8"
    )


def _write_mock_gap_report(intel_dir: Path, broken_imports: list[str] | None = None) -> None:
    """Write a minimal gap_report.json."""
    gap_report = {
        "coverage": 0.87,
        "orphan_files": ["src/warden/legacy/old_module.py"],
        "orphan_symbols": ["warden::legacy::unused_func"],
        "broken_imports": broken_imports or [],
        "circular_deps": [],
        "unreachable_from_entry": [],
        "missing_mixin_impl": [],
        "star_imports": ["src/warden/utils/__init__.py"],
        "dynamic_imports": [],
        "unparseable_files": [],
        "test_only_consumers": [],
    }
    (intel_dir / "gap_report.json").write_text(
        json.dumps(gap_report, indent=2), encoding="utf-8"
    )


def _write_mock_dependency_graph(intel_dir: Path) -> None:
    """Write a minimal dependency_graph.json."""
    dep_graph = {
        "stats": {
            "total_files": 42,
            "total_edges": 118,
            "orphan_count": 3,
        },
        "integrity": {
            "forward_reverse_match": True,
        },
    }
    (intel_dir / "dependency_graph.json").write_text(
        json.dumps(dep_graph, indent=2), encoding="utf-8"
    )


def _write_mock_chain_validation(
    intel_dir: Path,
    dead_symbols: list[str] | None = None,
    lsp_available: bool = True,
) -> None:
    """Write a minimal chain_validation.json."""
    chain_val = {
        "confirmed": 15,
        "unconfirmed": 3,
        "dead_symbols": dead_symbols or [],
        "lsp_available": lsp_available,
        "generated_at": "2026-02-20T12:00:00Z",
    }
    (intel_dir / "chain_validation.json").write_text(
        json.dumps(chain_val, indent=2), encoding="utf-8"
    )


def _write_all_mock_data(
    intel_dir: Path,
    broken_imports: list[str] | None = None,
    include_chain_validation: bool = False,
    dead_symbols: list[str] | None = None,
) -> None:
    """Populate intel_dir with all mock data files."""
    _write_mock_code_graph(intel_dir)
    _write_mock_gap_report(intel_dir, broken_imports=broken_imports)
    _write_mock_dependency_graph(intel_dir)
    if include_chain_validation:
        _write_mock_chain_validation(intel_dir, dead_symbols=dead_symbols)


# ---------------------------------------------------------------------------
# Tests: missing / empty intelligence directory
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAuditContextMissingData:

    def test_no_intelligence_dir_exits_with_code_1(self, runner, tmp_path, monkeypatch):
        """Command exits 1 when .warden/intelligence/ does not exist."""
        # Arrange: a project directory with no intelligence directory at all
        monkeypatch.chdir(tmp_path)

        # Act
        result = runner.invoke(app, ["audit-context"])

        # Assert
        assert result.exit_code == 1
        stdout = result.stdout.lower()
        assert "no intelligence" in stdout or "intelligence" in stdout

    def test_no_intelligence_dir_shows_helpful_message(self, runner, tmp_path, monkeypatch):
        """Exit message mentions how to generate intelligence data."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context"])

        assert result.exit_code == 1
        # Should guide user to warden refresh or warden init
        stdout = result.stdout.lower()
        assert "refresh" in stdout or "init" in stdout

    def test_empty_intelligence_dir_exits_with_code_1(self, runner, tmp_path, monkeypatch):
        """Command exits 1 when .warden/intelligence/ exists but has no JSON files."""
        # Arrange: create the directory but leave it empty
        (tmp_path / ".warden" / "intelligence").mkdir(parents=True)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context"])

        assert result.exit_code == 1
        stdout = result.stdout.lower()
        assert "intelligence" in stdout or "no data" in stdout

    def test_no_intelligence_dir_check_flag_also_exits_1(self, runner, tmp_path, monkeypatch):
        """--check also exits 1 when no intelligence directory is present."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--check"])

        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Tests: --format yaml (default)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAuditContextYaml:

    def test_yaml_format_exits_0_with_data(self, runner, tmp_path, monkeypatch):
        """YAML output with valid mock data exits with code 0."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0

    def test_yaml_is_parseable(self, runner, tmp_path, monkeypatch):
        """YAML output parses without errors."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert isinstance(parsed, dict)

    def test_yaml_contains_graph_section(self, runner, tmp_path, monkeypatch):
        """YAML output includes a 'graph' section with node/edge counts."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert "graph" in parsed
        assert parsed["graph"]["nodes"] == 3
        assert parsed["graph"]["edges"] == 2

    def test_yaml_contains_gaps_section(self, runner, tmp_path, monkeypatch):
        """YAML output includes a 'gaps' section with coverage and counts."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert "gaps" in parsed
        assert "coverage" in parsed["gaps"]
        assert parsed["gaps"]["coverage"] == pytest.approx(0.87, abs=0.01)

    def test_yaml_contains_dependencies_section(self, runner, tmp_path, monkeypatch):
        """YAML output includes a 'dependencies' section with file count."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert "dependencies" in parsed
        assert parsed["dependencies"]["total_files"] == 42

    def test_default_format_is_yaml(self, runner, tmp_path, monkeypatch):
        """Invoking without --format defaults to YAML output."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context"])

        assert result.exit_code == 0
        # Default output should be parseable YAML
        parsed = yaml.safe_load(result.stdout)
        assert isinstance(parsed, dict)
        assert "graph" in parsed

    def test_yaml_short_flag(self, runner, tmp_path, monkeypatch):
        """-f yaml short flag works the same as --format yaml."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "-f", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert "graph" in parsed


# ---------------------------------------------------------------------------
# Tests: --format json
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAuditContextJson:

    def test_json_format_exits_0_with_data(self, runner, tmp_path, monkeypatch):
        """JSON output with valid mock data exits with code 0."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "json"])

        assert result.exit_code == 0

    def test_json_output_is_valid(self, runner, tmp_path, monkeypatch):
        """JSON output parses without errors and produces a dict."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "json"])

        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, dict)

    def test_json_contains_code_graph_key(self, runner, tmp_path, monkeypatch):
        """JSON output top-level contains 'code_graph' key."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "json"])

        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "code_graph" in parsed

    def test_json_contains_gap_report_key(self, runner, tmp_path, monkeypatch):
        """JSON output top-level contains 'gap_report' key with summary fields."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "json"])

        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "gap_report" in parsed
        gap = parsed["gap_report"]
        assert "coverage" in gap
        assert "broken_imports" in gap
        assert "orphan_files" in gap

    def test_json_contains_dependency_graph_key(self, runner, tmp_path, monkeypatch):
        """JSON output top-level contains 'dependency_graph' key."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "json"])

        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "dependency_graph" in parsed
        assert "stats" in parsed["dependency_graph"]

    def test_json_gap_report_counts_are_integers(self, runner, tmp_path, monkeypatch):
        """JSON gap_report summary fields are integer counts, not raw lists."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "json"])

        assert result.exit_code == 0
        gap = json.loads(result.stdout)["gap_report"]
        # Compact mode: values are ints (counts), not lists
        assert isinstance(gap["broken_imports"], int)
        assert isinstance(gap["orphan_files"], int)
        assert isinstance(gap["circular_deps"], int)

    def test_json_code_graph_summary_only_by_default(self, runner, tmp_path, monkeypatch):
        """Default JSON output includes only a code_graph summary (not full node map)."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "json"])

        assert result.exit_code == 0
        cg = json.loads(result.stdout)["code_graph"]
        # Compact mode should contain stats, not the full nodes map
        assert "stats" in cg
        assert "nodes" not in cg  # Full node map excluded in compact mode


# ---------------------------------------------------------------------------
# Tests: --format markdown
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAuditContextMarkdown:

    def test_markdown_format_exits_0_with_data(self, runner, tmp_path, monkeypatch):
        """Markdown output with valid mock data exits with code 0."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown"])

        assert result.exit_code == 0

    def test_markdown_has_main_header(self, runner, tmp_path, monkeypatch):
        """Markdown output starts with an H1 Warden Audit Context header."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown"])

        assert result.exit_code == 0
        assert "# Warden Audit Context" in result.stdout

    def test_markdown_has_code_graph_section(self, runner, tmp_path, monkeypatch):
        """Markdown output includes an H2 Code Graph Overview section."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown"])

        assert result.exit_code == 0
        assert "## Code Graph Overview" in result.stdout

    def test_markdown_has_gap_analysis_section(self, runner, tmp_path, monkeypatch):
        """Markdown output includes an H2 Gap Analysis section."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown"])

        assert result.exit_code == 0
        assert "## Gap Analysis" in result.stdout

    def test_markdown_has_dependency_graph_section(self, runner, tmp_path, monkeypatch):
        """Markdown output includes an H2 Dependency Graph section."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown"])

        assert result.exit_code == 0
        assert "## Dependency Graph" in result.stdout

    def test_markdown_shows_symbol_counts(self, runner, tmp_path, monkeypatch):
        """Markdown code graph section shows node/edge counts from mock data."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown"])

        assert result.exit_code == 0
        # The mock has 3 nodes and 2 edges
        assert "3" in result.stdout
        assert "2" in result.stdout

    def test_markdown_shows_coverage_percentage(self, runner, tmp_path, monkeypatch):
        """Markdown gap analysis section shows coverage formatted as a percentage."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown"])

        assert result.exit_code == 0
        # 0.87 coverage → rendered as 87.0%
        assert "87" in result.stdout

    def test_markdown_md_alias_works(self, runner, tmp_path, monkeypatch):
        """--format md alias produces the same markdown output as --format markdown."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "md"])

        assert result.exit_code == 0
        assert "# Warden Audit Context" in result.stdout


# ---------------------------------------------------------------------------
# Tests: --full flag
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAuditContextFull:

    def test_full_flag_exits_0(self, runner, tmp_path, monkeypatch):
        """--full flag completes successfully with valid mock data."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--full"])

        assert result.exit_code == 0

    def test_full_yaml_includes_more_sections_than_compact(self, runner, tmp_path, monkeypatch):
        """--full YAML output has more content than compact YAML output."""
        # Arrange: include a broken import so --full has detail to emit
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, broken_imports=["warden.missing.module"])
        monkeypatch.chdir(tmp_path)

        compact = runner.invoke(app, ["audit-context", "--format", "yaml"])
        full = runner.invoke(app, ["audit-context", "--format", "yaml", "--full"])

        assert compact.exit_code == 0
        assert full.exit_code == 0
        # Full output should be longer than compact due to detail sections
        assert len(full.stdout) > len(compact.stdout)

    def test_full_yaml_contains_broken_imports_detail(self, runner, tmp_path, monkeypatch):
        """--full YAML includes 'broken_imports_detail' when broken imports exist."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, broken_imports=["warden.missing.module"])
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml", "--full"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert "broken_imports_detail" in parsed
        assert "warden.missing.module" in parsed["broken_imports_detail"]

    def test_full_json_includes_full_node_map(self, runner, tmp_path, monkeypatch):
        """--full JSON includes the complete node map, not just stats."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "json", "--full"])

        assert result.exit_code == 0
        cg = json.loads(result.stdout)["code_graph"]
        # Full mode includes the nodes map
        assert "nodes" in cg

    def test_full_markdown_includes_symbol_map_table_for_classes(
        self, runner, tmp_path, monkeypatch
    ):
        """--full markdown includes a Symbol Map table when class nodes are present."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown", "--full"])

        assert result.exit_code == 0
        # Symbol Map table header should appear in full mode
        assert "Symbol Map" in result.stdout

    def test_full_markdown_includes_class_hierarchy_for_inherits_edges(
        self, runner, tmp_path, monkeypatch
    ):
        """--full markdown includes Class Hierarchy section when inherits edges exist."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown", "--full"])

        assert result.exit_code == 0
        assert "Class Hierarchy" in result.stdout


# ---------------------------------------------------------------------------
# Tests: --check mode
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAuditContextCheck:

    def test_check_no_broken_imports_exits_0(self, runner, tmp_path, monkeypatch):
        """--check exits 0 when no broken imports or other critical gaps exist."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, broken_imports=[])
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--check"])

        assert result.exit_code == 0

    def test_check_no_gaps_prints_success_message(self, runner, tmp_path, monkeypatch):
        """--check with no critical gaps prints a success message."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, broken_imports=[])
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--check"])

        assert result.exit_code == 0
        stdout = result.stdout.lower()
        assert "no critical" in stdout or "critical gaps" in stdout

    def test_check_broken_imports_exits_1(self, runner, tmp_path, monkeypatch):
        """--check exits 1 when broken imports are present."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, broken_imports=["warden.missing.module"])
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--check"])

        assert result.exit_code == 1

    def test_check_broken_imports_shows_critical_message(self, runner, tmp_path, monkeypatch):
        """--check with broken imports prints a CRITICAL message."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(
            intel_dir,
            broken_imports=["warden.missing.module", "warden.other.missing"],
        )
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--check"])

        assert result.exit_code == 1
        stdout = result.stdout.lower()
        assert "critical" in stdout or "broken" in stdout

    def test_check_broken_imports_lists_them(self, runner, tmp_path, monkeypatch):
        """--check output lists each broken import (up to 10)."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, broken_imports=["warden.missing.module"])
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--check"])

        assert result.exit_code == 1
        assert "warden.missing.module" in result.stdout

    def test_check_many_circular_deps_exits_1(self, runner, tmp_path, monkeypatch):
        """--check exits 1 when there are more than 5 circular dependency cycles."""
        intel_dir = _make_intelligence_dir(tmp_path)
        # Write a gap report with 6 circular dep cycles (above the threshold of 5)
        gap_report = {
            "coverage": 0.90,
            "orphan_files": [],
            "orphan_symbols": [],
            "broken_imports": [],
            "circular_deps": [
                ["a", "b", "a"],
                ["c", "d", "c"],
                ["e", "f", "e"],
                ["g", "h", "g"],
                ["i", "j", "i"],
                ["k", "l", "k"],
            ],
            "unreachable_from_entry": [],
            "missing_mixin_impl": [],
            "star_imports": [],
            "dynamic_imports": [],
            "unparseable_files": [],
        }
        (intel_dir / "gap_report.json").write_text(
            json.dumps(gap_report, indent=2), encoding="utf-8"
        )
        _write_mock_code_graph(intel_dir)
        _write_mock_dependency_graph(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--check"])

        assert result.exit_code == 1

    def test_check_does_not_render_full_output(self, runner, tmp_path, monkeypatch):
        """--check mode should not emit a full YAML/JSON/Markdown render."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, broken_imports=[])
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--check"])

        assert result.exit_code == 0
        # No YAML/JSON structure dump in check mode
        assert "graph:" not in result.stdout
        assert '"code_graph"' not in result.stdout
        assert "## Code Graph" not in result.stdout


# ---------------------------------------------------------------------------
# Tests: --help
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAuditContextHelp:

    def test_help_exits_0(self, runner):
        """--help exits with code 0."""
        result = runner.invoke(app, ["audit-context", "--help"])

        assert result.exit_code == 0

    def test_help_shows_format_flag(self, runner):
        """--help output documents the --format flag."""
        result = runner.invoke(app, ["audit-context", "--help"])

        assert result.exit_code == 0
        assert "--format" in result.stdout

    def test_help_shows_full_flag(self, runner):
        """--help output documents the --full flag."""
        result = runner.invoke(app, ["audit-context", "--help"])

        assert result.exit_code == 0
        assert "--full" in result.stdout

    def test_help_shows_check_flag(self, runner):
        """--help output documents the --check flag."""
        result = runner.invoke(app, ["audit-context", "--help"])

        assert result.exit_code == 0
        assert "--check" in result.stdout

    def test_help_shows_format_options(self, runner):
        """--help mentions valid format values: yaml, json, markdown."""
        result = runner.invoke(app, ["audit-context", "--help"])

        assert result.exit_code == 0
        stdout = result.stdout.lower()
        # All three formats should be referenced in the help text
        assert "yaml" in stdout
        assert "json" in stdout
        assert "markdown" in stdout

    def test_audit_context_in_app_help(self, runner):
        """Root --help lists audit-context as a registered command."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "audit-context" in result.stdout


# ---------------------------------------------------------------------------
# Tests: edge cases and output correctness
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAuditContextEdgeCases:

    def test_only_code_graph_file_present(self, runner, tmp_path, monkeypatch):
        """Command succeeds when only code_graph.json is present."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_mock_code_graph(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert "graph" in parsed

    def test_only_gap_report_file_present(self, runner, tmp_path, monkeypatch):
        """Command succeeds when only gap_report.json is present."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_mock_gap_report(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert "gaps" in parsed

    def test_only_dependency_graph_file_present(self, runner, tmp_path, monkeypatch):
        """Command succeeds when only dependency_graph.json is present."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_mock_dependency_graph(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert "dependencies" in parsed

    def test_corrupt_json_file_does_not_crash(self, runner, tmp_path, monkeypatch):
        """Corrupted JSON files are skipped gracefully; command still exits 0."""
        intel_dir = _make_intelligence_dir(tmp_path)
        # Write valid code_graph but corrupt gap_report
        _write_mock_code_graph(intel_dir)
        (intel_dir / "gap_report.json").write_text("{ invalid json !!!", encoding="utf-8")
        _write_mock_dependency_graph(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        # Should complete without crashing; only valid files contribute to output
        assert result.exit_code == 0

    def test_yaml_output_ends_with_newline(self, runner, tmp_path, monkeypatch):
        """YAML output ends with a newline for correct terminal/pipe behaviour."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        assert result.stdout.endswith("\n")

    def test_json_output_ends_with_newline(self, runner, tmp_path, monkeypatch):
        """JSON output ends with a newline for correct terminal/pipe behaviour."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "json"])

        assert result.exit_code == 0
        assert result.stdout.endswith("\n")

    def test_markdown_output_ends_with_newline(self, runner, tmp_path, monkeypatch):
        """Markdown output ends with a newline for correct terminal/pipe behaviour."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown"])

        assert result.exit_code == 0
        assert result.stdout.endswith("\n")

    def test_yaml_integrity_flag_value(self, runner, tmp_path, monkeypatch):
        """YAML dependencies section reflects integrity check from mock data."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        # Mock dep graph has forward_reverse_match=True → integrity_ok should be True
        assert parsed["dependencies"]["integrity_ok"] is True

    def test_json_integrity_flag_value(self, runner, tmp_path, monkeypatch):
        """JSON dependency_graph section reflects integrity data from mock."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "json"])

        assert result.exit_code == 0
        dep = json.loads(result.stdout)["dependency_graph"]
        assert dep["integrity"]["forward_reverse_match"] is True


# ---------------------------------------------------------------------------
# Tests: chain_validation rendering
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAuditContextChainValidation:

    def test_yaml_includes_lsp_validation_section(self, runner, tmp_path, monkeypatch):
        """YAML output includes lsp_validation when chain_validation.json exists."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, include_chain_validation=True)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert "lsp_validation" in parsed
        assert parsed["lsp_validation"]["confirmed"] == 15
        assert parsed["lsp_validation"]["unconfirmed"] == 3

    def test_json_includes_chain_validation_key(self, runner, tmp_path, monkeypatch):
        """JSON output includes chain_validation when data exists."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, include_chain_validation=True)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "json"])

        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "chain_validation" in parsed
        assert parsed["chain_validation"]["confirmed"] == 15
        assert parsed["chain_validation"]["unconfirmed"] == 3

    def test_markdown_includes_lsp_chain_validation_section(self, runner, tmp_path, monkeypatch):
        """Markdown output includes LSP Chain Validation section when data exists."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, include_chain_validation=True)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown"])

        assert result.exit_code == 0
        assert "## LSP Chain Validation" in result.stdout
        assert "Confirmation rate" in result.stdout

    def test_markdown_shows_dead_symbols_in_full_mode(self, runner, tmp_path, monkeypatch):
        """--full markdown shows dead symbol list from chain_validation."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(
            intel_dir,
            include_chain_validation=True,
            dead_symbols=["unused_func", "dead_class"],
        )
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown", "--full"])

        assert result.exit_code == 0
        assert "Dead Symbols" in result.stdout
        assert "unused_func" in result.stdout
        assert "dead_class" in result.stdout

    def test_check_warns_on_dead_symbols(self, runner, tmp_path, monkeypatch):
        """--check exits 1 when chain_validation has dead symbols."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(
            intel_dir,
            include_chain_validation=True,
            dead_symbols=["orphan_symbol"],
        )
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--check"])

        assert result.exit_code == 1
        stdout = result.stdout.lower()
        assert "dead symbols" in stdout or "warning" in stdout

    def test_check_passes_with_no_dead_symbols(self, runner, tmp_path, monkeypatch):
        """--check exits 0 when chain_validation has no dead symbols."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, include_chain_validation=True, dead_symbols=[])
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--check"])

        assert result.exit_code == 0

    def test_no_chain_validation_still_works(self, runner, tmp_path, monkeypatch):
        """Command works fine when chain_validation.json is absent."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert "lsp_validation" not in parsed

    def test_yaml_confirmation_rate_format(self, runner, tmp_path, monkeypatch):
        """YAML lsp_validation shows confirmation_rate as a percentage string."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, include_chain_validation=True)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        # 15/(15+3) = 83.3%
        rate = parsed["lsp_validation"]["confirmation_rate"]
        assert "83" in rate


# ---------------------------------------------------------------------------
# Tests: custom template override
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAuditContextCustomTemplate:

    def test_custom_template_overrides_markdown(self, runner, tmp_path, monkeypatch):
        """Custom template from .warden/templates/audit_prompt.md is used for markdown."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir, include_chain_validation=True)

        # Write custom template
        tmpl_dir = tmp_path / ".warden" / "templates"
        tmpl_dir.mkdir(parents=True)
        (tmpl_dir / "audit_prompt.md").write_text(
            "# Custom Report\nStats: $stats\nGaps: $gap_summary\nLSP: $chain_validation\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "markdown"])

        assert result.exit_code == 0
        assert "# Custom Report" in result.stdout
        assert "Stats:" in result.stdout
        # Should NOT have default header
        assert "# Warden Audit Context" not in result.stdout

    def test_custom_template_does_not_affect_yaml(self, runner, tmp_path, monkeypatch):
        """Custom template only applies to markdown, not yaml format."""
        intel_dir = _make_intelligence_dir(tmp_path)
        _write_all_mock_data(intel_dir)

        tmpl_dir = tmp_path / ".warden" / "templates"
        tmpl_dir.mkdir(parents=True)
        (tmpl_dir / "audit_prompt.md").write_text("# Custom", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit-context", "--format", "yaml"])

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert isinstance(parsed, dict)
        assert "graph" in parsed
