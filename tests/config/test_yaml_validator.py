"""
Tests for warden.config.yaml_validator.

Covers ValidationResult, graph algorithms (DFS cycle detection, BFS path
finding), orphan detection, settings validation, and the top-level validate()
orchestrator.
"""

from unittest.mock import patch

import pytest

from warden.config.domain.models import (
    PipelineConfig,
    PipelineEdge,
    PipelineNode,
    PipelineSettings,
)
from warden.config.yaml_validator import (
    ValidationResult,
    find_orphaned_edges,
    find_orphaned_nodes,
    has_circular_dependency,
    has_path_start_to_end,
    validate,
    validate_basic_structure,
    validate_settings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(node_id: str, node_type: str, data: dict | None = None) -> PipelineNode:
    return PipelineNode.model_validate(
        {
            "id": node_id,
            "type": node_type,
            "position": {"x": 0, "y": 0},
            "data": data or {},
        }
    )


def _edge(edge_id: str, source: str, target: str) -> PipelineEdge:
    return PipelineEdge.model_validate(
        {"id": edge_id, "source": source, "target": target}
    )


def _config(
    nodes: list[PipelineNode],
    edges: list[PipelineEdge],
    settings: PipelineSettings | None = None,
) -> PipelineConfig:
    return PipelineConfig.model_validate(
        {
            "id": "test-pipeline",
            "name": "Test Pipeline",
            "nodes": [n.model_dump() for n in nodes],
            "edges": [e.model_dump() for e in edges],
            "settings": (settings.model_dump() if settings else {}),
        }
    )


def _linear_config() -> PipelineConfig:
    """start -> frame1 -> end — no cycle, valid path."""
    nodes = [
        _node("start", "start"),
        _node("frame1", "frame", {"frameId": "security"}),
        _node("end", "end"),
    ]
    edges = [
        _edge("e1", "start", "frame1"),
        _edge("e2", "frame1", "end"),
    ]
    return _config(nodes, edges)


# ---------------------------------------------------------------------------
# TestValidationResult
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_starts_valid_with_no_messages(self):
        result = ValidationResult()
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_add_error_marks_invalid(self):
        result = ValidationResult()
        result.add_error("something broke")
        assert result.is_valid is False
        assert "something broke" in result.errors

    def test_add_warning_does_not_invalidate(self):
        result = ValidationResult()
        result.add_warning("heads up")
        assert result.is_valid is True
        assert "heads up" in result.warnings

    def test_multiple_errors_accumulated(self):
        result = ValidationResult()
        result.add_error("error one")
        result.add_error("error two")
        assert len(result.errors) == 2

    def test_str_with_no_issues_returns_valid(self):
        result = ValidationResult()
        assert str(result) == "Valid"

    def test_str_formats_errors_and_warnings(self):
        result = ValidationResult()
        result.add_error("bad thing")
        result.add_warning("watch out")
        output = str(result)
        assert "Errors:" in output
        assert "  - bad thing" in output
        assert "Warnings:" in output
        assert "  - watch out" in output

    def test_str_errors_only(self):
        result = ValidationResult()
        result.add_error("only error")
        output = str(result)
        assert "Errors:" in output
        assert "Warnings:" not in output

    def test_str_warnings_only(self):
        result = ValidationResult()
        result.add_warning("only warning")
        output = str(result)
        assert "Warnings:" in output
        assert "Errors:" not in output


# ---------------------------------------------------------------------------
# TestCircularDependency
# ---------------------------------------------------------------------------


class TestCircularDependency:
    def test_linear_graph_has_no_cycle(self):
        config = _linear_config()
        assert has_circular_dependency(config) is False

    def test_direct_cycle_detected(self):
        nodes = [_node("a", "frame"), _node("b", "frame")]
        edges = [_edge("e1", "a", "b"), _edge("e2", "b", "a")]
        config = _config(nodes, edges)
        assert has_circular_dependency(config) is True

    def test_self_loop_detected(self):
        nodes = [_node("a", "frame")]
        edges = [_edge("e1", "a", "a")]
        config = _config(nodes, edges)
        assert has_circular_dependency(config) is True

    def test_diamond_graph_no_cycle(self):
        # start -> left -> end
        #        \-> right -/
        nodes = [
            _node("start", "start"),
            _node("left", "frame"),
            _node("right", "frame"),
            _node("end", "end"),
        ]
        edges = [
            _edge("e1", "start", "left"),
            _edge("e2", "start", "right"),
            _edge("e3", "left", "end"),
            _edge("e4", "right", "end"),
        ]
        config = _config(nodes, edges)
        assert has_circular_dependency(config) is False

    def test_three_node_cycle(self):
        nodes = [_node("a", "frame"), _node("b", "frame"), _node("c", "frame")]
        edges = [
            _edge("e1", "a", "b"),
            _edge("e2", "b", "c"),
            _edge("e3", "c", "a"),
        ]
        config = _config(nodes, edges)
        assert has_circular_dependency(config) is True

    def test_empty_graph_has_no_cycle(self):
        config = _config([], [])
        assert has_circular_dependency(config) is False


# ---------------------------------------------------------------------------
# TestPathFinding
# ---------------------------------------------------------------------------


class TestPathFinding:
    def test_direct_path_exists(self):
        config = _linear_config()
        assert has_path_start_to_end(config) is True

    def test_no_path_when_disconnected(self):
        nodes = [_node("start", "start"), _node("end", "end")]
        config = _config(nodes, [])
        assert has_path_start_to_end(config) is False

    def test_no_path_wrong_direction(self):
        nodes = [_node("start", "start"), _node("end", "end")]
        edges = [_edge("e1", "end", "start")]  # reversed
        config = _config(nodes, edges)
        assert has_path_start_to_end(config) is False

    def test_missing_start_node_returns_false(self):
        nodes = [_node("frame1", "frame"), _node("end", "end")]
        edges = [_edge("e1", "frame1", "end")]
        config = _config(nodes, edges)
        assert has_path_start_to_end(config) is False

    def test_missing_end_node_returns_false(self):
        nodes = [_node("start", "start"), _node("frame1", "frame")]
        edges = [_edge("e1", "start", "frame1")]
        config = _config(nodes, edges)
        assert has_path_start_to_end(config) is False

    def test_multi_hop_path_exists(self):
        nodes = [
            _node("start", "start"),
            _node("f1", "frame"),
            _node("f2", "frame"),
            _node("f3", "frame"),
            _node("end", "end"),
        ]
        edges = [
            _edge("e1", "start", "f1"),
            _edge("e2", "f1", "f2"),
            _edge("e3", "f2", "f3"),
            _edge("e4", "f3", "end"),
        ]
        config = _config(nodes, edges)
        assert has_path_start_to_end(config) is True


# ---------------------------------------------------------------------------
# TestOrphanedNodes
# ---------------------------------------------------------------------------


class TestOrphanedNodes:
    def test_no_orphans_in_connected_graph(self):
        config = _linear_config()
        assert find_orphaned_nodes(config) == []

    def test_one_orphaned_node(self):
        nodes = [
            _node("start", "start"),
            _node("frame1", "frame"),
            _node("end", "end"),
            _node("orphan", "frame"),  # not connected to anything
        ]
        edges = [
            _edge("e1", "start", "frame1"),
            _edge("e2", "frame1", "end"),
        ]
        config = _config(nodes, edges)
        orphans = find_orphaned_nodes(config)
        assert "orphan" in orphans
        assert len(orphans) == 1

    def test_no_orphans_returned_when_start_missing(self):
        nodes = [_node("frame1", "frame"), _node("end", "end")]
        edges = [_edge("e1", "frame1", "end")]
        config = _config(nodes, edges)
        # No start node -> implementation returns empty list
        assert find_orphaned_nodes(config) == []

    def test_multiple_orphans_detected(self):
        nodes = [
            _node("start", "start"),
            _node("end", "end"),
            _node("orphan1", "frame"),
            _node("orphan2", "frame"),
        ]
        edges = [_edge("e1", "start", "end")]
        config = _config(nodes, edges)
        orphans = find_orphaned_nodes(config)
        assert "orphan1" in orphans
        assert "orphan2" in orphans


# ---------------------------------------------------------------------------
# TestOrphanedEdges
# ---------------------------------------------------------------------------


class TestOrphanedEdges:
    def test_no_orphaned_edges_in_valid_config(self):
        config = _linear_config()
        assert find_orphaned_edges(config) == []

    def test_edge_with_missing_source_is_orphaned(self):
        nodes = [_node("start", "start"), _node("end", "end")]
        edges = [
            _edge("e1", "start", "end"),
            _edge("e2", "ghost", "end"),  # "ghost" node does not exist
        ]
        config = _config(nodes, edges)
        orphans = find_orphaned_edges(config)
        assert "e2" in orphans
        assert "e1" not in orphans

    def test_edge_with_missing_target_is_orphaned(self):
        nodes = [_node("start", "start"), _node("end", "end")]
        edges = [
            _edge("e1", "start", "end"),
            _edge("e2", "start", "nowhere"),
        ]
        config = _config(nodes, edges)
        orphans = find_orphaned_edges(config)
        assert "e2" in orphans

    def test_both_endpoints_missing_detected(self):
        nodes = [_node("start", "start")]
        edges = [_edge("e1", "ghost1", "ghost2")]
        config = _config(nodes, edges)
        assert "e1" in find_orphaned_edges(config)


# ---------------------------------------------------------------------------
# TestValidateSettings
# ---------------------------------------------------------------------------


class TestValidateSettings:
    def test_valid_timeout_produces_no_issues(self):
        settings = PipelineSettings.model_validate({"timeout": 300})
        config = _config([], [], settings=settings)
        result = ValidationResult()
        validate_settings(config, result)
        assert result.is_valid is True
        assert result.warnings == []

    def test_negative_timeout_is_an_error(self):
        settings = PipelineSettings.model_validate({"timeout": -1})
        config = _config([], [], settings=settings)
        result = ValidationResult()
        validate_settings(config, result)
        assert result.is_valid is False
        assert any("Timeout must be positive" in e for e in result.errors)

    def test_zero_timeout_is_an_error(self):
        settings = PipelineSettings.model_validate({"timeout": 0})
        config = _config([], [], settings=settings)
        result = ValidationResult()
        validate_settings(config, result)
        assert result.is_valid is False

    def test_large_timeout_triggers_warning(self):
        settings = PipelineSettings.model_validate({"timeout": 7200})  # 2 hours
        config = _config([], [], settings=settings)
        result = ValidationResult()
        validate_settings(config, result)
        assert result.is_valid is True
        assert any("large" in w.lower() for w in result.warnings)

    def test_no_timeout_produces_no_issues(self):
        settings = PipelineSettings.model_validate({})
        config = _config([], [], settings=settings)
        result = ValidationResult()
        validate_settings(config, result)
        assert result.is_valid is True
        assert result.warnings == []

    def test_boundary_timeout_3600_is_valid(self):
        settings = PipelineSettings.model_validate({"timeout": 3600})
        config = _config([], [], settings=settings)
        result = ValidationResult()
        validate_settings(config, result)
        assert result.is_valid is True
        assert result.warnings == []

    def test_boundary_timeout_3601_triggers_warning(self):
        settings = PipelineSettings.model_validate({"timeout": 3601})
        config = _config([], [], settings=settings)
        result = ValidationResult()
        validate_settings(config, result)
        assert any("large" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# TestValidateBasicStructure
# ---------------------------------------------------------------------------


class TestValidateBasicStructure:
    def test_valid_structure_with_mocked_frame(self):
        nodes = [
            _node("start", "start"),
            _node("frame1", "frame", {"frameId": "security"}),
            _node("end", "end"),
        ]
        config = _config(nodes, [])
        result = ValidationResult()
        with patch(
            "warden.config.yaml_validator.get_frame_by_id", return_value=object()
        ):
            validate_basic_structure(config, result)
        assert result.is_valid is True
        assert result.warnings == []

    def test_missing_start_node_is_error(self):
        nodes = [_node("end", "end")]
        config = _config(nodes, [])
        result = ValidationResult()
        with patch("warden.config.yaml_validator.get_frame_by_id", return_value=None):
            validate_basic_structure(config, result)
        assert any("start" in e.lower() for e in result.errors)

    def test_missing_end_node_is_error(self):
        nodes = [_node("start", "start")]
        config = _config(nodes, [])
        result = ValidationResult()
        with patch("warden.config.yaml_validator.get_frame_by_id", return_value=None):
            validate_basic_structure(config, result)
        assert any("end" in e.lower() for e in result.errors)

    def test_no_frame_nodes_produces_warning(self):
        nodes = [_node("start", "start"), _node("end", "end")]
        config = _config(nodes, [])
        result = ValidationResult()
        with patch("warden.config.yaml_validator.get_frame_by_id", return_value=None):
            validate_basic_structure(config, result)
        assert any("frame" in w.lower() for w in result.warnings)

    def test_frame_missing_frame_id_is_error(self):
        nodes = [
            _node("start", "start"),
            _node("frame1", "frame", {}),  # no frameId key
            _node("end", "end"),
        ]
        config = _config(nodes, [])
        result = ValidationResult()
        with patch("warden.config.yaml_validator.get_frame_by_id", return_value=None):
            validate_basic_structure(config, result)
        assert any("frameId" in e for e in result.errors)

    def test_unknown_frame_id_is_error(self):
        nodes = [
            _node("start", "start"),
            _node("frame1", "frame", {"frameId": "unknown-frame"}),
            _node("end", "end"),
        ]
        config = _config(nodes, [])
        result = ValidationResult()
        with patch(
            "warden.config.yaml_validator.get_frame_by_id", return_value=None
        ):
            validate_basic_structure(config, result)
        assert any("Unknown frame ID" in e for e in result.errors)


# ---------------------------------------------------------------------------
# TestValidateOrchestrator
# ---------------------------------------------------------------------------


class TestValidateOrchestrator:
    def test_full_valid_config_returns_no_errors(self):
        config = _linear_config()
        with patch(
            "warden.config.yaml_validator.get_frame_by_id", return_value=object()
        ):
            result = validate(config)
        assert result.is_valid is True

    def test_config_with_missing_start_and_no_path_has_errors(self):
        nodes = [_node("end", "end")]
        config = _config(nodes, [])
        with patch("warden.config.yaml_validator.get_frame_by_id", return_value=None):
            result = validate(config)
        assert result.is_valid is False
        assert len(result.errors) >= 1

    def test_config_with_cycle_has_error(self):
        nodes = [
            _node("start", "start"),
            _node("frame1", "frame", {"frameId": "security"}),
            _node("end", "end"),
        ]
        edges = [
            _edge("e1", "start", "frame1"),
            _edge("e2", "frame1", "start"),  # cycle back to start
        ]
        config = _config(nodes, edges)
        with patch(
            "warden.config.yaml_validator.get_frame_by_id", return_value=object()
        ):
            result = validate(config)
        assert any("Circular" in e for e in result.errors)

    def test_returns_validation_result_instance(self):
        config = _linear_config()
        with patch(
            "warden.config.yaml_validator.get_frame_by_id", return_value=object()
        ):
            result = validate(config)
        assert isinstance(result, ValidationResult)
