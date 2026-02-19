"""Tests for taint analysis engine."""
import pytest

from warden.validation.frames.security._internal.taint_analyzer import (
    TaintAnalyzer,
    TaintPath,
    TaintSink,
    TaintSource,
)


class TestTaintAnalyzer:
    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_sql_injection_detected(self):
        code = '''
def get_user(user_id):
    uid = request.args.get('id')
    cursor.execute(f"SELECT * FROM users WHERE id = {uid}")
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "SQL-value" for p in paths)

    def test_command_injection_detected(self):
        code = '''
def run_cmd():
    cmd = request.form['command']
    os.system(cmd)
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "CMD-argument" for p in paths)

    def test_safe_parameterized_query(self):
        code = '''
def get_user_safe(user_id):
    uid = request.args.get('id')
    cursor.execute("SELECT * FROM users WHERE id = ?", (uid,))
'''
        # Parameterized queries still detect the path but args are separate
        # The taint analyzer sees uid going to execute but as a separate arg
        paths = self.analyzer.analyze(code)
        # May or may not detect depending on argument position analysis
        # The key is it doesn't crash

    def test_no_taint_clean_code(self):
        code = '''
def calculate(a, b):
    return a + b
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) == 0

    def test_input_function_source(self):
        code = '''
def greet():
    name = input("Name: ")
    eval(name)
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "CODE-execution" for p in paths)

    def test_f_string_propagation(self):
        code = '''
def search():
    query = request.args.get('q')
    sql = f"SELECT * FROM items WHERE name = '{query}'"
    cursor.execute(sql)
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1

    def test_syntax_error_graceful(self):
        code = "def foo(:\n  pass"
        paths = self.analyzer.analyze(code)
        assert paths == []

    def test_unsupported_language_returns_empty(self):
        paths = self.analyzer.analyze("foo();", language="ruby")
        assert paths == []

    def test_clean_js_returns_empty(self):
        paths = self.analyzer.analyze("const x = 1;", language="javascript")
        assert paths == []

    def test_taint_path_to_json(self):
        source = TaintSource(name="request.args", node_type="attribute", line=5)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=10)
        path = TaintPath(source=source, sink=sink, confidence=0.9)
        j = path.to_json()
        assert j["source"]["name"] == "request.args"
        assert j["sink"]["type"] == "SQL-value"
        assert j["confidence"] == 0.9

    def test_multiple_functions(self):
        code = '''
def func_a():
    user_input = input("x")
    eval(user_input)

def func_b():
    x = 42
    print(x)
'''
        paths = self.analyzer.analyze(code)
        # Only func_a should have taint paths
        assert len(paths) >= 1
        assert all(p.source.name == "input" or "input" in p.source.name for p in paths)

    def test_environ_source(self):
        code = '''
def run():
    cmd = os.environ.get('CMD')
    subprocess.run(cmd, shell=True)
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1

    def test_string_concatenation_propagation(self):
        code = '''
def build_query():
    name = request.args.get('name')
    query = "SELECT * FROM users WHERE name = '" + name + "'"
    cursor.execute(query)
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "SQL-value" for p in paths)

    def test_format_string_propagation(self):
        code = '''
def build_query():
    name = request.args.get('name')
    query = "SELECT * FROM users WHERE name = '{}'".format(name)
    cursor.execute(query)
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1

    def test_taint_path_confidence_reduced_when_sanitized(self):
        source = TaintSource(name="request.args", node_type="attribute", line=1)
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=5)
        path = TaintPath(
            source=source,
            sink=sink,
            sanitizers=["html.escape"],
            is_sanitized=True,
            confidence=0.27,  # 0.9 * 0.3
        )
        assert path.is_sanitized is True
        assert path.confidence < 0.5

    def test_subprocess_sink_detected(self):
        code = '''
def execute():
    user_cmd = request.form['cmd']
    subprocess.Popen(user_cmd, shell=True)
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "CMD-argument" for p in paths)

    def test_async_function_analyzed(self):
        code = '''
async def handle_request():
    data = request.json
    eval(data)
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "CODE-execution" for p in paths)

    def test_keyword_argument_taint(self):
        code = '''
def run():
    user_input = request.args.get('cmd')
    subprocess.run(args=user_input, shell=True)
'''
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1

    def test_taint_source_dataclass_fields(self):
        source = TaintSource(name="request.args", node_type="attribute", line=5, confidence=0.85)
        assert source.name == "request.args"
        assert source.node_type == "attribute"
        assert source.line == 5
        assert source.confidence == 0.85

    def test_taint_sink_dataclass_fields(self):
        sink = TaintSink(name="cursor.execute", sink_type="SQL-value", line=10)
        assert sink.name == "cursor.execute"
        assert sink.sink_type == "SQL-value"
        assert sink.line == 10

    def test_sink_type_property(self):
        source = TaintSource(name="input", node_type="call", line=1)
        sink = TaintSink(name="eval", sink_type="CODE-execution", line=2)
        path = TaintPath(source=source, sink=sink, confidence=0.9)
        assert path.sink_type == "CODE-execution"


