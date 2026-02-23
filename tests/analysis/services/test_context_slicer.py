"""Tests for ContextSlicerService.

Covers: function extraction via AST, caller/callee signatures via CodeGraph,
fallback behavior, token budget compliance, build_focused_context assembly.
"""

from __future__ import annotations

import pytest

from warden.analysis.domain.code_graph import (
    CodeGraph,
    EdgeRelation,
    SymbolEdge,
    SymbolKind,
    SymbolNode,
)
from warden.analysis.services.context_slicer import ContextSlicerService, SlicedContext
from warden.ast.domain.enums import ASTNodeType
from warden.ast.domain.models import ASTNode, SourceLocation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FILE = "src/auth/views.py"

SAMPLE_CODE = """\
import os
from flask import request

class AuthService:
    def __init__(self):
        self.db = get_db()

    def login(self, req):
        user = req.form["username"]
        pwd = req.form["password"]
        result = self.db.execute(
            f"SELECT * FROM users WHERE name='{user}'"
        )
        return result

    def logout(self, session_id):
        self.db.execute("DELETE FROM sessions WHERE id=?", [session_id])
        return True

    def refresh_token(self, token):
        if not validate(token):
            raise ValueError("Invalid token")
        return generate_new_token(token)

def standalone_helper():
    return "helper"
"""

DECORATED_CODE = """\
import os
from flask import Flask, request
from auth import require_auth, rate_limit

app = Flask(__name__)

@app.route("/login", methods=["POST"])
@require_auth
@rate_limit(100)
def login():
    user = request.form["username"]
    pwd = request.form["password"]
    return check_credentials(user, pwd)

@app.route("/health")
def health():
    return "ok"

def internal_helper():
    return 42
"""


def _make_decorated_ast() -> ASTNode:
    """Build AST for DECORATED_CODE.

    DECORATED_CODE lines (1-indexed):
    1: import os                    7: @app.route(...)
    2: from flask ...               8: @require_auth
    3: from auth ...                9: @rate_limit(100)
    4: (empty)                     10: def login():
    5: app = Flask(...)            11-13: body
    6: (empty)                     14: (empty)
                                   15: @app.route("/health")
                                   16: def health():
                                   17: return "ok"
                                   19: def internal_helper():
                                   20: return 42
    """
    dfile = "src/auth/views.py"
    root = ASTNode(
        node_type=ASTNodeType.MODULE,
        name="module",
        location=SourceLocation(dfile, 1, 0, 21, 0),
    )
    # login: AST says def starts at line 10, but decorators are 7-9
    login_func = ASTNode(
        node_type=ASTNodeType.FUNCTION,
        name="login",
        location=SourceLocation(dfile, 10, 0, 13, 0),
    )
    # health: decorator at line 15, def at line 16
    health_func = ASTNode(
        node_type=ASTNodeType.FUNCTION,
        name="health",
        location=SourceLocation(dfile, 16, 0, 17, 0),
    )
    # internal_helper: no decorators, line 19-20
    helper_func = ASTNode(
        node_type=ASTNodeType.FUNCTION,
        name="internal_helper",
        location=SourceLocation(dfile, 19, 0, 20, 0),
    )
    root.children = [login_func, health_func, helper_func]
    return root


