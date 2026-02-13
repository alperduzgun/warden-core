"""Tests for ProjectIntelligence."""
import pytest
from warden.pipeline.domain.intelligence import ProjectIntelligence


class TestProjectIntelligence:
    def test_empty_creation(self):
        intel = ProjectIntelligence()
        assert intel.total_files == 0
        assert intel.input_sources == []
        assert intel.critical_sinks == []

    def test_to_json(self):
        intel = ProjectIntelligence(
            total_files=10,
            primary_language="python",
            input_sources=[{"source": "request.args", "file": "app.py", "line": 5}],
        )
        j = intel.to_json()
        assert j["total_files"] == 10
        assert j["primary_language"] == "python"
        assert len(j["input_sources"]) == 1

    def test_has_web_inputs(self):
        intel = ProjectIntelligence(
            input_sources=[{"source": "request.form['name']", "file": "app.py", "line": 1}]
        )
        assert intel.has_web_inputs is True

    def test_no_web_inputs(self):
        intel = ProjectIntelligence(
            input_sources=[{"source": "os.environ.get('KEY')", "file": "config.py", "line": 1}]
        )
        assert intel.has_web_inputs is False

    def test_has_sql_sinks(self):
        intel = ProjectIntelligence(
            critical_sinks=[{"sink": "cursor.execute", "type": "SQL", "file": "db.py", "line": 10}]
        )
        assert intel.has_sql_sinks is True
        assert intel.has_cmd_sinks is False

    def test_has_cmd_sinks(self):
        intel = ProjectIntelligence(
            critical_sinks=[{"sink": "subprocess.run", "type": "CMD", "file": "run.py", "line": 5}]
        )
        assert intel.has_cmd_sinks is True
        assert intel.has_sql_sinks is False

    def test_empty_has_properties(self):
        intel = ProjectIntelligence()
        assert intel.has_web_inputs is False
        assert intel.has_sql_sinks is False
        assert intel.has_cmd_sinks is False

    def test_to_json_all_fields(self):
        """Verify to_json includes all expected fields."""
        intel = ProjectIntelligence(
            input_sources=[{"source": "request.args", "file": "app.py", "line": 5}],
            critical_sinks=[{"sink": "cursor.execute", "type": "SQL", "file": "db.py", "line": 10}],
            auth_patterns=[{"pattern": "login_required", "file": "views.py"}],
            dependencies=["flask", "sqlalchemy"],
            detected_frameworks=["flask"],
            file_types={"python": 10, "javascript": 3},
            entry_points=["app.py"],
            test_files=["test_app.py"],
            config_files=["config.py"],
            total_files=13,
            total_lines=1500,
            primary_language="python",
        )
        j = intel.to_json()
        assert j["total_files"] == 13
        assert j["total_lines"] == 1500
        assert j["primary_language"] == "python"
        assert len(j["dependencies"]) == 2
        assert len(j["detected_frameworks"]) == 1
        assert j["file_types"]["python"] == 10
        assert len(j["entry_points"]) == 1
        assert len(j["test_files"]) == 1
        assert len(j["config_files"]) == 1
        assert len(j["auth_patterns"]) == 1

    def test_multiple_sinks_mixed(self):
        """Test project with both SQL and CMD sinks."""
        intel = ProjectIntelligence(
            critical_sinks=[
                {"sink": "cursor.execute", "type": "SQL", "file": "db.py", "line": 10},
                {"sink": "subprocess.run", "type": "CMD", "file": "run.py", "line": 5},
                {"sink": "render_template", "type": "HTML", "file": "views.py", "line": 20},
            ]
        )
        assert intel.has_sql_sinks is True
        assert intel.has_cmd_sinks is True

    def test_multiple_web_input_patterns(self):
        """Test detection of various web input patterns."""
        for pattern in ["request.args", "form.data", "params['id']", "query.get", "body.json"]:
            intel = ProjectIntelligence(
                input_sources=[{"source": pattern, "file": "handler.py", "line": 1}]
            )
            assert intel.has_web_inputs is True, f"Failed to detect web input: {pattern}"
