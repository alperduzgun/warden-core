"""Tests for interprocedural taint tracking (#74) and multi-label taint (#75).

Issue #74: Interprocedural (cross-function) taint tracking within a single file.
Issue #75: Multi-label taint tracking with per-sink-type sanitization.
"""

import pytest

from warden.validation.frames.security._internal.taint_analyzer import (
    ALL_SINK_TYPES,
    TaintAnalyzer,
    TaintPath,
    TaintSink,
    TaintSource,
)


# ═══════════════════════════════════════════════════════════════════════════
# Issue #75: Multi-label taint tracking
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiLabelTaintPath:
    """TaintPath multi-label dataclass behavior."""

    def test_default_taint_labels_include_sink_type(self):
        """When no explicit labels, the sink type is the active label."""
        source = TaintSource(name="request.args", node_type="attribute", line=1)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=5)
        path = TaintPath(source=source, sink=sink, confidence=0.9)
        assert "SQL-value" in path.taint_labels
        assert path.is_sanitized is False

    def test_explicit_empty_labels_means_sanitized(self):
        """Explicit empty taint_labels means fully sanitized."""
        source = TaintSource(name="request.args", node_type="attribute", line=1)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=5)
        path = TaintPath(source=source, sink=sink, taint_labels=set(), confidence=0.9)
        assert path.is_sanitized is True

    def test_is_sanitized_legacy_override_true(self):
        """Legacy is_sanitized=True still works."""
        source = TaintSource(name="request.args", node_type="attribute", line=1)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=5)
        path = TaintPath(
            source=source, sink=sink, is_sanitized=True, confidence=0.27
        )
        assert path.is_sanitized is True
        # Legacy override -> empty label set
        assert len(path.taint_labels) == 0

    def test_is_sanitized_legacy_override_false(self):
        """Legacy is_sanitized=False still works."""
        source = TaintSource(name="request.args", node_type="attribute", line=1)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=5)
        path = TaintPath(
            source=source, sink=sink, is_sanitized=False, confidence=0.9
        )
        assert path.is_sanitized is False
        # Sink type should be in the label set
        assert "SQL-value" in path.taint_labels

    def test_taint_labels_with_multiple_types(self):
        """A variable can carry multiple sink-type labels."""
        source = TaintSource(name="request.args", node_type="attribute", line=1)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=5)
        path = TaintPath(
            source=source,
            sink=sink,
            taint_labels={"SQL-value", "HTML-content", "CMD-argument"},
            confidence=0.9,
        )
        assert "SQL-value" in path.taint_labels
        assert "HTML-content" in path.taint_labels
        assert path.is_sanitized is False

    def test_removing_sink_type_from_labels_makes_sanitized(self):
        """Removing the sink's own type from labels marks it as sanitized."""
        source = TaintSource(name="request.args", node_type="attribute", line=1)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=5)
        # All labels except SQL-value
        path = TaintPath(
            source=source,
            sink=sink,
            taint_labels={"HTML-content", "CMD-argument"},
            confidence=0.9,
        )
        assert path.is_sanitized is True

    def test_to_json_includes_taint_labels(self):
        """to_json output includes sorted taint_labels."""
        source = TaintSource(name="request.args", node_type="attribute", line=1)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=5)
        path = TaintPath(
            source=source,
            sink=sink,
            taint_labels={"SQL-value", "HTML-content"},
            confidence=0.9,
        )
        j = path.to_json()
        assert "taint_labels" in j
        assert j["taint_labels"] == ["HTML-content", "SQL-value"]

    def test_taint_source_carries_labels(self):
        """TaintSource dataclass carries taint_labels."""
        src = TaintSource(
            name="request.args",
            node_type="attribute",
            line=1,
            taint_labels={"SQL-value", "CMD-argument"},
        )
        assert "SQL-value" in src.taint_labels
        assert "CMD-argument" in src.taint_labels

    def test_taint_source_default_labels_empty(self):
        """TaintSource default taint_labels is empty set."""
        src = TaintSource(name="request.args", node_type="attribute", line=1)
        assert src.taint_labels == set()


class TestMultiLabelAnalysis:
    """Integration: multi-label analysis detects label-aware paths."""

    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_html_sanitizer_removes_html_label_only(self):
        """html.escape removes HTML-content but not SQL-value label."""
        code = '''
def handler():
    user_input = request.args.get('q')
    safe_html = html.escape(user_input)
    render_template_string(safe_html)
'''
        paths = self.analyzer.analyze(code)
        # The path to render_template_string should be sanitized for HTML-content
        html_paths = [p for p in paths if p.sink.sink_type == "HTML-content"]
        assert len(html_paths) >= 1
        assert all(p.is_sanitized for p in html_paths)

    def test_unsanitized_flow_has_all_labels(self):
        """Unsanitized taint path carries ALL_SINK_TYPES labels."""
        code = '''
def handler():
    user_input = request.args.get('q')
    eval(user_input)
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1
        # The CODE-execution path should not be sanitized
        code_paths = [p for p in paths if p.sink.sink_type == "CODE-execution"]
        assert len(code_paths) >= 1
        for p in code_paths:
            assert not p.is_sanitized
            # Should still have the CODE-execution label active
            assert "CODE-execution" in p.taint_labels

    def test_sanitizer_specific_to_sink_type(self):
        """Sanitizer for one type does not remove labels for a different type."""
        code = '''