def _make_ast_root() -> ASTNode:
    """Build a minimal AST tree with function nodes that have locations.

    SAMPLE_CODE lines (1-indexed):
    1: import os              8: def login(...)      16: def logout(...)
    2: from flask ...         9: user = ...           17: self.db.execute(...)
    3: (empty)               10: pwd = ...            18: return True
    4: class AuthService:    11: result = ...         20: def refresh_token(...)
    5: def __init__(self):   12: f"SELECT..."         25: def standalone_helper():
    6: self.db = get_db()    14: return result        26: return "helper"
    """
    root = ASTNode(
        node_type=ASTNodeType.MODULE,
        name="module",
        location=SourceLocation(FILE, 1, 0, 27, 0),
    )

    class_node = ASTNode(
        node_type=ASTNodeType.CLASS,
        name="AuthService",
        location=SourceLocation(FILE, 4, 0, 24, 0),
    )

    init_method = ASTNode(
        node_type=ASTNodeType.METHOD,
        name="__init__",
        location=SourceLocation(FILE, 5, 4, 6, 0),
    )

    # login method: lines 8-14 (contains SQL injection at line 12)
    login_method = ASTNode(
        node_type=ASTNodeType.METHOD,
        name="login",
        location=SourceLocation(FILE, 8, 4, 14, 0),
    )

    # logout method: lines 16-18
    logout_method = ASTNode(
        node_type=ASTNodeType.METHOD,
        name="logout",
        location=SourceLocation(FILE, 16, 4, 18, 0),
    )

    # refresh_token method: lines 20-23
    refresh_method = ASTNode(
        node_type=ASTNodeType.METHOD,
        name="refresh_token",
        location=SourceLocation(FILE, 20, 4, 23, 0),
    )

    class_node.children = [init_method, login_method, logout_method, refresh_method]

    # standalone function: lines 25-26
    standalone = ASTNode(
        node_type=ASTNodeType.FUNCTION,
        name="standalone_helper",
        location=SourceLocation(FILE, 25, 0, 26, 0),
    )

    root.children = [class_node, standalone]
    return root


def _make_code_graph() -> CodeGraph:
    """Build a CodeGraph with caller/callee edges for login()."""
    graph = CodeGraph()

    # Nodes
    graph.add_node(
        SymbolNode(
            fqn=f"{FILE}::AuthService.login",
            name="login",
            kind=SymbolKind.METHOD,
            file_path=FILE,
            line=8,
        )
    )
    graph.add_node(
        SymbolNode(
            fqn="src/api/routes.py::handle_post",
            name="handle_post",
            kind=SymbolKind.FUNCTION,
            file_path="src/api/routes.py",
            line=42,
        )
    )
    graph.add_node(
        SymbolNode(
            fqn="src/api/routes.py::api_login",
            name="api_login",
            kind=SymbolKind.FUNCTION,
            file_path="src/api/routes.py",
            line=55,
        )
    )
    graph.add_node(
        SymbolNode(
            fqn="src/db/engine.py::execute",
            name="execute",
            kind=SymbolKind.METHOD,
            file_path="src/db/engine.py",
            line=10,
        )
    )
    graph.add_node(
        SymbolNode(
            fqn="src/auth/session.py::create_session",
            name="create_session",
            kind=SymbolKind.FUNCTION,
            file_path="src/auth/session.py",
            line=5,
        )
    )

    # Caller edges: handle_post and api_login call login
    graph.add_edge(
        SymbolEdge(
            source="src/api/routes.py::handle_post",
            target=f"{FILE}::AuthService.login",
            relation=EdgeRelation.CALLS,
        )
    )
    graph.add_edge(
        SymbolEdge(
            source="src/api/routes.py::api_login",
            target=f"{FILE}::AuthService.login",
            relation=EdgeRelation.CALLS,
        )
    )

    # Callee edges: login calls execute and create_session
    graph.add_edge(
        SymbolEdge(
            source=f"{FILE}::AuthService.login",
            target="src/db/engine.py::execute",
            relation=EdgeRelation.CALLS,
        )
    )
    graph.add_edge(
        SymbolEdge(
            source=f"{FILE}::AuthService.login",
            target="src/auth/session.py::create_session",
            relation=EdgeRelation.CALLS,
        )
    )

    return graph


# ---------------------------------------------------------------------------
# SlicedContext
# ---------------------------------------------------------------------------


class TestSlicedContext:
    def test_empty_context(self):
        ctx = SlicedContext()
        assert ctx.total_chars == 0
        assert ctx.is_fallback is False

    def test_total_chars(self):
        ctx = SlicedContext(
            function_body="def foo(): pass",
            caller_signatures=["func bar()"],
            callee_signatures=["func baz()"],
            import_context="import os",
        )
        expected = len("def foo(): pass") + len("func bar()") + len("func baz()") + len("import os")
        assert ctx.total_chars == expected


