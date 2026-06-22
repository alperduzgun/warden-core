"""
Tests for the Layer-A deterministic intent classifier (#690).

Covers role assignment (decorators / path / naming / class suffix / kind
fallback), docstring-head summaries, fan-in centrality + public_api, the
GraphStore intent persistence methods, and the end-to-end
``warden graph build`` population (extract → resolve → fan-in → classify).
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from warden.analysis.domain.code_graph import (
    CodeGraph,
    EdgeRelation,
    SymbolEdge,
    SymbolKind,
    SymbolNode,
)
from warden.analysis.services.code_graph_builder import write_graph_to_store
from warden.analysis.services.graph_store_factory import default_db_path, get_graph_store
from warden.analysis.services.intent_classifier import (
    PUBLIC_API_FANIN_THRESHOLD,
    build_intents,
    classify_role,
    extract_symbol_facts,
    populate_symbol_intent,
)
from warden.cli.commands.graph import graph_app


def _node(fqn, name, kind, file_path, **kw) -> SymbolNode:
    return SymbolNode(fqn=fqn, name=name, kind=kind, file_path=file_path, **kw)


class TestClassifyRole:
    def test_test_function(self):
        n = _node("tests/test_a.py::test_foo", "test_foo", SymbolKind.FUNCTION, "tests/test_a.py", is_test=True)
        assert classify_role(n) == "test"

    def test_typer_command_decorator(self):
        n = _node("cli.py::build", "build", SymbolKind.FUNCTION, "cli.py", metadata={"decorators": ["app.command()"]})
        assert classify_role(n) == "cli_command"

    def test_api_endpoint_decorator(self):
        n = _node("api.py::list_users", "list_users", SymbolKind.FUNCTION, "api.py",
                  metadata={"decorators": ["router.get('/users')"]})
        assert classify_role(n) == "api_endpoint"

    def test_pydantic_model_base(self):
        n = _node("models.py::User", "User", SymbolKind.CLASS, "models.py", bases=["BaseModel"])
        assert classify_role(n) == "data_model"

    def test_dataclass_decorator(self):
        n = _node("m.py::Point", "Point", SymbolKind.CLASS, "m.py", metadata={"decorators": ["dataclass"]})
        assert classify_role(n) == "data_model"

    def test_exception_class_suffix(self):
        n = _node("e.py::ParseError", "ParseError", SymbolKind.CLASS, "e.py")
        assert classify_role(n) == "exception"

    def test_service_class_suffix(self):
        n = _node("s.py::PaymentService", "PaymentService", SymbolKind.CLASS, "s.py")
        assert classify_role(n) == "service"

    def test_naming_lexicon_accessor(self):
        n = _node("u.py::get_user", "get_user", SymbolKind.FUNCTION, "u.py")
        assert classify_role(n) == "accessor"

    def test_naming_lexicon_validator(self):
        n = _node("u.py::validate_email", "validate_email", SymbolKind.FUNCTION, "u.py")
        assert classify_role(n) == "validator"

    def test_dunder(self):
        n = _node("u.py::C.__init__", "__init__", SymbolKind.METHOD, "u.py")
        assert classify_role(n) == "dunder"

    def test_kind_fallback_assigns_everything(self):
        # An ordinary class with no signal still gets a (generic) role.
        n = _node("u.py::Widget", "Widget", SymbolKind.CLASS, "u.py")
        assert classify_role(n) == "class"


class TestCentralityAndPublicApi:
    def test_high_fan_in_is_public_api(self):
        g = CodeGraph()
        g.add_node(_node("core.py::Base", "Base", SymbolKind.CLASS, "core.py"))
        for i in range(PUBLIC_API_FANIN_THRESHOLD):
            g.add_node(_node(f"u{i}.py::C", f"User{i}", SymbolKind.CLASS, f"u{i}.py"))
            g.add_edge(SymbolEdge(source=f"u{i}.py::C", target="Base", relation=EdgeRelation.INHERITS))
        # fan-in keyed by short name "Base" (unresolved target), unique in graph.
        fan_in = {"Base": PUBLIC_API_FANIN_THRESHOLD}
        intents = {i.fqn: i for i in build_intents(g, fan_in)}
        base = intents["core.py::Base"]
        assert base.centrality == PUBLIC_API_FANIN_THRESHOLD
        assert base.public_api is True

    def test_private_name_not_public_even_with_fan_in(self):
        g = CodeGraph()
        g.add_node(_node("u.py::_helper", "_helper", SymbolKind.FUNCTION, "u.py"))
        intents = build_intents(g, {"_helper": 99})
        assert intents[0].public_api is False

    def test_ambiguous_name_fan_in_not_attributed(self):
        # Two symbols share the name "run" → name-based fan-in is NOT credited.
        g = CodeGraph()
        g.add_node(_node("a.py::A.run", "run", SymbolKind.METHOD, "a.py"))
        g.add_node(_node("b.py::B.run", "run", SymbolKind.METHOD, "b.py"))
        intents = {i.fqn: i for i in build_intents(g, {"run": 50})}
        assert intents["a.py::A.run"].centrality == 0
        assert intents["b.py::B.run"].centrality == 0

    def test_source_is_deterministic(self):
        g = CodeGraph()
        g.add_node(_node("u.py::f", "f", SymbolKind.FUNCTION, "u.py"))
        assert build_intents(g, {})[0].source == "deterministic"


class TestSymbolFacts:
    def test_extracts_docstring_head_and_decorators(self, tmp_path: Path):
        src = (
            'class User:\n'
            '    """Represents a user account.\n\n    More detail here.\n    """\n'
            '    @property\n'
            '    def save(self):\n'
            '        """Persist the user."""\n'
            '        pass\n'
        )
        abs_path = tmp_path / "models.py"
        abs_path.write_text(src, encoding="utf-8")
        facts = extract_symbol_facts({str(abs_path): src}, tmp_path)
        assert facts["models.py::User"]["summary"] == "Represents a user account."
        assert facts["models.py::User.save"]["summary"] == "Persist the user."
        assert facts["models.py::User.save"]["decorators"] == ["property"]

    def test_unparses_call_decorator(self, tmp_path: Path):
        src = 'import typer\napp = typer.Typer()\n\n\n@app.command()\ndef serve():\n    pass\n'
        abs_path = tmp_path / "cli.py"
        abs_path.write_text(src, encoding="utf-8")
        facts = extract_symbol_facts({str(abs_path): src}, tmp_path)
        assert facts["cli.py::serve"]["decorators"] == ["app.command()"]


class TestStoreIntentMethods:
    def _populated_store(self):
        g = CodeGraph()
        g.add_node(_node("core.py::Base", "Base", SymbolKind.CLASS, "core.py"))
        g.add_node(_node("u.py::User", "User", SymbolKind.CLASS, "u.py", bases=["Base"]))
        g.add_edge(SymbolEdge(source="u.py::User", target="core.py::Base", relation=EdgeRelation.INHERITS))
        store = get_graph_store("sqlite", path=":memory:")
        write_graph_to_store(g, store)
        populate_symbol_intent(g, store)
        return g, store

    def test_intent_rows_written_and_readback(self):
        _, store = self._populated_store()
        try:
            intent = store.get_intent("u.py::User")
            assert intent is not None
            assert intent.role == "class"
            assert intent.source == "deterministic"
        finally:
            store.close()

    def test_intent_stats_full_coverage(self):
        g, store = self._populated_store()
        try:
            stats = store.intent_stats()
            assert stats["total_symbols"] == len(g.nodes)
            assert stats["symbols_with_role"] == len(g.nodes)
            assert stats["role_coverage"] == 1.0
        finally:
            store.close()

    def test_compute_fan_in_uses_hint(self):
        _, store = self._populated_store()
        try:
            fan_in = store.compute_fan_in()
            # Unresolved INHERITS target "Base" (short name) is counted.
            assert fan_in.get("core.py::Base", 0) + fan_in.get("Base", 0) >= 1
        finally:
            store.close()

    def test_delete_file_cascades_intent(self):
        _, store = self._populated_store()
        try:
            store.delete_file("u.py")
            assert store.get_intent("u.py::User") is None
        finally:
            store.close()


class TestBuildPopulatesIntent:
    def test_cli_build_populates_roles_and_source(self, tmp_path: Path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "models.py").write_text(
            'from pydantic import BaseModel\n\n\n'
            'class User(BaseModel):\n'
            '    """A user record."""\n'
            '    name: str\n',
            encoding="utf-8",
        )
        (tmp_path / "pkg" / "cli.py").write_text(
            'import typer\n\napp = typer.Typer()\n\n\n'
            '@app.command()\n'
            'def serve():\n'
            '    """Run the server."""\n'
            '    return 0\n',
            encoding="utf-8",
        )
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_user.py").write_text(
            'def test_user_name():\n'
            '    assert True\n',
            encoding="utf-8",
        )

        result = CliRunner().invoke(graph_app, ["build", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Roles:" in result.output

        store = get_graph_store("sqlite", path=str(default_db_path(tmp_path)))
        try:
            user = store.get_intent("pkg/models.py::User")
            serve = store.get_intent("pkg/cli.py::serve")
            test = store.get_intent("tests/test_user.py::test_user_name")
            assert user is not None and user.role == "data_model"
            assert user.summary == "A user record."
            assert serve is not None and serve.role == "cli_command"
            assert test is not None and test.role == "test"
            # Everything carries deterministic provenance + full role coverage.
            stats = store.intent_stats()
            assert stats["role_coverage"] == 1.0
            assert all(
                store.get_intent(fqn).source == "deterministic"
                for fqn in ("pkg/models.py::User", "pkg/cli.py::serve")
            )
        finally:
            store.close()
