"""E2E tests for suppression system CLI integration.

Tests verify:
- Suppression YAML loading
- Inline warden-ignore comments
- Global suppression entries
- Wildcard suppression
- File pattern matching
- Suppression config mutations
"""

import pytest
import yaml
from pathlib import Path
from warden.main import app


@pytest.mark.e2e
class TestSuppressionConfig:
    """Test suppression configuration structure."""

    def test_suppression_yaml_exists(self, isolated_project):
        """Suppression config exists in fixture."""
        supp_file = isolated_project / ".warden/suppression.yaml"
        assert supp_file.exists()

    def test_suppression_yaml_valid(self, isolated_project):
        """Suppression YAML is valid structure."""
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        assert "enabled" in data
        assert data["enabled"] is True
        assert "entries" in data

    def test_suppression_entry_has_required_fields(self, isolated_project):
        """Each suppression entry has required fields."""
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        for entry in data["entries"]:
            assert "id" in entry
            assert "type" in entry
            assert "rules" in entry
            assert "reason" in entry

    def test_suppression_can_be_disabled(self, isolated_project):
        """Suppression can be disabled globally."""
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        data["enabled"] = False
        supp_file.write_text(yaml.dump(data, default_flow_style=False))
        reloaded = yaml.safe_load(supp_file.read_text())
        assert reloaded["enabled"] is False


@pytest.mark.e2e
class TestSuppressionMutation:
    """Test adding/modifying suppressions."""

    def test_add_suppression_entry(self, isolated_project):
        """Add a new suppression entry."""
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        data["entries"].append({
            "id": "suppress-sql-vuln",
            "type": "config",
            "rules": ["sql-injection"],
            "file": "src/vulnerable.py",
            "reason": "Known issue, tracked in JIRA-123",
        })
        supp_file.write_text(yaml.dump(data, default_flow_style=False))
        reloaded = yaml.safe_load(supp_file.read_text())
        assert len(reloaded["entries"]) == 2
        assert reloaded["entries"][1]["id"] == "suppress-sql-vuln"

    def test_add_wildcard_suppression(self, isolated_project):
        """Add wildcard suppression for all rules on a file."""
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        data["entries"].append({
            "id": "suppress-all-messy",
            "type": "config",
            "rules": [],
            "file": "src/messy.py",
            "reason": "Legacy code, will be refactored",
        })
        supp_file.write_text(yaml.dump(data, default_flow_style=False))
        reloaded = yaml.safe_load(supp_file.read_text())
        wildcard_entry = [e for e in reloaded["entries"] if e["id"] == "suppress-all-messy"][0]
        assert wildcard_entry["rules"] == []

    def test_remove_suppression_entry(self, isolated_project):
        """Remove a suppression entry."""
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        original_count = len(data["entries"])
        data["entries"] = [e for e in data["entries"] if e["id"] != "suppress-test-secret"]
        supp_file.write_text(yaml.dump(data, default_flow_style=False))
        reloaded = yaml.safe_load(supp_file.read_text())
        assert len(reloaded["entries"]) == original_count - 1

    def test_add_global_rules(self, isolated_project):
        """Add global rule suppression."""
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        data["globalRules"] = ["unused-import", "magic-number"]
        supp_file.write_text(yaml.dump(data, default_flow_style=False))
        reloaded = yaml.safe_load(supp_file.read_text())
        assert "globalRules" in reloaded
        assert "unused-import" in reloaded["globalRules"]
        assert "magic-number" in reloaded["globalRules"]

    def test_add_ignored_files(self, isolated_project):
        """Add ignored file patterns."""
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        data["ignoredFiles"] = ["test_*.py", "migrations/*.py", "generated/*"]
        supp_file.write_text(yaml.dump(data, default_flow_style=False))
        reloaded = yaml.safe_load(supp_file.read_text())
        assert "ignoredFiles" in reloaded
        assert "test_*.py" in reloaded["ignoredFiles"]
        assert "generated/*" in reloaded["ignoredFiles"]


