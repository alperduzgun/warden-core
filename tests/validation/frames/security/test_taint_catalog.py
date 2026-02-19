"""Tests for TaintCatalog — default catalog and user-extensible YAML loading."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from warden.validation.frames.security._internal.taint_catalog import TaintCatalog


class TestTaintCatalogDefault:
    """Tests for TaintCatalog.get_default()."""

    def setup_method(self):
        self.catalog = TaintCatalog.get_default()

    def test_python_sources_present(self):
        py_sources = self.catalog.sources.get("python", set())
        assert "request.args" in py_sources
        assert "request.form" in py_sources
        assert "input" in py_sources
        assert "os.environ" in py_sources

    def test_javascript_sources_present(self):
        js_sources = self.catalog.sources.get("javascript", set())
        assert "req.body" in js_sources
        assert "req.query" in js_sources
        assert "process.env" in js_sources
        assert "document.cookie" in js_sources

    def test_python_sinks_present(self):
        assert "cursor.execute" in self.catalog.sinks
        assert self.catalog.sinks["cursor.execute"] == "SQL-value"
        assert "os.system" in self.catalog.sinks
        assert self.catalog.sinks["os.system"] == "CMD-argument"
        assert "eval" in self.catalog.sinks
        assert self.catalog.sinks["eval"] == "CODE-execution"

    def test_javascript_sinks_present(self):
        assert "db.query" in self.catalog.sinks
        assert self.catalog.sinks["db.query"] == "SQL-value"
        assert "exec" in self.catalog.sinks
        assert self.catalog.sinks["exec"] == "CMD-argument"

    def test_assign_sinks_present(self):
        assert "innerHTML" in self.catalog.assign_sinks
        assert "outerHTML" in self.catalog.assign_sinks

    def test_python_sanitizers_present(self):
        html_sans = self.catalog.sanitizers.get("HTML-content", set())
        assert "html.escape" in html_sans
        sql_sans = self.catalog.sanitizers.get("SQL-value", set())
        assert "parameterized_query" in sql_sans
        cmd_sans = self.catalog.sanitizers.get("CMD-argument", set())
        assert "shlex.quote" in cmd_sans

    def test_javascript_sanitizers_present(self):
        html_sans = self.catalog.sanitizers.get("HTML-content", set())
        assert "DOMPurify.sanitize" in html_sans
        sql_sans = self.catalog.sanitizers.get("SQL-value", set())
        assert "db.escape" in sql_sans

    def test_all_sink_types_covered(self):
        expected_types = {"SQL-value", "CMD-argument", "HTML-content", "CODE-execution", "FILE-path"}
        actual_types = set(self.catalog.sinks.values())
        assert expected_types.issubset(actual_types)

    def test_sanitizers_all_sink_types_present(self):
        expected_keys = {"SQL-value", "CMD-argument", "HTML-content", "CODE-execution", "FILE-path"}
        assert expected_keys.issubset(set(self.catalog.sanitizers.keys()))

    def test_sources_dict_contains_two_languages(self):
        assert "python" in self.catalog.sources
        assert "javascript" in self.catalog.sources

    def test_default_catalog_is_mutable_without_affecting_next_call(self):
        """Each get_default() call returns independent sets."""
        c1 = TaintCatalog.get_default()
        c2 = TaintCatalog.get_default()
        c1.sources["python"].add("__SENTINEL__")
        assert "__SENTINEL__" not in c2.sources.get("python", set())


class TestTaintCatalogLoad:
    """Tests for TaintCatalog.load()."""

    def test_load_no_file_returns_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = TaintCatalog.load(root)
            assert "request.args" in catalog.sources.get("python", set())
            assert "cursor.execute" in catalog.sinks

    def test_load_extends_python_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text(
                "sources:\n  python:\n    - fastapi.Request.query_params\n"
            )
            catalog = TaintCatalog.load(root)
            # Custom entry added
            assert "fastapi.Request.query_params" in catalog.sources.get("python", set())
            # Built-in still present
            assert "request.args" in catalog.sources.get("python", set())

    def test_load_extends_javascript_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text(
                "sources:\n  javascript:\n    - ctx.request.body\n"
            )
            catalog = TaintCatalog.load(root)
            assert "ctx.request.body" in catalog.sources.get("javascript", set())
            assert "req.body" in catalog.sources.get("javascript", set())

    def test_load_extends_sinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            content = yaml.dump({"sinks": {"SQL-value": ["prisma.query", "mongoose.find"]}})
            (root / ".warden" / "taint_catalog.yaml").write_text(content)
            catalog = TaintCatalog.load(root)
            assert "prisma.query" in catalog.sinks
            assert catalog.sinks["prisma.query"] == "SQL-value"
            assert "mongoose.find" in catalog.sinks
            assert catalog.sinks["mongoose.find"] == "SQL-value"
            # Built-in sinks still present
            assert "cursor.execute" in catalog.sinks

    def test_load_extends_sanitizers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text(
                "sanitizers:\n  HTML-content:\n    - myCustomSanitizer\n"
            )
            catalog = TaintCatalog.load(root)
            assert "myCustomSanitizer" in catalog.sanitizers.get("HTML-content", set())
            # Built-in sanitizer still present
            assert "html.escape" in catalog.sanitizers.get("HTML-content", set())

    def test_load_all_sections_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            data = {
                "sources": {
                    "python": ["fastapi.Request.query_params"],
                    "javascript": ["ctx.request.body"],
                },
                "sinks": {
                    "SQL-value": ["prisma.raw"],
                    "CMD-argument": ["custom_shell.exec"],
                },
                "sanitizers": {
                    "HTML-content": ["myCustomSanitizer"],
                    "SQL-value": ["parameterized_prisma"],
                },
            }
            (root / ".warden" / "taint_catalog.yaml").write_text(yaml.dump(data))
            catalog = TaintCatalog.load(root)

            # Sources
            assert "fastapi.Request.query_params" in catalog.sources.get("python", set())
            assert "request.args" in catalog.sources.get("python", set())
            assert "ctx.request.body" in catalog.sources.get("javascript", set())
            assert "req.body" in catalog.sources.get("javascript", set())

            # Sinks
            assert catalog.sinks.get("prisma.raw") == "SQL-value"
            assert catalog.sinks.get("custom_shell.exec") == "CMD-argument"
            assert "cursor.execute" in catalog.sinks

            # Sanitizers
            assert "myCustomSanitizer" in catalog.sanitizers.get("HTML-content", set())
            assert "html.escape" in catalog.sanitizers.get("HTML-content", set())
            assert "parameterized_prisma" in catalog.sanitizers.get("SQL-value", set())
            assert "parameterized_query" in catalog.sanitizers.get("SQL-value", set())

    def test_load_malformed_yaml_returns_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text(": invalid: yaml: [")
            catalog = TaintCatalog.load(root)
            # Falls back to default gracefully
            assert "request.args" in catalog.sources.get("python", set())

    def test_load_empty_yaml_returns_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text("")
            catalog = TaintCatalog.load(root)
            assert "request.args" in catalog.sources.get("python", set())

    def test_load_null_sections_ignored(self):
        """Null/empty sections don't overwrite defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text(
                "sources:\nsinks:\nsanitizers:\n"
            )
            catalog = TaintCatalog.load(root)
            assert "request.args" in catalog.sources.get("python", set())
            assert "cursor.execute" in catalog.sinks

    def test_load_empty_lists_ignored(self):
        """Empty lists for a section don't break defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            data = {"sources": {"python": [], "javascript": []}, "sinks": {"SQL-value": []}}
            (root / ".warden" / "taint_catalog.yaml").write_text(yaml.dump(data))
            catalog = TaintCatalog.load(root)
            assert "request.args" in catalog.sources.get("python", set())
            assert "cursor.execute" in catalog.sinks

    def test_load_new_language_added(self):
        """User can introduce a new language key (e.g., ruby) for future use."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text(
                "sources:\n  ruby:\n    - params[:id]\n"
            )
            catalog = TaintCatalog.load(root)
            assert "params[:id]" in catalog.sources.get("ruby", set())
            # Other languages unaffected
            assert "request.args" in catalog.sources.get("python", set())

    def test_load_invalid_entry_types_skipped(self):
        """Non-string entries (int, null) in lists are silently skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text(
                "sources:\n  python:\n    - valid.source\n    - 42\n    - null\n"
            )
            catalog = TaintCatalog.load(root)
            assert "valid.source" in catalog.sources.get("python", set())
            assert 42 not in catalog.sources.get("python", set())


class TestTaintCatalogWithAnalyzer:
    """Integration: custom catalog entries are picked up by TaintAnalyzer."""

    def test_custom_python_source_detected(self):
        from warden.validation.frames.security._internal.taint_analyzer import TaintAnalyzer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text(
                "sources:\n  python:\n    - fastapi.Request.query_params\n"
            )
            catalog = TaintCatalog.load(root)
            analyzer = TaintAnalyzer(catalog=catalog)

            code = """