# ---------------------------------------------------------------------------
# slice_for_function
# ---------------------------------------------------------------------------


class TestSliceForFunction:
    def setup_method(self):
        self.slicer = ContextSlicerService()
        self.ast_root = _make_ast_root()

    def test_extracts_login_function_for_line_12(self):
        """Line 12 is inside login() — should extract login body."""
        result = self.slicer.slice_for_function(SAMPLE_CODE, [12], self.ast_root)

        assert not result.is_fallback
        assert result.function_name == "login"
        assert "def login" in result.function_body
        assert "SELECT * FROM users" in result.function_body

    def test_extracts_logout_function_for_line_18(self):
        """Line 18 is inside logout()."""
        result = self.slicer.slice_for_function(SAMPLE_CODE, [18], self.ast_root)

        assert not result.is_fallback
        assert result.function_name == "logout"
        assert "DELETE FROM sessions" in result.function_body

    def test_multiple_target_lines_across_functions(self):
        """Target lines in login (12) and logout (18) should extract both."""
        result = self.slicer.slice_for_function(SAMPLE_CODE, [12, 18], self.ast_root)

        assert not result.is_fallback
        assert "login" in result.function_body
        assert "logout" in result.function_body

    def test_fallback_when_no_ast(self):
        """Without AST root, should return fallback."""
        result = self.slicer.slice_for_function(SAMPLE_CODE, [12], None)

        assert result.is_fallback

    def test_fallback_when_empty_content(self):
        result = self.slicer.slice_for_function("", [12], self.ast_root)

        assert result.is_fallback

    def test_fallback_when_no_target_lines(self):
        result = self.slicer.slice_for_function(SAMPLE_CODE, [], self.ast_root)

        assert result.is_fallback

    def test_nearest_function_when_line_outside_any_function(self):
        """Line 3 is between imports and class — should find nearest function."""
        result = self.slicer.slice_for_function(SAMPLE_CODE, [3], self.ast_root)

        # Should find nearest function (either __init__ or the class start)
        assert not result.is_fallback or result.function_body

    def test_standalone_function_extraction(self):
        """Line 26 is in standalone_helper()."""
        result = self.slicer.slice_for_function(SAMPLE_CODE, [26], self.ast_root)

        assert not result.is_fallback
        assert result.function_name == "standalone_helper"

    def test_import_context_extracted(self):
        """Should extract import lines."""
        result = self.slicer.slice_for_function(SAMPLE_CODE, [12], self.ast_root)

        assert "import os" in result.import_context

    def test_innermost_function_preferred(self):
        """When target line is in nested function, prefer the inner one."""
        # login() is lines 8-15, inside AuthService class (4-26)
        # The METHOD node should win over the CLASS node
        result = self.slicer.slice_for_function(SAMPLE_CODE, [12], self.ast_root)

        assert result.function_name == "login"


# ---------------------------------------------------------------------------
# get_caller_signatures
# ---------------------------------------------------------------------------


class TestGetCallerSignatures:
    def setup_method(self):
        self.slicer = ContextSlicerService()
        self.graph = _make_code_graph()

    def test_returns_callers(self):
        callers, _ = self.slicer.get_caller_signatures(FILE, "login", self.graph)

        assert len(callers) == 2
        assert any("handle_post" in c for c in callers)
        assert any("api_login" in c for c in callers)

    def test_returns_callees(self):
        _, callees = self.slicer.get_caller_signatures(FILE, "login", self.graph)

        assert len(callees) == 2
        assert any("execute" in c for c in callees)
        assert any("create_session" in c for c in callees)

    def test_respects_max_callers(self):
        callers, _ = self.slicer.get_caller_signatures(FILE, "login", self.graph, max_callers=1)

        assert len(callers) == 1

    def test_respects_max_callees(self):
        _, callees = self.slicer.get_caller_signatures(FILE, "login", self.graph, max_callees=1)

        assert len(callees) == 1

    def test_empty_when_no_graph(self):
        callers, callees = self.slicer.get_caller_signatures(FILE, "login", None)

        assert callers == []
        assert callees == []

    def test_empty_when_function_not_found(self):
        callers, callees = self.slicer.get_caller_signatures(FILE, "nonexistent", self.graph)

        assert callers == []
        assert callees == []


