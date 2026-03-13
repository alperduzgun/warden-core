"""Tests for warden.config.yaml_parser.

Covers load_yaml file validation, parse_simple_format, parse_full_format,
and auto-detection in parse_yaml.
"""

from unittest.mock import MagicMock, patch

import pytest

from warden.config.yaml_parser import (
    YAMLParseError,
    load_yaml,
    parse_full_format,
    parse_simple_format,
    parse_yaml,
)

MOCK_FRAME = MagicMock(id="security", name="Security Frame")

SIMPLE_DATA = {
    "name": "Test Pipeline",
    "frames": ["security"],
}

FULL_DATA = {
    "id": "pipe-1",
    "name": "Full Pipeline",
    "nodes": [
        {"id": "start", "type": "start", "position": {"x": 100, "y": 200}, "data": {}},
        {"id": "end", "type": "end", "position": {"x": 300, "y": 200}, "data": {}},
    ],
    "edges": [
        {"id": "e0", "source": "start", "target": "end"},
    ],
}


# ---------------------------------------------------------------------------
# load_yaml
# ---------------------------------------------------------------------------


class TestLoadYaml:
    def test_empty_path_raises(self):
        with pytest.raises(YAMLParseError, match="empty"):
            load_yaml("")

    def test_path_traversal_raises(self):
        with pytest.raises(YAMLParseError, match="traversal"):
            load_yaml("../../etc/passwd")

    def test_file_not_found_raises(self, tmp_path):
        missing = str(tmp_path / "nonexistent.yaml")
        with pytest.raises(YAMLParseError, match="not found"):
            load_yaml(missing)

    def test_file_too_large_raises(self, tmp_path):
        large_file = tmp_path / "big.yaml"
        large_file.write_bytes(b"x: " + b"a" * (1 * 1024 * 1024 + 1))
        with pytest.raises(YAMLParseError, match="too large"):
            load_yaml(str(large_file))

    def test_non_dict_root_raises(self, tmp_path):
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        with pytest.raises(YAMLParseError, match="dictionary"):
            load_yaml(str(f))

    def test_invalid_yaml_syntax_raises(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("key: [\n  unclosed bracket\n")
        with pytest.raises(YAMLParseError, match="Invalid YAML"):
            load_yaml(str(f))

    def test_valid_yaml_returns_dict(self, tmp_path):
        f = tmp_path / "good.yaml"
        f.write_text("name: Test\nversion: '1.0'\n")
        result = load_yaml(str(f))
        assert isinstance(result, dict)
        assert result["name"] == "Test"


# ---------------------------------------------------------------------------
# parse_simple_format
# ---------------------------------------------------------------------------


class TestParseSimpleFormat:
    def test_missing_name_raises(self):
        with pytest.raises(YAMLParseError, match="name"):
            parse_simple_format({"frames": ["security"]})

    def test_missing_frames_key_raises(self):
        with pytest.raises(YAMLParseError, match="frame"):
            parse_simple_format({"name": "No Frames"})

    def test_empty_frames_list_raises(self):
        with pytest.raises(YAMLParseError, match="frame"):
            parse_simple_format({"name": "Empty", "frames": []})


    def test_valid_input_returns_pipeline_config(self):
        with patch("warden.config.yaml_parser.get_frame_by_id", return_value=MOCK_FRAME):
            config = parse_simple_format(SIMPLE_DATA)
        assert config.name == "Test Pipeline"
        # start + 1 frame + end = 3 nodes, 2 edges
        assert len(config.nodes) == 3
        assert len(config.edges) == 2


    def test_linear_edge_order(self):
        with patch("warden.config.yaml_parser.get_frame_by_id", return_value=MOCK_FRAME):
            config = parse_simple_format(SIMPLE_DATA)
        node_ids = [n.id for n in config.nodes]
        assert node_ids[0] == "start"
        assert node_ids[-1] == "end"
        assert config.edges[0].source == "start"
        assert config.edges[-1].target == "end"


    def test_unknown_frame_id_raises(self):
        with patch("warden.config.yaml_parser.get_frame_by_id", return_value=None):
            with pytest.raises(YAMLParseError, match="Unknown frame"):
                parse_simple_format({"name": "Bad", "frames": ["nonexistent"]})


    def test_settings_parsing(self):
        data = {
            "name": "Settings Test",
            "frames": ["security"],
            "settings": {
                "fail_fast": False,
                "timeout": 120,
                "parallel": True,
                "enable_issue_validation": False,
            },
        }
        with patch("warden.config.yaml_parser.get_frame_by_id", return_value=MOCK_FRAME):
            config = parse_simple_format(data)
        assert config.settings.fail_fast is False
        assert config.settings.timeout == 120
        assert config.settings.parallel is True
        assert config.settings.enable_issue_validation is False


    def test_settings_defaults(self):
        with patch("warden.config.yaml_parser.get_frame_by_id", return_value=MOCK_FRAME):
            config = parse_simple_format(SIMPLE_DATA)
        assert config.settings.fail_fast is True
        assert config.settings.parallel is False
        assert config.settings.enable_issue_validation is True


    def test_multiple_frames_produce_correct_node_count(self):
        data = {"name": "Multi", "frames": ["security", "resilience", "fuzz"]}
        with patch("warden.config.yaml_parser.get_frame_by_id", return_value=MOCK_FRAME):
            config = parse_simple_format(data)
        # start + 3 frames + end = 5 nodes, 4 edges
        assert len(config.nodes) == 5
        assert len(config.edges) == 4


    def test_version_and_id_defaults(self):
        with patch("warden.config.yaml_parser.get_frame_by_id", return_value=MOCK_FRAME):
            config = parse_simple_format(SIMPLE_DATA)
        assert config.version == "1.0"
        assert config.id == "pipeline-1"


# ---------------------------------------------------------------------------
# parse_full_format
# ---------------------------------------------------------------------------


class TestParseFullFormat:
    def test_missing_id_raises(self):
        data = {k: v for k, v in FULL_DATA.items() if k != "id"}
        with pytest.raises(YAMLParseError, match="id"):
            parse_full_format(data)

    def test_missing_name_raises(self):
        data = {k: v for k, v in FULL_DATA.items() if k != "name"}
        with pytest.raises(YAMLParseError, match="name"):
            parse_full_format(data)

    def test_missing_nodes_raises(self):
        data = {k: v for k, v in FULL_DATA.items() if k != "nodes"}
        with pytest.raises(YAMLParseError, match="nodes"):
            parse_full_format(data)

    def test_missing_edges_raises(self):
        data = {k: v for k, v in FULL_DATA.items() if k != "edges"}
        with pytest.raises(YAMLParseError, match="edges"):
            parse_full_format(data)


    def test_valid_input_returns_pipeline_config(self):
        config = parse_full_format(FULL_DATA)
        assert config.id == "pipe-1"
        assert config.name == "Full Pipeline"
        assert len(config.nodes) == 2
        assert len(config.edges) == 1


    def test_optional_project_parsed(self):
        data = {
            **FULL_DATA,
            "project": {"id": "proj-1", "name": "My Project", "branch": "main"},
        }
        config = parse_full_format(data)
        assert config.project is not None
        assert config.project.id == "proj-1"
        assert config.project.branch == "main"


    def test_no_project_field_leaves_none(self):
        config = parse_full_format(FULL_DATA)
        assert config.project is None


    def test_settings_parsed(self):
        data = {
            **FULL_DATA,
            "settings": {"fail_fast": False, "parallel": True},
        }
        config = parse_full_format(data)
        assert config.settings.fail_fast is False
        assert config.settings.parallel is True


    def test_edge_optional_fields_default(self):
        config = parse_full_format(FULL_DATA)
        edge = config.edges[0]
        assert edge.type == "smoothstep"
        assert edge.animated is True
        assert edge.label is None


# ---------------------------------------------------------------------------
# parse_yaml (format auto-detection)
# ---------------------------------------------------------------------------


class TestParseYaml:
    def test_invalid_format_raises(self, tmp_path):
        f = tmp_path / "bad_format.yaml"
        f.write_text("name: Incomplete\nversion: '1.0'\n")
        with pytest.raises(YAMLParseError, match="Invalid format"):
            parse_yaml(str(f))


    def test_simple_format_detected_by_frames(self, tmp_path):
        f = tmp_path / "simple.yaml"
        f.write_text("name: My Pipeline\nframes:\n  - security\n")
        with patch("warden.config.yaml_parser.get_frame_by_id", return_value=MOCK_FRAME):
            config = parse_yaml(str(f))
        assert config.name == "My Pipeline"


    def test_full_format_detected_by_nodes_and_edges(self, tmp_path):
        import yaml

        f = tmp_path / "full.yaml"
        f.write_text(yaml.dump(FULL_DATA))
        config = parse_yaml(str(f))
        assert config.id == "pipe-1"


    def test_nodes_and_edges_take_precedence_over_frames(self, tmp_path):
        import yaml

        data = {**FULL_DATA, "frames": ["security"]}
        f = tmp_path / "both.yaml"
        f.write_text(yaml.dump(data))
        # nodes+edges present → full format chosen; get_frame_by_id not called
        config = parse_yaml(str(f))
        assert config.id == "pipe-1"