def handler(req):
    uid = fastapi.Request.query_params.get("id")
    cursor.execute(f"SELECT * FROM users WHERE id = {uid}")
"""
            paths = analyzer.analyze(code)
            assert len(paths) >= 1
            assert any("fastapi" in p.source.name for p in paths)

    def test_custom_sink_detected(self):
        from warden.validation.frames.security._internal.taint_analyzer import TaintAnalyzer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text(
                "sinks:\n  SQL-value:\n    - prisma.raw\n"
            )
            catalog = TaintCatalog.load(root)
            analyzer = TaintAnalyzer(catalog=catalog)

            code = """
def handler(req):
    uid = request.args.get("id")
    prisma.raw(f"SELECT * FROM users WHERE id = {uid}")
"""
            paths = analyzer.analyze(code)
            assert len(paths) >= 1
            assert any("prisma" in p.sink.name for p in paths)

    def test_custom_js_source_detected(self):
        from warden.validation.frames.security._internal.taint_analyzer import TaintAnalyzer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text(
                "sources:\n  javascript:\n    - ctx.request.body\n"
            )
            catalog = TaintCatalog.load(root)
            analyzer = TaintAnalyzer(catalog=catalog)

            code = "const id = ctx.request.body.id;\ndb.query(`SELECT * FROM t WHERE id = ${id}`);"
            paths = analyzer.analyze(code, language="javascript")
            assert len(paths) >= 1

    def test_builtin_entries_still_work_with_custom_catalog(self):
        """Built-in detection is not broken when custom entries are loaded."""
        from warden.validation.frames.security._internal.taint_analyzer import TaintAnalyzer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text(
                "sources:\n  python:\n    - custom.source\n"
            )
            catalog = TaintCatalog.load(root)
            analyzer = TaintAnalyzer(catalog=catalog)

            # Built-in source still detected
            code = """
def get_user():
    uid = request.args.get('id')
    cursor.execute(f"SELECT * FROM users WHERE id = {uid}")
"""
            paths = analyzer.analyze(code)
            assert len(paths) >= 1
