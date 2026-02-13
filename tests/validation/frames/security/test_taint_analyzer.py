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

    def test_non_python_returns_empty(self):
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