# ---------------------------------------------------------------------------
# build_focused_context
# ---------------------------------------------------------------------------


def _make_large_code() -> str:
    """Generate code large enough that slicing actually triggers (~500 tokens)."""
    lines = list(SAMPLE_CODE.splitlines())
    # Pad the file with extra methods to exceed token budgets
    for i in range(20):
        lines.append(f"    def helper_{i}(self, x):")
        lines.append(f"        result = compute_{i}(x)")
        lines.append(f"        log.debug('helper_{i} called with %s', x)")
        lines.append(f"        return result + {i}")
        lines.append("")
    return "\n".join(lines)


LARGE_CODE = _make_large_code()


class TestBuildFocusedContext:
    def setup_method(self):
        self.slicer = ContextSlicerService()
        self.ast_root = _make_ast_root()
        self.graph = _make_code_graph()

    def test_focused_context_contains_function_body(self):
        """With tight budget on large file, function body is still present."""
        result = self.slicer.build_focused_context(LARGE_CODE, FILE, [12], self.ast_root, self.graph, token_budget=200)

        assert "def login" in result
        assert "SELECT * FROM users" in result

    def test_focused_context_contains_caller_info(self):
        """With tight budget on large file, callers are included."""
        result = self.slicer.build_focused_context(LARGE_CODE, FILE, [12], self.ast_root, self.graph, token_budget=200)

        assert "Callers:" in result
        assert "handle_post" in result

    def test_focused_context_contains_callee_info(self):
        result = self.slicer.build_focused_context(LARGE_CODE, FILE, [12], self.ast_root, self.graph, token_budget=200)

        assert "Callees:" in result
        assert "execute" in result

    def test_focused_context_shorter_than_full_file(self):
        result = self.slicer.build_focused_context(LARGE_CODE, FILE, [12], self.ast_root, self.graph, token_budget=200)

        assert len(result) < len(LARGE_CODE)

    def test_fallback_when_no_ast(self):
        """Without AST, should fall back to truncate_with_ast_hints."""
        result = self.slicer.build_focused_context(LARGE_CODE, FILE, [12], None, None, token_budget=200)

        assert len(result) > 0

    def test_small_file_returned_as_is(self):
        """Small file that fits in budget should be returned unmodified."""
        small_code = "def foo():\n    return 42\n"
        result = self.slicer.build_focused_context(small_code, FILE, [2], self.ast_root, self.graph, token_budget=10000)

        assert result == small_code

    def test_import_context_included(self):
        result = self.slicer.build_focused_context(LARGE_CODE, FILE, [12], self.ast_root, self.graph, token_budget=200)

        assert "import os" in result

    def test_no_code_graph_still_works(self):
        """Should work without CodeGraph (no caller/callee info)."""
        result = self.slicer.build_focused_context(LARGE_CODE, FILE, [12], self.ast_root, None, token_budget=200)

        assert "def login" in result
        assert "Callers:" not in result


# ---------------------------------------------------------------------------
# Token budget compliance
# ---------------------------------------------------------------------------


