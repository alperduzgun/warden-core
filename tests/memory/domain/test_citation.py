"""Tests for Citation model and Fact.citations integration."""

import json

from warden.memory.domain.models import Citation, Fact, KnowledgeGraph


class TestCitation:
    """Unit tests for the Citation dataclass."""

    def test_creation_minimal(self):
        """Test Citation with only required field."""
        c = Citation(file="src/main.py")
        assert c.file == "src/main.py"
        assert c.line is None
        assert c.text == ""

    def test_creation_full(self):
        """Test Citation with all fields."""
        c = Citation(file="src/auth.py", line=42, text="def login():")
        assert c.file == "src/auth.py"
        assert c.line == 42
        assert c.text == "def login():"

    def test_frozen(self):
        """Test that Citation is immutable (frozen=True)."""
        c = Citation(file="test.py", line=1)
        try:
            c.file = "other.py"
            assert False, "Should have raised an error"
        except AttributeError:
            pass

    def test_equality(self):
        """Test dataclass equality comparison."""
        c1 = Citation(file="a.py", line=10, text="x")
        c2 = Citation(file="a.py", line=10, text="x")
        assert c1 == c2

    def test_inequality(self):
        """Test dataclass inequality."""
        c1 = Citation(file="a.py", line=10)
        c2 = Citation(file="a.py", line=20)
        assert c1 != c2

    def test_hash(self):
        """Test that Citation is hashable (frozen dataclass)."""
        c = Citation(file="a.py", line=1)
        s = {c}
        assert c in s

    def test_as_dict_key(self):
        """Test Citation can be used as dict key (hashable)."""
        c = Citation(file="a.py", line=1)
        d = {c: "found"}
        assert d[c] == "found"


class TestFactCitations:
    """Tests for Fact.citations field and helper methods."""

    def test_fact_default_empty_citations(self):
        """New Fact should have empty citations list."""
        f = Fact(
            category="test",
            subject="TestClass",
            predicate="has",
            object="method",
        )
        assert f.citations == []

    def test_fact_with_citations(self):
        """Fact can be created with citations as list of dicts."""
        f = Fact(
            category="test",
            subject="TestClass",
            predicate="has",
            object="method",
            citations=[
                {"file": "src/test.py", "line": 10, "text": "class TestClass:"},
                {"file": "src/test.py", "line": 20},
            ],
        )
        assert len(f.citations) == 2

    def test_get_citations(self):
        """get_citations should return typed Citation objects."""
        f = Fact(
            category="test",
            subject="X",
            predicate="p",
            object="o",
            citations=[
                {"file": "a.py", "line": 5, "text": "import os"},
                {"file": "b.py"},
            ],
        )
        typed = f.get_citations()
        assert len(typed) == 2
        assert isinstance(typed[0], Citation)
        assert typed[0].file == "a.py"
        assert typed[0].line == 5
        assert typed[0].text == "import os"
        assert typed[1].file == "b.py"
        assert typed[1].line is None
        assert typed[1].text == ""

    def test_add_citation(self):
        """add_citation should return a new Fact with citation appended."""
        f = Fact(
            category="test",
            subject="X",
            predicate="p",
            object="o",
        )
        c = Citation(file="src/x.py", line=42, text="def method():")
        f2 = f.add_citation(c)

        # Original unchanged
        assert len(f.citations) == 0
        # New fact has citation
        assert len(f2.citations) == 1
        assert f2.citations[0]["file"] == "src/x.py"
        assert f2.citations[0]["line"] == 42
        assert f2.citations[0]["text"] == "def method():"

    def test_add_citation_minimal(self):
        """add_citation with minimal Citation (no line, no text)."""
        f = Fact(category="t", subject="s", predicate="p", object="o")
        c = Citation(file="only_file.py")
        f2 = f.add_citation(c)
        assert f2.citations[0]["file"] == "only_file.py"
        assert "line" not in f2.citations[0]
        assert "text" not in f2.citations[0]

    def test_add_multiple_citations(self):
        """Chaining add_citation should accumulate citations."""
        f = Fact(category="t", subject="s", predicate="p", object="o")
        f = f.add_citation(Citation(file="a.py", line=1))
        f = f.add_citation(Citation(file="b.py", line=2))
        f = f.add_citation(Citation(file="c.py", line=3))
        assert len(f.citations) == 3
        assert f.citations[2]["file"] == "c.py"


class TestFactCitationSerialization:
    """Test that citations survive JSON round-trips."""

    def test_to_json_includes_citations(self):
        """Fact.to_json should include citations."""
        f = Fact(
            category="test",
            subject="X",
            predicate="p",
            object="o",
            citations=[{"file": "a.py", "line": 10, "text": "hello"}],
        )
        data = f.to_json()
        assert "citations" in data
        assert len(data["citations"]) == 1
        assert data["citations"][0]["file"] == "a.py"

    def test_from_json_with_citations(self):
        """Fact.from_json should restore citations."""
        data = {
            "category": "test",
            "subject": "X",
            "predicate": "p",
            "object": "o",
            "citations": [
                {"file": "src/x.py", "line": 5, "text": "import x"},
            ],
        }
        f = Fact.from_json(data)
        assert len(f.citations) == 1
        typed = f.get_citations()
        assert typed[0].file == "src/x.py"
        assert typed[0].line == 5

    def test_json_roundtrip(self):
        """Full JSON serialization round-trip with citations."""
        f = Fact(
            category="arch",
            subject="AuthService",
            predicate="implements",
            object="JWT",
            citations=[
                {"file": "src/auth.py", "line": 1, "text": "class AuthService:"},
                {"file": "src/jwt.py", "line": 15},
            ],
        )
        json_str = json.dumps(f.to_json())
        data = json.loads(json_str)
        f2 = Fact.from_json(data)

        assert len(f2.citations) == 2
        typed = f2.get_citations()
        assert typed[0].file == "src/auth.py"
        assert typed[1].file == "src/jwt.py"
        assert typed[1].line == 15

    def test_backward_compatible_no_citations(self):
        """Fact without citations field should still deserialize."""
        data = {
            "category": "test",
            "subject": "Old",
            "predicate": "existed",
            "object": "before_citations",
        }
        f = Fact.from_json(data)
        assert f.citations == []
        assert f.get_citations() == []


class TestKnowledgeGraphWithCitations:
    """Test KnowledgeGraph round-trip with citation-bearing facts."""

    def test_knowledge_graph_roundtrip(self):
        """KnowledgeGraph serialization should preserve citations."""
        kg = KnowledgeGraph()
        f = Fact(
            id="test-1",
            category="rule",
            subject="NoSQL",
            predicate="uses",
            object="MongoDB",
            citations=[{"file": "config.py", "line": 3, "text": "MONGO_URI = ..."}],
        )
        kg.add_fact(f)

        # Serialize
        data = kg.to_json()
        json_str = json.dumps(data)

        # Deserialize
        data2 = json.loads(json_str)
        kg2 = KnowledgeGraph.from_json(data2)

        restored = kg2.facts["test-1"]
        assert len(restored.citations) == 1
        assert restored.citations[0]["file"] == "config.py"


class TestCitationImports:
    """Test that Citation is importable from expected locations."""

    def test_import_from_models(self):
        from warden.memory.domain.models import Citation as C
        assert C is Citation

    def test_import_from_domain_init(self):
        from warden.memory.domain import Citation as C
        assert C is Citation
