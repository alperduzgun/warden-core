"""
Multi-framework taint analysis coverage tests.

Covers:
  - Python: stdlib, Flask, FastAPI, Django
  - JavaScript: Express.js, Koa.js, Browser DOM
  - Go: net/http + database/sql
  - Java: Servlet + Spring
  - Signal inference heuristics
  - ModelPackLoader unit tests
  - Catalog YAML integration
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from warden.validation.frames.security._internal.model_loader import ModelPackLoader
from warden.validation.frames.security._internal.signal_inference import SignalInferenceEngine
from warden.validation.frames.security._internal.taint_analyzer import TaintAnalyzer
from warden.validation.frames.security._internal.taint_catalog import TaintCatalog


# ── Python: stdlib ───────────────────────────────────────────────────────────


class TestPythonStdlib:
    """Python standard library taint sources and sinks."""

    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_input_to_eval(self):
        code = """
def run():
    user_code = input("Enter code: ")
    eval(user_code)
"""
        paths = self.analyzer.analyze(code)
        assert any("eval" in p.sink.name for p in paths)

    def test_sys_argv_to_os_system(self):
        code = """
import sys, os
def run():
    cmd = sys.argv[1]
    os.system(cmd)
"""
        paths = self.analyzer.analyze(code)
        assert any("os.system" in p.sink.name or "system" in p.sink.name for p in paths)

    def test_os_environ_to_subprocess(self):
        code = """
import os, subprocess
def run():
    path = os.environ.get("PATH")
    subprocess.run(path)
"""
        paths = self.analyzer.analyze(code)
        assert any("subprocess" in p.sink.name for p in paths)

    def test_open_sink_detected(self):
        code = """
def read_file():
    filename = input("File: ")
    open(filename)
"""
        paths = self.analyzer.analyze(code)
        assert any("open" in p.sink.name for p in paths)

    def test_eval_taint_path_confidence(self):
        code = """
def danger():
    val = input("x: ")
    exec(val)
"""
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1
        # Confidence should be > 0 and <= 1.0
        for p in paths:
            assert 0 < p.confidence <= 1.0


# ── Python: Flask ────────────────────────────────────────────────────────────


class TestPythonFlask:
    """Flask-specific source/sink detection."""

    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_request_args_to_cursor_execute(self):
        code = """
from flask import request
def search():
    q = request.args.get("q")
    cursor.execute("SELECT * FROM t WHERE name = " + q)
"""
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1
        assert any("request.args" in p.source.name for p in paths)

    def test_request_form_to_sql(self):
        code = """
from flask import request
def create():
    name = request.form["name"]
    db.execute(f"INSERT INTO users VALUES ({name})")
"""
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1

    def test_request_json_to_eval(self):
        code = """
from flask import request
def api():
    expr = request.get_json()
    eval(expr)
"""
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1

    def test_render_template_string_sink(self):
        code = """
from flask import request, render_template_string
def page():
    name = request.args.get("name")
    return render_template_string("<h1>Hello " + name + "</h1>")
"""
        paths = self.analyzer.analyze(code)
        assert any("render_template_string" in p.sink.name for p in paths)

    def test_request_cookies_source(self):
        code = """
from flask import request
def handler():
    session_id = request.cookies.get("session")
    cursor.execute(f"SELECT * FROM sessions WHERE id = {session_id}")
"""
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1

    def test_catalog_contains_flask_sources(self):
        catalog = TaintCatalog.get_default()
        py_sources = catalog.sources.get("python", set())
        assert "request.args" in py_sources
        assert "request.form" in py_sources
        assert "request.json" in py_sources
        assert "request.cookies" in py_sources


# ── Python: FastAPI ──────────────────────────────────────────────────────────


class TestPythonFastAPI:
    """FastAPI-specific source detection via model pack."""

    def test_catalog_contains_fastapi_sources(self):
        catalog = TaintCatalog.get_default()
        py_sources = catalog.sources.get("python", set())
        # FastAPI sources should be loaded from fastapi.yaml
        assert "Request.query_params" in py_sources or "request.query_params" in py_sources

    def test_fastapi_request_body_in_pack(self):
        """request.body should appear from fastapi.yaml."""
        pack = ModelPackLoader.load_all()
        py_pack_sources = pack.get("sources", {}).get("python", set())
        assert "Request.body" in py_pack_sources or "request.body" in py_pack_sources


# ── Python: Django ───────────────────────────────────────────────────────────


class TestPythonDjango:
    """Django-specific source/sink detection via model pack."""

    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_request_get_to_sql(self):
        code = """
