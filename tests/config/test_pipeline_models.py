"""Tests for pipeline configuration domain models.

Note on construction: These models use @dataclass on top of Pydantic BaseModel.
The dataclass-generated __init__ is not Pydantic-aware, so model_validate() must
be used instead of direct keyword construction.  Where a custom from_json()
classmethod exists and calls cls(...) directly it is affected by the same
limitation (see test_from_json_custom_override_is_broken for the known bug).
"""

import pytest

from warden.config.domain.models import (
    PipelineConfig,
    PipelineEdge,
    PipelineNode,
    PipelineSettings,
    Position,
    ProjectSummary,
)

# ---------------------------------------------------------------------------
# Shared defaults for PipelineSettings required when building PipelineConfig
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS = {
    "failFast": True,
    "parallel": False,
    "enableLlm": True,
    "llmProvider": "deepseek",
    "enableIssueValidation": True,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pos(x: float = 0.0, y: float = 0.0) -> Position:
    return Position.model_validate({"x": x, "y": y})


def _node(node_id: str, node_type: str) -> PipelineNode:
    return PipelineNode.model_validate(
        {"id": node_id, "type": node_type, "position": {"x": 0, "y": 0}, "data": {"type": node_type}}
    )


def _config(nodes: list[PipelineNode] | None = None, edges: list[PipelineEdge] | None = None) -> PipelineConfig:
    return PipelineConfig.model_validate(
        {
            "id": "pipe-1",
            "name": "Test Pipeline",
            "nodes": [n.model_dump(by_alias=True) for n in (nodes or [])],
            "edges": [e.model_dump(by_alias=True) for e in (edges or [])],
            "settings": _DEFAULT_SETTINGS,
        }
    )


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------


class TestPosition:
    def test_fields_stored(self) -> None:
        pos = _pos(5.0, 15.5)
        assert pos.x == 5.0
        assert pos.y == 15.5

    def test_to_json_shape(self) -> None:
        result = _pos(3.0, 7.0).to_json()
        assert result == {"x": 3.0, "y": 7.0}


# ---------------------------------------------------------------------------
# ProjectSummary
# ---------------------------------------------------------------------------


class TestProjectSummary:
    def test_required_fields_only(self) -> None:
        ps = ProjectSummary.model_validate({"id": "proj-1", "name": "MyProject"})
        assert ps.id == "proj-1"
        assert ps.name == "MyProject"
        assert ps.path is None
        assert ps.branch is None
        assert ps.commit is None

    def test_all_optional_fields(self) -> None:
        ps = ProjectSummary.model_validate(
            {"id": "proj-2", "name": "Full", "path": "/src", "branch": "main", "commit": "abc123"}
        )
        assert ps.path == "/src"
        assert ps.branch == "main"
        assert ps.commit == "abc123"


# ---------------------------------------------------------------------------
# PipelineSettings
# ---------------------------------------------------------------------------


class TestPipelineSettings:
    def _default(self) -> PipelineSettings:
        return PipelineSettings.model_validate(_DEFAULT_SETTINGS)

    def test_defaults(self) -> None:
        s = self._default()
        assert s.fail_fast is True
        assert s.timeout is None
        assert s.parallel is False
        assert s.enable_llm is True
        assert s.llm_provider == "deepseek"

    def test_to_json_keys_are_camel_case(self) -> None:
        result = self._default().to_json()
        for key in ("failFast", "timeout", "parallel", "enableLlm", "llmProvider"):
            assert key in result, f"missing key: {key}"

    def test_to_json_default_values(self) -> None:
        result = self._default().to_json()
        assert result["failFast"] is True
        assert result["timeout"] is None
        assert result["parallel"] is False
        assert result["enableLlm"] is True
        assert result["llmProvider"] == "deepseek"

    def test_to_json_custom_values(self) -> None:
        s = PipelineSettings.model_validate(
            {
                "failFast": False,
                "timeout": 60,
                "parallel": True,
                "enableLlm": False,
                "llmProvider": "openai",
                "enableIssueValidation": True,
            }
        )
        result = s.to_json()
        assert result["failFast"] is False
        assert result["timeout"] == 60
        assert result["parallel"] is True
        assert result["enableLlm"] is False
        assert result["llmProvider"] == "openai"

    def test_round_trip_via_model_validate(self) -> None:
        """to_json output can be fed back into model_validate to recreate the model."""
        original = PipelineSettings.model_validate(
            {
                "failFast": False,
                "timeout": 30,
                "parallel": True,
                "enableLlm": False,
                "llmProvider": "openai",
                "enableIssueValidation": False,
            }
        )
        # to_json produces camelCase; pass it back through model_validate
        restored = PipelineSettings.model_validate(original.to_json())
        assert restored.fail_fast == original.fail_fast
        assert restored.timeout == original.timeout
        assert restored.parallel == original.parallel
        assert restored.enable_llm == original.enable_llm
        assert restored.llm_provider == original.llm_provider

    def test_from_json_custom_override_works(self) -> None:
        """Custom from_json() should work with partial data."""
        s = PipelineSettings.from_json({"failFast": True})
        assert s.fail_fast is True
        assert s.enable_issue_validation is True  # default preserved


# ---------------------------------------------------------------------------
# PipelineNode
# ---------------------------------------------------------------------------


class TestPipelineNode:
    def test_to_json_structure(self) -> None:
        node = PipelineNode.model_validate(
            {
                "id": "node-1",
                "type": "frame",
                "position": {"x": 100.0, "y": 200.0},
                "data": {"frameId": "security", "type": "frame"},
            }
        )
        result = node.to_json()
        assert result["id"] == "node-1"
        assert result["type"] == "frame"
        assert result["position"] == {"x": 100.0, "y": 200.0}
        assert result["data"] == {"frameId": "security", "type": "frame"}

    def test_to_json_for_all_node_types(self) -> None:
        for node_type in ("start", "end", "frame", "globalRule", "rule"):
            node = _node("n", node_type)
            assert node.to_json()["type"] == node_type


# ---------------------------------------------------------------------------
# PipelineEdge
# ---------------------------------------------------------------------------


class TestPipelineEdge:
    def test_to_json_minimal_omits_optional_keys(self) -> None:
        edge = PipelineEdge.model_validate({"id": "e-1", "source": "node-a", "target": "node-b"})
        result = edge.to_json()
        assert result["id"] == "e-1"
        assert result["source"] == "node-a"
        assert result["target"] == "node-b"
        assert result["type"] == "smoothstep"
        assert result["animated"] is True
        for optional in ("sourceHandle", "targetHandle", "style", "label"):
            assert optional not in result, f"unexpected key present: {optional}"

    def test_to_json_with_optional_fields(self) -> None:
        edge = PipelineEdge.model_validate(
            {
                "id": "e-2",
                "source": "node-a",
                "target": "node-b",
                "sourceHandle": "output",
                "targetHandle": "pre-execution",
                "label": "runs before",
            }
        )
        result = edge.to_json()
        assert result["sourceHandle"] == "output"
        assert result["targetHandle"] == "pre-execution"
        assert result["label"] == "runs before"


# ---------------------------------------------------------------------------
# PipelineConfig
# ---------------------------------------------------------------------------


class TestPipelineConfig:
    def test_get_start_node_found(self) -> None:
        start = _node("start-1", "start")
        frame = _node("frame-1", "frame")
        config = _config(nodes=[start, frame])
        found = config.get_start_node()
        assert found is not None
        assert found.id == "start-1"

    def test_get_start_node_not_found(self) -> None:
        config = _config(nodes=[_node("frame-1", "frame")])
        assert config.get_start_node() is None

    def test_get_end_node_found(self) -> None:
        end = _node("end-1", "end")
        config = _config(nodes=[_node("start-1", "start"), end])
        found = config.get_end_node()
        assert found is not None
        assert found.id == "end-1"

    def test_get_end_node_not_found(self) -> None:
        config = _config(nodes=[])
        assert config.get_end_node() is None

    def test_get_frame_nodes_returns_only_frames(self) -> None:
        nodes = [
            _node("start-1", "start"),
            _node("frame-1", "frame"),
            _node("frame-2", "frame"),
            _node("end-1", "end"),
        ]
        frames = _config(nodes=nodes).get_frame_nodes()
        assert len(frames) == 2
        assert all(n.type == "frame" for n in frames)

    def test_get_frame_nodes_empty_when_no_frames(self) -> None:
        config = _config(nodes=[_node("start-1", "start")])
        assert config.get_frame_nodes() == []

    def test_to_json_required_keys_present(self) -> None:
        result = _config().to_json()
        assert result["id"] == "pipe-1"
        assert result["name"] == "Test Pipeline"
        assert result["version"] == "1.0"
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["globalRules"] == []
        assert "settings" in result
        assert "project" not in result

    def test_to_json_includes_project_when_set(self) -> None:
        config = PipelineConfig.model_validate(
            {
                "id": "pipe-2",
                "name": "With Project",
                "project": {"id": "proj-1", "name": "MyRepo"},
                "settings": _DEFAULT_SETTINGS,
            }
        )
        result = config.to_json()
        assert "project" in result
        assert result["project"]["id"] == "proj-1"
        assert result["project"]["name"] == "MyRepo"

    def test_to_json_serializes_nodes_and_edges(self) -> None:
        node = _node("n1", "start")
        edge = PipelineEdge.model_validate({"id": "e1", "source": "n1", "target": "n2"})
        config = _config(nodes=[node], edges=[edge])
        result = config.to_json()
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["id"] == "n1"
        assert len(result["edges"]) == 1
        assert result["edges"][0]["id"] == "e1"