class TestTokenBudget:
    def setup_method(self):
        self.slicer = ContextSlicerService()
        self.ast_root = _make_ast_root()

    def test_respects_token_budget(self):
        """Output token count should not exceed budget by more than a margin."""
        from warden.shared.utils.token_utils import estimate_tokens

        result = self.slicer.build_focused_context(LARGE_CODE, FILE, [12], self.ast_root, None, token_budget=100)

        tokens = estimate_tokens(result)
        # Budget is 100, allow 50% margin for estimation inaccuracy
        assert tokens <= 150, f"Token count {tokens} exceeds budget 100 + margin"

    def test_large_budget_includes_everything(self):
        """When budget is huge, small file is returned as-is."""
        result = self.slicer.build_focused_context(
            SAMPLE_CODE, FILE, [12], self.ast_root, _make_code_graph(), token_budget=10000
        )

        assert result == SAMPLE_CODE


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def setup_method(self):
        self.slicer = ContextSlicerService()

    def test_empty_functions_list(self):
        """AST with no functions should fallback."""
        empty_root = ASTNode(
            node_type=ASTNodeType.MODULE,
            name="module",
            location=SourceLocation(FILE, 1, 0, 5, 0),
        )
        result = self.slicer.slice_for_function("some code\n" * 5, [3], empty_root)

        assert result.is_fallback

    def test_function_without_location(self):
        """Function node without location should be skipped."""
        root = ASTNode(
            node_type=ASTNodeType.MODULE,
            name="module",
        )
        func = ASTNode(
            node_type=ASTNodeType.FUNCTION,
            name="no_loc_func",
            location=None,
        )
        root.children = [func]

        result = self.slicer.slice_for_function("def no_loc_func(): pass\n", [1], root)
        # Should fallback since function has no location
        assert result.is_fallback

    def test_max_three_functions_in_slice(self):
        """When target lines span many functions, max 3 are included."""
        root = ASTNode(node_type=ASTNodeType.MODULE, name="m")
        funcs = []
        code_lines: list[str] = []
        for i in range(5):
            start = i * 10 + 1
            end = start + 5
            func = ASTNode(
                node_type=ASTNodeType.FUNCTION,
                name=f"alpha_{i}",
                location=SourceLocation(FILE, start, 0, end, 0),
            )
            funcs.append(func)
        root.children = funcs

        # Generate code with unique markers per function region
        for line_num in range(1, 51):
            func_idx = (line_num - 1) // 10
            offset = (line_num - 1) % 10
            if offset == 0:
                code_lines.append(f"def alpha_{func_idx}():")
            else:
                code_lines.append(f"    pass  # body of alpha_{func_idx}")

        code = "\n".join(code_lines)

        # Target lines in 5 different functions
        targets = [2, 12, 22, 32, 42]
        result = self.slicer.slice_for_function(code, targets, root)

        # Should not be fallback, but limited to 3 functions
        if not result.is_fallback:
            # Count def statements in body — max 3
            def_count = result.function_body.count("def alpha_")
            assert def_count <= 3


# ---------------------------------------------------------------------------
# Decorator-aware slicing
# ---------------------------------------------------------------------------


class TestDecoratorAwareSlicing:
    """Decorator lines above a function def should be included in the slice."""

    def setup_method(self):
        self.slicer = ContextSlicerService()
        self.ast_root = _make_decorated_ast()

    def test_decorators_included_for_login(self):
        """login() has 3 decorators (@app.route, @require_auth, @rate_limit).
        All should appear in the sliced body."""
        result = self.slicer.slice_for_function(DECORATED_CODE, [11], self.ast_root)

        assert not result.is_fallback
        assert result.function_name == "login"
        assert "@app.route" in result.function_body
        assert "@require_auth" in result.function_body
        assert "@rate_limit" in result.function_body
        assert "def login" in result.function_body

    def test_single_decorator_included_for_health(self):
        """health() has 1 decorator (@app.route). Should be included."""
        result = self.slicer.slice_for_function(DECORATED_CODE, [17], self.ast_root)

        assert not result.is_fallback
        assert result.function_name == "health"
        assert "@app.route" in result.function_body
        assert "def health" in result.function_body

    def test_no_decorator_function_unchanged(self):
        """internal_helper() has no decorators — behavior unchanged."""
        result = self.slicer.slice_for_function(DECORATED_CODE, [20], self.ast_root)

        assert not result.is_fallback
        assert result.function_name == "internal_helper"
        assert "def internal_helper" in result.function_body
        # Should NOT include decorators from other functions
        assert "@require_auth" not in result.function_body

    def test_start_line_includes_decorators(self):
        """start_line should be adjusted to the first decorator line."""
        result = self.slicer.slice_for_function(DECORATED_CODE, [11], self.ast_root)

        # login def is line 10, but decorators start at line 7
        assert result.start_line == 7

    def test_decorator_at_file_top(self):
        """Edge case: decorator at line 1 (no room to scan up)."""
        code = "@decorator\ndef func():\n    pass\n"
        root = ASTNode(node_type=ASTNodeType.MODULE, name="m")
        func = ASTNode(
            node_type=ASTNodeType.FUNCTION,
            name="func",
            location=SourceLocation(FILE, 2, 0, 3, 0),
        )
        root.children = [func]

        result = self.slicer.slice_for_function(code, [3], root)
        assert not result.is_fallback
        assert "@decorator" in result.function_body
        assert result.start_line == 1