def handler():
    user_input = request.args.get('q')
    safe = html.escape(user_input)
    cursor.execute(f"SELECT * FROM t WHERE x = {safe}")
'''
        paths = self.analyzer.analyze(code)
        sql_paths = [p for p in paths if p.sink.sink_type == "SQL-value"]
        # SQL-value label should still be active even though html.escape was applied
        assert len(sql_paths) >= 1
        for p in sql_paths:
            assert not p.is_sanitized


# ═══════════════════════════════════════════════════════════════════════════
# Issue #74: Interprocedural (cross-function) taint tracking
# ═══════════════════════════════════════════════════════════════════════════


class TestInterproceduralTaintTracking:
    """Cross-function taint propagation within a single file."""

    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_taint_through_function_call_argument(self):
        """Taint flows from caller arg to callee param."""
        code = '''
def process_query(q):
    cursor.execute(f"SELECT * FROM t WHERE x = {q}")

def handler():
    user_input = request.args.get('q')
    process_query(user_input)
'''
        paths = self.analyzer.analyze(code)
        sql_paths = [p for p in paths if p.sink.sink_type == "SQL-value"]
        assert len(sql_paths) >= 1

    def test_taint_through_return_value(self):
        """Taint flows back from callee return to caller."""
        code = '''
def get_user_input():
    return request.args.get('q')

def handler():
    data = get_user_input()
    cursor.execute(f"SELECT * FROM t WHERE x = {data}")
'''
        paths = self.analyzer.analyze(code)
        sql_paths = [p for p in paths if p.sink.sink_type == "SQL-value"]
        assert len(sql_paths) >= 1

    def test_taint_through_chain_of_functions(self):
        """Taint flows through a chain: A -> B -> sink."""
        code = '''
def get_input():
    return request.args.get('q')

def transform(val):
    return val.upper()

def handler():
    raw = get_input()
    processed = transform(raw)
    eval(processed)
'''
        paths = self.analyzer.analyze(code)
        code_paths = [p for p in paths if p.sink.sink_type == "CODE-execution"]
        assert len(code_paths) >= 1

    def test_no_interprocedural_taint_when_clean(self):
        """No false positives when functions don't handle tainted data."""
        code = '''
def compute(a, b):
    return a + b

def handler():
    result = compute(1, 2)
    print(result)
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) == 0

    def test_taint_argument_propagation_multiple_params(self):
        """Only the tainted argument position propagates taint."""
        code = '''
def process(safe_val, dangerous_val):
    cursor.execute(f"SELECT * FROM t WHERE x = {dangerous_val}")

def handler():
    clean = "safe"
    dirty = request.args.get('q')
    process(clean, dirty)
'''
        paths = self.analyzer.analyze(code)
        sql_paths = [p for p in paths if p.sink.sink_type == "SQL-value"]
        assert len(sql_paths) >= 1

    def test_interprocedural_with_cmd_injection(self):
        """Cross-function command injection detection."""
        code = '''
def run_command(cmd):
    os.system(cmd)

def handle_request():
    user_cmd = request.form['cmd']
    run_command(user_cmd)
'''
        paths = self.analyzer.analyze(code)
        cmd_paths = [p for p in paths if p.sink.sink_type == "CMD-argument"]
        assert len(cmd_paths) >= 1

    def test_self_param_excluded_from_taint_propagation(self):
        """'self' and 'cls' parameters are not tracked for taint."""
        code = '''
class Handler:
    def process(self, query):
        cursor.execute(f"SELECT * FROM t WHERE x = {query}")

    def handle(self):
        user_input = request.args.get('q')
        self.process(user_input)
'''
        paths = self.analyzer.analyze(code)
        # Should still detect the taint flow (self is excluded from param tracking)
        sql_paths = [p for p in paths if p.sink.sink_type == "SQL-value"]
        assert len(sql_paths) >= 1

    def test_function_return_taint_labels_preserved(self):
        """Return value taint labels are preserved through interprocedural flow."""
        code = '''
def get_user_input():
    return request.args.get('q')

def handler():
    data = get_user_input()
    eval(data)
'''
        paths = self.analyzer.analyze(code)
        code_paths = [p for p in paths if p.sink.sink_type == "CODE-execution"]
        assert len(code_paths) >= 1
        for p in code_paths:
            assert not p.is_sanitized