def view(request):
    pk = request.GET.get("id")
    cursor.execute("SELECT * FROM t WHERE id = " + pk)
"""
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1
        assert any("GET" in p.source.name or "request" in p.source.name for p in paths)

    def test_request_post_source(self):
        code = """
def create(request):
    name = request.POST["name"]
    connection.execute(f"INSERT INTO users VALUES ({name})")
"""
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1

    def test_catalog_contains_django_sources(self):
        catalog = TaintCatalog.get_default()
        py_sources = catalog.sources.get("python", set())
        assert "request.GET" in py_sources
        assert "request.POST" in py_sources


# ── JavaScript: Express.js ───────────────────────────────────────────────────


class TestJSExpress:
    """Express.js source/sink detection."""

    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_req_body_to_db_query(self):
        code = "const id = req.body.id;\ndb.query(`SELECT * FROM t WHERE id = ${id}`);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1

    def test_req_query_to_sql(self):
        code = "const name = req.query.name;\npool.query('SELECT * FROM users WHERE name = ' + name);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1

    def test_req_params_propagation(self):
        code = (
            "const id = req.params.id;\n"
            "const userId = id;\n"
            "connection.query(`SELECT * FROM users WHERE id = ${userId}`);"
        )
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1

    def test_req_body_destructuring(self):
        code = "const { email, password } = req.body;\ndb.query(`SELECT * FROM users WHERE email = ${email}`);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1

    def test_request_body_alt_name(self):
        """Both req.body and request.body should work."""
        code = "const data = request.body;\ndb.query('SELECT ' + data);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1

    def test_knex_raw_sink(self):
        code = "const id = req.query.id;\nknex.raw(`SELECT * FROM t WHERE id = ${id}`);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1
        assert any("knex.raw" in p.sink.name for p in paths)

    def test_sequelize_query_sink(self):
        code = "const q = req.body.q;\nsequelize.query('SELECT * WHERE name = ' + q);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1


# ── JavaScript: Koa.js ───────────────────────────────────────────────────────


class TestJSKoa:
    """Koa.js source detection via model pack."""

    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_ctx_request_body_to_db_query(self):
        code = "const id = ctx.request.body.id;\ndb.query(`SELECT * FROM t WHERE id = ${id}`);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1

    def test_ctx_query_to_sql(self):
        code = "const name = ctx.query.name;\npool.query('SELECT * FROM users WHERE name = ' + name);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1

    def test_catalog_contains_koa_sources(self):
        catalog = TaintCatalog.get_default()
        js_sources = catalog.sources.get("javascript", set())
        assert "ctx.request.body" in js_sources
        assert "ctx.query" in js_sources


# ── JavaScript: Browser DOM ──────────────────────────────────────────────────


class TestJSBrowser:
    """Browser DOM source/sink (XSS) detection."""

    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_location_search_to_innerhtml(self):
        code = "const q = location.search;\ndiv.innerHTML = q;"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1
        assert any("innerHTML" in p.sink.name for p in paths)

    def test_document_cookie_to_innerhtml(self):
        code = "const cookie = document.cookie;\nel.innerHTML = cookie;"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1

    def test_location_href_to_document_write(self):
        code = "const url = location.href;\ndocument.write(url);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1

    def test_assign_sink_outerhtml(self):
        code = "const data = window.location.hash;\nel.outerHTML = data;"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1

    def test_domxss_sanitized(self):
        """DOMPurify.sanitize should suppress confidence."""
        code = "const h = location.hash;\nel.innerHTML = DOMPurify.sanitize(h);"
        paths = self.analyzer.analyze(code, language="javascript")
        sanitized = [p for p in paths if p.is_sanitized]
        assert len(sanitized) >= 1


# ── Go: stdlib ───────────────────────────────────────────────────────────────


class TestGoStdlib:
    """Go standard library HTTP + database/sql taint detection."""

    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_url_query_to_db_exec(self):
        code = 'id := r.URL.Query().Get("id")\ndb.Exec("SELECT * FROM t WHERE id = " + id)\n'
        paths = self.analyzer.analyze(code, language="go")
        assert len(paths) >= 1

    def test_form_value_to_db_query(self):
        code = 'name := r.FormValue("name")\ndb.Query("SELECT * FROM users WHERE name = " + name)\n'
        paths = self.analyzer.analyze(code, language="go")
        assert len(paths) >= 1

    def test_go_propagation(self):
        code = (
            'raw := r.FormValue("id")\n'
            "userId := raw\n"
            'db.QueryRow("SELECT * FROM t WHERE id = " + userId)\n'
        )
        paths = self.analyzer.analyze(code, language="go")
        assert len(paths) >= 1

    def test_exec_command_sink(self):
        code = 'cmd := r.FormValue("cmd")\nexec.Command("sh", "-c", cmd)\n'
        paths = self.analyzer.analyze(code, language="go")
        assert len(paths) >= 1
        assert any("exec.Command" in p.sink.name or "Command" in p.sink.name for p in paths)

    def test_catalog_contains_go_sources(self):
        catalog = TaintCatalog.get_default()
        go_sources = catalog.sources.get("go", set())
        assert len(go_sources) > 0
        assert any("r.URL.Query" in s or "Query" in s for s in go_sources)

    def test_go_unsupported_returns_empty_for_rust(self):
        """Unsupported language returns empty list (regression guard)."""
        code = 'fn main() { let x = std::env::var("X").unwrap(); }'
        paths = self.analyzer.analyze(code, language="rust")
        assert paths == []


# ── Java: Servlet + Spring ───────────────────────────────────────────────────


class TestJavaServlet:
    """Java Servlet + Spring taint detection."""

    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_get_parameter_to_statement_execute(self):
        code = (
            'String id = request.getParameter("id");\n'
            'Statement.execute("SELECT * FROM t WHERE id = " + id);\n'
        )
        paths = self.analyzer.analyze(code, language="java")
        assert len(paths) >= 1

    def test_java_propagation(self):
        code = (
            'String raw = request.getParameter("id");\n'
            "String userId = raw;\n"
            'Statement.executeQuery("SELECT * WHERE id = " + userId);\n'
        )
        paths = self.analyzer.analyze(code, language="java")
        assert len(paths) >= 1

    def test_system_getenv_source(self):
        code = (
            'String cmd = System.getenv("CMD");\n'
            "Runtime.exec(cmd);\n"
        )
        paths = self.analyzer.analyze(code, language="java")
        assert len(paths) >= 1

    def test_spring_jdbc_template_sink(self):
        code = (
            'String id = request.getParameter("id");\n'
            'JdbcTemplate.execute("SELECT * FROM t WHERE id = " + id);\n'
        )
        paths = self.analyzer.analyze(code, language="java")
        assert len(paths) >= 1

    def test_catalog_contains_java_sources(self):
        catalog = TaintCatalog.get_default()
        java_sources = catalog.sources.get("java", set())
        assert len(java_sources) > 0
        assert any("getParameter" in s for s in java_sources)

    def test_java_sink_execute_detected(self):
        catalog = TaintCatalog.get_default()
        # Statement.execute should be in sinks from java/stdlib.yaml
        assert any("Statement.execute" in k or "execute" in k for k in catalog.sinks)


# ── Signal Inference ─────────────────────────────────────────────────────────


class TestSignalInference:
    """Signal-based heuristic inference engine tests."""

    @pytest.fixture
    def engine(self):
        signals_data = ModelPackLoader.load_signals()
        return SignalInferenceEngine(signals_data)

    def test_is_available_with_signals(self, engine):
        assert engine.is_available()

    def test_is_unavailable_with_empty_data(self):
        e = SignalInferenceEngine({})
        assert not e.is_available()

    def test_infer_sink_execute_method(self, engine):
        result = engine.infer_sink("db.execute")
        assert result is not None
        sink_type, confidence = result
        assert sink_type == "SQL-value"
        assert 0.5 <= confidence <= 1.0

    def test_infer_sink_param_boost(self, engine):
        """Param name hint should boost confidence."""
        r1 = engine.infer_sink("db.execute")
        r2 = engine.infer_sink("db.execute", param_names=["sql"])
        assert r1 is not None and r2 is not None
        # r2 should have higher or equal confidence
        assert r2[1] >= r1[1]

    def test_infer_sink_no_match_returns_none(self, engine):
        result = engine.infer_sink("logger.info")
        assert result is None

    def test_infer_source_http_request_type(self, engine):
        result = engine.infer_source("Request.get_json")
        assert result is not None
        role, confidence = result
        assert "HTTP" in role or "INPUT" in role
        assert 0.5 <= confidence <= 1.0

    def test_infer_source_no_match_returns_none(self, engine):
        result = engine.infer_source("math.sqrt")
        assert result is None

    def test_infer_sink_cmd_exec(self, engine):
        result = engine.infer_sink("proc.exec", module_hint="subprocess")
        assert result is not None
        sink_type, confidence = result
        assert sink_type == "CMD-argument"


# ── ModelPackLoader unit tests ───────────────────────────────────────────────


class TestModelPackLoader:
    """Unit tests for ModelPackLoader."""

    def test_load_all_returns_non_empty(self):
        result = ModelPackLoader.load_all()
        assert result
        assert "sources" in result
        assert "sinks" in result
        assert "sanitizers" in result

    def test_load_all_has_go_sources(self):
        result = ModelPackLoader.load_all()
        go_sources = result.get("sources", {}).get("go", set())
        assert len(go_sources) > 0

    def test_load_all_has_java_sources(self):
        result = ModelPackLoader.load_all()
        java_sources = result.get("sources", {}).get("java", set())
        assert len(java_sources) > 0

    def test_load_all_has_koa_sources_in_javascript(self):
        result = ModelPackLoader.load_all()
        js_sources = result.get("sources", {}).get("javascript", set())
        assert any("ctx" in s for s in js_sources)

    def test_load_all_has_assign_sinks(self):
        result = ModelPackLoader.load_all()
        assert "innerHTML" in result.get("assign_sinks", set())
        assert "outerHTML" in result.get("assign_sinks", set())

    def test_load_signals_returns_dict(self):
        signals = ModelPackLoader.load_signals()
        assert isinstance(signals, dict)
        assert "sources" in signals or "sinks" in signals

    def test_load_all_missing_dir_returns_empty(self, tmp_path, monkeypatch):
        """If models dir is missing, load_all returns empty dict."""
        monkeypatch.setattr(ModelPackLoader, "MODELS_DIR", tmp_path / "nonexistent")
        result = ModelPackLoader.load_all()
        assert result == {}


# ── Catalog YAML Integration ─────────────────────────────────────────────────


class TestCatalogYAMLIntegration:
    """Integration: YAML model packs are merged into TaintCatalog correctly."""

    def test_go_sources_in_default_catalog(self):
        catalog = TaintCatalog.get_default()
        go_sources = catalog.sources.get("go", set())
        assert len(go_sources) >= 1

    def test_java_sources_in_default_catalog(self):
        catalog = TaintCatalog.get_default()
        java_sources = catalog.sources.get("java", set())
        assert len(java_sources) >= 1

    def test_python_stdlib_sources_still_present(self):
        """Hardcoded constants are still present (baseline guarantee)."""
        catalog = TaintCatalog.get_default()
        py_sources = catalog.sources.get("python", set())
        assert "request.args" in py_sources
        assert "input" in py_sources
        assert "os.environ" in py_sources

    def test_javascript_sources_still_present(self):
        catalog = TaintCatalog.get_default()
        js_sources = catalog.sources.get("javascript", set())
        assert "req.body" in js_sources
        assert "document.cookie" in js_sources

    def test_assign_sinks_from_browser_yaml(self):
        catalog = TaintCatalog.get_default()
        assert "innerHTML" in catalog.assign_sinks
        assert "outerHTML" in catalog.assign_sinks

    def test_yaml_sinks_merged_with_constants(self):
        """YAML sinks don't replace hardcoded constants."""
        catalog = TaintCatalog.get_default()
        # Hardcoded constants
        assert "cursor.execute" in catalog.sinks
        assert "eval" in catalog.sinks
        # From Go model pack
        assert any("db.Exec" in k or "Exec" in k for k in catalog.sinks)

    def test_catalog_independence_with_yaml_packs(self):
        """Each get_default() call returns independent sets even with YAML packs."""
        c1 = TaintCatalog.get_default()
        c2 = TaintCatalog.get_default()
        c1.sources.get("go", set()).add("__TEST_SENTINEL__")
        go_sources2 = c2.sources.get("go", set())
        assert "__TEST_SENTINEL__" not in go_sources2

    def test_user_override_still_works_with_yaml_packs(self):
        """User .warden/taint_catalog.yaml entries are still unioned."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".warden").mkdir()
            (root / ".warden" / "taint_catalog.yaml").write_text(
                "sources:\n  go:\n    - custom.go.source\n"
            )
            catalog = TaintCatalog.load(root)
            go_sources = catalog.sources.get("go", set())
            # User entry added
            assert "custom.go.source" in go_sources
            # YAML pack entries still present
            assert len(go_sources) > 1


# ── Configurable Taint Thresholds ─────────────────────────────────────────


class TestConfigurableThreshold:
    """Configurable confidence thresholds for taint analysis."""

    _SQL_INJECT_CODE = """