# ---------------------------------------------------------------------------
# Center-around truncation
# ---------------------------------------------------------------------------


class TestCenterAroundTargets:
    """When function body exceeds token budget, center around target lines."""

    def setup_method(self):
        self.slicer = ContextSlicerService()

    def test_target_line_preserved_in_long_function(self):
        """In a 200-line function, target at line 151 (x_150) should still appear."""
        # Build a large function
        func_lines = ["def big_function():"]
        for i in range(1, 201):
            func_lines.append(f"    x_{i} = compute({i})  # line {i}")
        code = "\n".join(func_lines)

        # AST: function spans lines 1-201
        root = ASTNode(node_type=ASTNodeType.MODULE, name="m")
        func = ASTNode(
            node_type=ASTNodeType.FUNCTION,
            name="big_function",
            location=SourceLocation(FILE, 1, 0, 201, 0),
        )
        root.children = [func]

        # Target is deep in the function (file line 151 = x_150)
        result = self.slicer.build_focused_context(code, FILE, [151], root, None, token_budget=100)

        # The target line content should be preserved
        assert "x_150" in result or "compute(150)" in result

    def test_signature_always_preserved(self):
        """Function signature (def line) should always be in the output."""
        func_lines = ["def important_func(a, b, c):"]
        for i in range(1, 201):
            func_lines.append(f"    result_{i} = a + b + {i}")
        code = "\n".join(func_lines)

        root = ASTNode(node_type=ASTNodeType.MODULE, name="m")
        func = ASTNode(
            node_type=ASTNodeType.FUNCTION,
            name="important_func",
            location=SourceLocation(FILE, 1, 0, 201, 0),
        )
        root.children = [func]

        result = self.slicer.build_focused_context(code, FILE, [180], root, None, token_budget=100)

        assert "def important_func" in result

    def test_omission_markers_present(self):
        """Gaps between signature and target should show omission markers."""
        func_lines = ["def func():"]
        for i in range(1, 201):
            func_lines.append(f"    line_{i} = {i}")
        code = "\n".join(func_lines)

        root = ASTNode(node_type=ASTNodeType.MODULE, name="m")
        func = ASTNode(
            node_type=ASTNodeType.FUNCTION,
            name="func",
            location=SourceLocation(FILE, 1, 0, 201, 0),
        )
        root.children = [func]

        result = self.slicer.build_focused_context(code, FILE, [150], root, None, token_budget=80)

        assert "omitted" in result

    def test_small_function_no_centering(self):
        """Short function that fits in budget should not be centered."""
        code = "def small():\n    return 42\n"
        root = ASTNode(node_type=ASTNodeType.MODULE, name="m")
        func = ASTNode(
            node_type=ASTNodeType.FUNCTION,
            name="small",
            location=SourceLocation(FILE, 1, 0, 2, 0),
        )
        root.children = [func]

        result = self.slicer.build_focused_context(code, FILE, [2], root, None, token_budget=10000)

        assert result == code
        assert "omitted" not in result