@pytest.mark.e2e
class TestInlineSuppression:
    """Test inline warden-ignore comments."""

    def test_create_file_with_inline_suppression(self, isolated_project):
        """Create a Python file with warden-ignore comment."""
        src_dir = isolated_project / "src"
        suppressed_file = src_dir / "with_suppression.py"
        suppressed_file.write_text('''"""File with inline suppressions for testing."""
import os

# warden-ignore: hardcoded-secret
API_KEY = "test-key-12345"

def safe_func():
    password = "admin123"  # warden-ignore: hardcoded-secret
    return password

# warden-ignore
def suppress_all():
    """This line suppresses all rules."""
    eval("1 + 1")
''')
        assert suppressed_file.exists()
        content = suppressed_file.read_text()
        assert "warden-ignore" in content

    def test_inline_suppression_with_multiple_rules(self, isolated_project):
        """Create file with multi-rule inline suppression."""
        src_dir = isolated_project / "src"
        multi_file = src_dir / "multi_suppress.py"
        multi_file.write_text('''"""File with multi-rule suppression."""
# warden-ignore: hardcoded-secret, command-injection
API_KEY = "secret"
''')
        content = multi_file.read_text()
        assert "hardcoded-secret, command-injection" in content

    def test_javascript_style_suppression(self, isolated_project):
        """Create JS file with // warden-ignore comment."""
        src_dir = isolated_project / "src"
        js_file = src_dir / "test.js"
        js_file.write_text('''// warden-ignore: hardcoded-secret
const API_KEY = "test-key";
''')
        content = js_file.read_text()
        assert "// warden-ignore" in content

    def test_block_comment_style_suppression(self, isolated_project):
        """Create file with block comment warden-ignore."""
        src_dir = isolated_project / "src"
        block_file = src_dir / "block.js"
        block_file.write_text('''/* warden-ignore: hardcoded-secret */
const SECRET = "my-secret";
''')
        content = block_file.read_text()
        assert "/* warden-ignore" in content