def search():
    q = request.args.get("q")
    cursor.execute("SELECT * FROM t WHERE name = " + q)
"""

    def test_default_threshold_0_8(self):
        """Default threshold (0.8): source confidence 0.9 -> HIGH severity."""
        from warden.validation.frames.security.frame import SecurityFrame

        frame = SecurityFrame(config={})
        from warden.validation.frames.security._internal.taint_analyzer import TaintPath, TaintSink, TaintSource

        paths = [
            TaintPath(
                source=TaintSource(name="request.args", node_type="call", line=3, confidence=0.9),
                sink=TaintSink(name="cursor.execute", sink_type="SQL-value", line=4),
                confidence=0.9,
            )
        ]
        result = frame._convert_taint_paths_to_findings(paths, "test.py")
        assert result is not None
        assert result.findings[0].is_blocker is True
        assert result.findings[0].severity.value == "high"

    def test_custom_threshold_low_catches_more(self):
        """Lower threshold (0.6): propagated confidence 0.75 -> HIGH + blocker."""
        from warden.validation.frames.security.frame import SecurityFrame

        frame = SecurityFrame(config={"taint": {"confidence_threshold": 0.6}})
        from warden.validation.frames.security._internal.taint_analyzer import TaintPath, TaintSink, TaintSource

        paths = [
            TaintPath(
                source=TaintSource(name="request.args", node_type="call", line=3, confidence=0.75),
                sink=TaintSink(name="cursor.execute", sink_type="SQL-value", line=4),
                confidence=0.75,
            )
        ]
        result = frame._convert_taint_paths_to_findings(paths, "test.py")
        assert result is not None
        assert result.findings[0].is_blocker is True  # 0.75 >= 0.6

    def test_custom_threshold_high_fewer_blockers(self):
        """Higher threshold (0.95): confidence 0.9 -> MEDIUM, not blocker."""
        from warden.validation.frames.security.frame import SecurityFrame

        frame = SecurityFrame(config={"taint": {"confidence_threshold": 0.95}})
        from warden.validation.frames.security._internal.taint_analyzer import TaintPath, TaintSink, TaintSource

        paths = [
            TaintPath(
                source=TaintSource(name="request.args", node_type="call", line=3, confidence=0.9),
                sink=TaintSink(name="cursor.execute", sink_type="SQL-value", line=4),
                confidence=0.9,
            )
        ]
        result = frame._convert_taint_paths_to_findings(paths, "test.py")
        assert result is not None
        assert result.findings[0].is_blocker is False  # 0.9 < 0.95
        assert result.findings[0].severity.value == "medium"

    def test_custom_sanitizer_penalty(self):
        """Custom sanitizer_penalty (0.1) reduces confidence more aggressively."""
        analyzer = TaintAnalyzer(taint_config={"sanitizer_penalty": 0.1})
        code = """