class TestInterproceduralWithMultiLabel:
    """Combined interprocedural + multi-label behavior."""

    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_sanitized_return_preserves_non_sanitized_labels(self):
        """A function that sanitizes for HTML but returns to SQL sink is still tainted."""
        code = '''
def sanitize_for_html(val):
    return html.escape(val)

def handler():
    user_input = request.args.get('q')
    safe_html = sanitize_for_html(user_input)
    cursor.execute(f"SELECT * FROM t WHERE x = {safe_html}")
'''
        paths = self.analyzer.analyze(code)
        sql_paths = [p for p in paths if p.sink.sink_type == "SQL-value"]
        # SQL path should still be detected (html.escape does not sanitize SQL)
        assert len(sql_paths) >= 1
        for p in sql_paths:
            assert not p.is_sanitized

    def test_multiple_sinks_different_label_state(self):
        """Same variable reaching different sinks with different sanitization states."""
        code = '''
def handler():
    user_input = request.args.get('q')
    safe_html = html.escape(user_input)
    render_template_string(safe_html)
    cursor.execute(f"SELECT * FROM t WHERE x = {user_input}")
'''
        paths = self.analyzer.analyze(code)
        html_paths = [p for p in paths if p.sink.sink_type == "HTML-content"]
        sql_paths = [p for p in paths if p.sink.sink_type == "SQL-value"]

        # HTML path is sanitized by html.escape
        assert len(html_paths) >= 1
        assert all(p.is_sanitized for p in html_paths)

        # SQL path is NOT sanitized (different sink type)
        assert len(sql_paths) >= 1
        assert all(not p.is_sanitized for p in sql_paths)


class TestBackwardCompatibility:
    """Ensure the multi-label changes do not break existing API contracts."""

    def test_legacy_is_sanitized_true(self):
        """Legacy construction with is_sanitized=True."""
        source = TaintSource(name="request.args", node_type="attribute", line=1)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=5)
        path = TaintPath(
            source=source,
            sink=sink,
            sanitizers=["html.escape"],
            is_sanitized=True,
            confidence=0.27,
        )
        assert path.is_sanitized is True
        assert path.confidence < 0.5

    def test_legacy_is_sanitized_false(self):
        """Legacy construction with is_sanitized=False."""
        source = TaintSource(name="request.args", node_type="attribute", line=1)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=5)
        path = TaintPath(
            source=source,
            sink=sink,
            is_sanitized=False,
            confidence=0.9,
        )
        assert path.is_sanitized is False

    def test_legacy_default_is_not_sanitized(self):
        """Default construction (no is_sanitized) is not sanitized."""
        source = TaintSource(name="request.args", node_type="attribute", line=1)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=5)
        path = TaintPath(source=source, sink=sink, confidence=0.9)
        assert path.is_sanitized is False

    def test_sink_type_property_still_works(self):
        """The sink_type property on TaintPath still works."""
        source = TaintSource(name="input", node_type="call", line=1)
        sink = TaintSink(name="eval", sink_type="CODE-execution", line=2)
        path = TaintPath(source=source, sink=sink, confidence=0.9)
        assert path.sink_type == "CODE-execution"

    def test_to_json_backward_compatible(self):
        """to_json still has all legacy keys."""
        source = TaintSource(name="request.args", node_type="attribute", line=5)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=10)
        path = TaintPath(source=source, sink=sink, confidence=0.9)
        j = path.to_json()
        assert "source" in j
        assert "sink" in j
        assert "transformations" in j
        assert "sanitizers" in j
        assert "is_sanitized" in j
        assert "confidence" in j
        # New field also present
        assert "taint_labels" in j

    def test_existing_sql_injection_still_detected(self):
        """Regression: basic SQL injection detection unchanged."""
        analyzer = TaintAnalyzer()
        code = '''
def get_user(user_id):
    uid = request.args.get('id')
    cursor.execute(f"SELECT * FROM users WHERE id = {uid}")
'''
        paths = analyzer.analyze(code)
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "SQL-value" for p in paths)

    def test_existing_cmd_injection_still_detected(self):
        """Regression: basic command injection detection unchanged."""
        analyzer = TaintAnalyzer()
        code = '''
def run_cmd():
    cmd = request.form['command']
    os.system(cmd)
'''
        paths = analyzer.analyze(code)
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "CMD-argument" for p in paths)

    def test_existing_eval_injection_still_detected(self):
        """Regression: eval injection detection unchanged."""
        analyzer = TaintAnalyzer()
        code = '''
def greet():
    name = input("Name: ")
    eval(name)
'''
        paths = analyzer.analyze(code)
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "CODE-execution" for p in paths)

    def test_existing_clean_code_still_clean(self):
        """Regression: clean code produces no paths."""
        analyzer = TaintAnalyzer()
        code = '''
def calculate(a, b):
    return a + b
'''
        paths = analyzer.analyze(code)
        assert len(paths) == 0

    def test_existing_js_analysis_unchanged(self):
        """Regression: JS taint analysis still works."""
        analyzer = TaintAnalyzer()
        code = "const id = req.query.id;\ndb.query(`SELECT * FROM users WHERE id = ${id}`);"
        paths = analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "SQL-value" for p in paths)