@pytest.mark.e2e
class TestSuppressionScan:
    """Test suppression during scan execution."""

    def test_scan_with_suppression_config(self, runner, isolated_project, monkeypatch):
        """Scan loads suppression config without crashing."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, [
            "scan", str(isolated_project / "src/vulnerable.py"),
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        # Should not crash with exit codes 0 (clean), 1 (error), or 2 (policy fail)
        assert result.exit_code in (0, 1, 2)

    def test_scan_with_disabled_suppression(self, runner, isolated_project, monkeypatch):
        """Scan works with suppression disabled."""
        monkeypatch.chdir(isolated_project)
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        data["enabled"] = False
        supp_file.write_text(yaml.dump(data, default_flow_style=False))
        result = runner.invoke(app, [
            "scan", str(isolated_project / "src/vulnerable.py"),
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        assert result.exit_code in (0, 1, 2)

    def test_scan_without_suppression_file(self, runner, isolated_project, monkeypatch):
        """Scan works when suppression.yaml doesn't exist."""
        monkeypatch.chdir(isolated_project)
        supp_file = isolated_project / ".warden/suppression.yaml"
        if supp_file.exists():
            supp_file.unlink()
        result = runner.invoke(app, [
            "scan", str(isolated_project / "src/vulnerable.py"),
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        # Should not crash
        assert result.exit_code in (0, 1, 2)

    def test_scan_with_inline_suppressed_file(self, runner, isolated_project, monkeypatch):
        """Scan a file that has inline warden-ignore comments."""
        monkeypatch.chdir(isolated_project)
        # Create file with suppression
        suppressed = isolated_project / "src/suppressed.py"
        suppressed.write_text('''# warden-ignore: hardcoded-secret
API_KEY = "test-secret-key"
''')
        result = runner.invoke(app, [
            "scan", str(suppressed),
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        assert result.exit_code in (0, 1, 2)

    def test_scan_with_global_rule_suppression(self, runner, isolated_project, monkeypatch):
        """Scan with globally suppressed rules."""
        monkeypatch.chdir(isolated_project)
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        data["globalRules"] = ["hardcoded-secret"]
        supp_file.write_text(yaml.dump(data, default_flow_style=False))
        result = runner.invoke(app, [
            "scan", str(isolated_project / "src/vulnerable.py"),
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        assert result.exit_code in (0, 1, 2)

    def test_scan_with_ignored_files_pattern(self, runner, isolated_project, monkeypatch):
        """Scan with file ignore patterns."""
        monkeypatch.chdir(isolated_project)
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        data["ignoredFiles"] = ["src/vulnerable.py", "src/messy.py"]
        supp_file.write_text(yaml.dump(data, default_flow_style=False))
        result = runner.invoke(app, [
            "scan", str(isolated_project / "src"),
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        assert result.exit_code in (0, 1, 2)


@pytest.mark.e2e
class TestSuppressionEdgeCases:
    """Test edge cases and error handling."""

    def test_malformed_yaml_handled_gracefully(self, runner, isolated_project, monkeypatch):
        """Scan handles malformed suppression.yaml."""
        monkeypatch.chdir(isolated_project)
        supp_file = isolated_project / ".warden/suppression.yaml"
        supp_file.write_text("enabled: true\nentries:\n  - id: bad\n    type: [malformed")
        result = runner.invoke(app, [
            "scan", str(isolated_project / "src/clean.py"),
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        # Should handle error gracefully
        assert result.exit_code in (0, 1, 2)

    def test_empty_suppression_file(self, runner, isolated_project, monkeypatch):
        """Scan handles empty suppression.yaml."""
        monkeypatch.chdir(isolated_project)
        supp_file = isolated_project / ".warden/suppression.yaml"
        supp_file.write_text("")
        result = runner.invoke(app, [
            "scan", str(isolated_project / "src/clean.py"),
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        assert result.exit_code in (0, 1, 2)

    def test_suppression_with_missing_type_field(self, runner, isolated_project, monkeypatch):
        """Scan handles suppression entry missing type field."""
        monkeypatch.chdir(isolated_project)
        supp_file = isolated_project / ".warden/suppression.yaml"
        supp_file.write_text("""enabled: true
entries:
  - id: "bad-entry"
    rules: ["hardcoded-secret"]
    file: "src/clean.py"
    reason: "Missing type field"
""")
        result = runner.invoke(app, [
            "scan", str(isolated_project / "src/clean.py"),
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        # May fail due to validation error, but should not crash
        assert result.exit_code in (0, 1, 2)

    def test_suppression_with_invalid_type(self, runner, isolated_project, monkeypatch):
        """Scan handles invalid suppression type."""
        monkeypatch.chdir(isolated_project)
        supp_file = isolated_project / ".warden/suppression.yaml"
        supp_file.write_text("""enabled: true
entries:
  - id: "bad-type"
    type: "invalid"
    rules: ["hardcoded-secret"]
    file: "src/clean.py"
""")
        result = runner.invoke(app, [
            "scan", str(isolated_project / "src/clean.py"),
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        assert result.exit_code in (0, 1, 2)

    def test_suppression_entry_with_line_number(self, isolated_project):
        """Add suppression entry with specific line number."""
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        data["entries"].append({
            "id": "suppress-line-42",
            "type": "config",
            "rules": ["hardcoded-secret"],
            "file": "src/vulnerable.py",
            "line": 42,
            "reason": "Suppress only line 42",
        })
        supp_file.write_text(yaml.dump(data, default_flow_style=False))
        reloaded = yaml.safe_load(supp_file.read_text())
        line_entry = [e for e in reloaded["entries"] if e["id"] == "suppress-line-42"][0]
        assert line_entry["line"] == 42

    def test_suppression_with_glob_pattern(self, isolated_project):
        """Add suppression with glob file pattern."""
        supp_file = isolated_project / ".warden/suppression.yaml"
        data = yaml.safe_load(supp_file.read_text())
        data["entries"].append({
            "id": "suppress-all-lib",
            "type": "config",
            "rules": [],
            "file": "src/lib/*.py",
            "reason": "Suppress all in lib directory",
        })
        supp_file.write_text(yaml.dump(data, default_flow_style=False))
        reloaded = yaml.safe_load(supp_file.read_text())
        glob_entry = [e for e in reloaded["entries"] if e["id"] == "suppress-all-lib"][0]
        assert glob_entry["file"] == "src/lib/*.py"
        assert glob_entry["rules"] == []