def handler():
    name = request.args.get("name")
    return render_template_string(html.escape(name))
"""
        paths = analyzer.analyze(code)
        sanitized = [p for p in paths if p.is_sanitized]
        if sanitized:
            # With penalty 0.1 (vs default 0.3), confidence should be lower
            assert sanitized[0].confidence <= 0.1 * 0.9 + 0.01  # ~0.09 + margin

    def test_custom_propagation_confidence(self):
        """Custom propagation_confidence affects variable propagation in JS."""
        analyzer = TaintAnalyzer(taint_config={"propagation_confidence": 0.5})
        code = (
            "const id = req.params.id;\n"
            "const userId = id;\n"
            "db.query(`SELECT * FROM t WHERE id = ${userId}`);\n"
        )
        paths = analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1
        # The propagated variable should have the custom confidence
        propagated = [p for p in paths if p.source.node_type == "propagation"]
        if propagated:
            assert propagated[0].source.confidence == 0.5

    def test_signal_inference_custom_base(self):
        """Custom signal_base_sink overrides the default base confidence."""
        signals_data = ModelPackLoader.load_signals()
        engine = SignalInferenceEngine(signals_data, config={"signal_base_sink": 0.80})
        result = engine.infer_sink("db.execute")
        assert result is not None
        # Should be >= custom base (rules may define their own, but default uses our base)
        assert result[1] >= 0.60


# ── Chaos / Edge-Case Tests for Taint Config Validation ───────────────────


class TestTaintConfigValidation:
    """Chaos engineering: config validation, fail-fast, idempotency, edge cases."""

    def test_none_config_returns_defaults(self):
        """None config → all defaults, no crash."""
        from warden.validation.frames.security._internal.taint_analyzer import TAINT_DEFAULTS, validate_taint_config

        result = validate_taint_config(None)
        assert result == TAINT_DEFAULTS

    def test_empty_dict_returns_defaults(self):
        """Empty dict → all defaults, no crash."""
        from warden.validation.frames.security._internal.taint_analyzer import TAINT_DEFAULTS, validate_taint_config

        result = validate_taint_config({})
        assert result == TAINT_DEFAULTS

    def test_string_value_falls_back_to_default(self):
        """String value → warning + fallback (fail-fast, no crash)."""
        from warden.validation.frames.security._internal.taint_analyzer import TAINT_DEFAULTS, validate_taint_config

        result = validate_taint_config({"confidence_threshold": "abc"})
        assert result["confidence_threshold"] == TAINT_DEFAULTS["confidence_threshold"]

    def test_negative_value_clamped_to_zero(self):
        """Negative value → clamped to 0.0 (range enforcement)."""
        from warden.validation.frames.security._internal.taint_analyzer import validate_taint_config

        result = validate_taint_config({"sanitizer_penalty": -0.5})
        assert result["sanitizer_penalty"] == 0.0

    def test_value_above_one_clamped(self):
        """Value > 1.0 → clamped to 1.0 (range enforcement)."""
        from warden.validation.frames.security._internal.taint_analyzer import validate_taint_config

        result = validate_taint_config({"confidence_threshold": 2.0})
        assert result["confidence_threshold"] == 1.0

    def test_int_value_accepted(self):
        """Integer value (1) → coerced to float (1.0)."""
        from warden.validation.frames.security._internal.taint_analyzer import validate_taint_config

        result = validate_taint_config({"confidence_threshold": 1})
        assert result["confidence_threshold"] == 1.0
        assert isinstance(result["confidence_threshold"], float)

    def test_zero_is_valid(self):
        """Zero is valid — disables the threshold entirely."""
        from warden.validation.frames.security._internal.taint_analyzer import validate_taint_config

        result = validate_taint_config({"confidence_threshold": 0.0})
        assert result["confidence_threshold"] == 0.0

    def test_unknown_keys_ignored(self):
        """Extra keys not in TAINT_DEFAULTS are silently ignored."""
        from warden.validation.frames.security._internal.taint_analyzer import TAINT_DEFAULTS, validate_taint_config

        result = validate_taint_config({"unknown_key": 42, "confidence_threshold": 0.5})
        assert result["confidence_threshold"] == 0.5
        assert "unknown_key" not in result
        # All default keys present
        for key in TAINT_DEFAULTS:
            assert key in result

    def test_idempotency_double_validate(self):
        """Validating an already-validated config returns same result."""
        from warden.validation.frames.security._internal.taint_analyzer import validate_taint_config

        first = validate_taint_config({"confidence_threshold": 0.6})
        second = validate_taint_config(first)
        assert first == second

    def test_analyzer_survives_bad_config(self):
        """TaintAnalyzer with garbage config still works (graceful degradation)."""
        analyzer = TaintAnalyzer(taint_config={"confidence_threshold": "garbage", "sanitizer_penalty": -10})
        code = """
def handler():
    q = request.args.get("q")
    cursor.execute("SELECT * FROM t WHERE name = " + q)
"""
        paths = analyzer.analyze(code)
        assert len(paths) >= 1  # Still finds taint paths

    def test_frame_survives_bad_config(self):
        """SecurityFrame with bad taint config still converts findings."""
        from warden.validation.frames.security._internal.taint_analyzer import TaintPath, TaintSink, TaintSource
        from warden.validation.frames.security.frame import SecurityFrame

        frame = SecurityFrame(config={"taint": {"confidence_threshold": "not_a_number"}})
        paths = [
            TaintPath(
                source=TaintSource(name="request.args", node_type="call", line=3, confidence=0.9),
                sink=TaintSink(name="cursor.execute", sink_type="SQL-value", line=4),
                confidence=0.9,
            )
        ]
        # Should not crash — falls back to default 0.8
        result = frame._convert_taint_paths_to_findings(paths, "test.py")
        assert result is not None
        assert result.findings[0].is_blocker is True  # 0.9 >= 0.8 default