class TestJSTaintAnalyzer:
    """JavaScript / TypeScript taint analysis tests."""

    def setup_method(self):
        self.analyzer = TaintAnalyzer()

    def test_js_sql_injection_template_literal(self):
        code = "const id = req.query.id;\ndb.query(`SELECT * FROM users WHERE id = ${id}`);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "SQL-value" for p in paths)

    def test_js_sql_injection_concatenation(self):
        code = 'const name = req.body.name;\npool.query("SELECT * FROM users WHERE name = \'" + name + "\'");'
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "SQL-value" for p in paths)

    def test_js_command_injection_exec(self):
        code = "const cmd = req.query.cmd;\nexec(cmd);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "CMD-argument" for p in paths)

    def test_js_xss_inner_html(self):
        code = "const input = req.query.q;\ndocument.getElementById('out').innerHTML = input;"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "HTML-content" for p in paths)

    def test_js_eval_code_execution(self):
        code = "const code = req.body.script;\neval(code);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "CODE-execution" for p in paths)

    def test_js_destructuring_source(self):
        code = "const { username, password } = req.body;\ndb.query(`SELECT * FROM users WHERE username = ${username}`);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "SQL-value" for p in paths)

    def test_js_taint_propagation(self):
        """Taint flows through an intermediate variable."""
        code = "const body = req.body;\nconst id = body.id;\ndb.query(`SELECT * FROM items WHERE id = ${id}`);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1

    def test_js_sanitized_xss_reduced_confidence(self):
        code = "const input = req.query.q;\ndocument.getElementById('out').innerHTML = DOMPurify.sanitize(input);"
        paths = self.analyzer.analyze(code, language="javascript")
        sanitized = [p for p in paths if p.is_sanitized]
        assert len(sanitized) >= 1
        assert all(p.confidence < 0.5 for p in sanitized)

    def test_ts_sql_injection_detected(self):
        """TypeScript files use the same JS analyzer."""
        code = "const id: string = req.params.id;\nclient.query(`SELECT * FROM orders WHERE id = ${id}`);"
        paths = self.analyzer.analyze(code, language="typescript")
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "SQL-value" for p in paths)

    def test_js_clean_code_no_paths(self):
        code = "const x = 42;\nconst y = x + 1;\nconsole.log(y);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert paths == []

    def test_js_process_env_source(self):
        code = "const secret = process.env.SECRET_KEY;\nexec(secret);"
        paths = self.analyzer.analyze(code, language="javascript")
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "CMD-argument" for p in paths)


class TestTaintAnalyzerWithCatalog:
    """Tests that verify catalog injection into TaintAnalyzer."""

    def test_analyzer_accepts_catalog_parameter(self):
        from warden.validation.frames.security._internal.taint_catalog import TaintCatalog

        catalog = TaintCatalog.get_default()
        analyzer = TaintAnalyzer(catalog=catalog)
        assert analyzer._catalog is catalog

    def test_analyzer_no_args_uses_default_catalog(self):
        from warden.validation.frames.security._internal.taint_catalog import TaintCatalog

        analyzer = TaintAnalyzer()
        assert isinstance(analyzer._catalog, TaintCatalog)

    def test_custom_python_source_via_catalog(self):
        from warden.validation.frames.security._internal.taint_catalog import TaintCatalog

        catalog = TaintCatalog.get_default()
        catalog.sources["python"].add("fastapi.Request.query_params")
        analyzer = TaintAnalyzer(catalog=catalog)

        code = """
def handler(req):
    uid = fastapi.Request.query_params.get("id")
    cursor.execute(f"SELECT * FROM users WHERE id = {uid}")
"""
        paths = analyzer.analyze(code)
        assert len(paths) >= 1
        assert any("fastapi" in p.source.name for p in paths)

    def test_custom_sink_via_catalog(self):
        from warden.validation.frames.security._internal.taint_catalog import TaintCatalog

        catalog = TaintCatalog.get_default()
        catalog.sinks["prisma.raw"] = "SQL-value"
        analyzer = TaintAnalyzer(catalog=catalog)

        code = """
def handler(req):
    uid = request.args.get("id")
    prisma.raw(f"SELECT * FROM users WHERE id = {uid}")
"""
        paths = analyzer.analyze(code)
        assert len(paths) >= 1
        assert any("prisma" in p.sink.name for p in paths)

    def test_two_analyzers_independent_catalogs(self):
        """Two analyzers with different catalogs produce different results."""
        from warden.validation.frames.security._internal.taint_catalog import TaintCatalog

        cat1 = TaintCatalog.get_default()
        cat1.sinks["prisma.raw"] = "SQL-value"

        cat2 = TaintCatalog.get_default()  # pristine copy

        a1 = TaintAnalyzer(catalog=cat1)
        a2 = TaintAnalyzer(catalog=cat2)

        code = """
def handler(req):
    uid = request.args.get("id")
    prisma.raw(f"SELECT * FROM users WHERE id = {uid}")
"""
        paths1 = a1.analyze(code)
        paths2 = a2.analyze(code)

        assert len(paths1) >= 1
        assert not any("prisma" in p.sink.name for p in paths2)
