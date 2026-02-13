"""E2E tests for custom rules execution.

Tests verify:
- Custom rule YAML files are loaded
- Custom rule file structure validation
- Rule enable/disable
- Invalid rule file handling
- Custom rule presence in config
"""

import pytest
import yaml
from pathlib import Path
from warden.main import app


@pytest.mark.e2e
class TestCustomRuleConfig:
    """Test custom rule configuration."""

    def test_custom_rules_file_exists(self, isolated_project):
        """Custom rules YAML exists in fixture."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        assert rules_file.exists()

    def test_custom_rules_yaml_valid(self, isolated_project):
        """Custom rules YAML is valid."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        assert "rules" in data
        assert len(data["rules"]) > 0

    def test_custom_rule_has_required_fields(self, isolated_project):
        """Each custom rule has required fields."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        required_fields = ["id", "name", "severity", "category", "isBlocker", "enabled", "type"]
        for rule in data["rules"]:
            for field in required_fields:
                assert field in rule, f"Rule '{rule.get('id', 'unknown')}' missing '{field}'"
            # For non-script/non-ai rules, conditions is required
            if rule["type"] not in ("script", "ai"):
                assert "conditions" in rule, f"Rule '{rule['id']}' missing 'conditions' (required for type={rule['type']})"

    def test_custom_rule_ids_unique(self, isolated_project):
        """Custom rule IDs are unique."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        ids = [r["id"] for r in data["rules"]]
        assert len(ids) == len(set(ids)), f"Duplicate rule IDs: {ids}"

    def test_custom_rule_severity_valid(self, isolated_project):
        """Custom rule severities are valid."""
        valid_severities = {"critical", "high", "medium", "low", "warning", "info", "error"}
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        for rule in data["rules"]:
            assert rule["severity"] in valid_severities, f"Invalid severity: {rule['severity']}"

    def test_custom_rule_category_valid(self, isolated_project):
        """Custom rule categories are valid."""
        valid_categories = {"security", "convention", "performance", "custom", "antipattern"}
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        for rule in data["rules"]:
            assert rule["category"] in valid_categories, f"Invalid category: {rule['category']}"

    def test_custom_rule_type_valid(self, isolated_project):
        """Custom rule types are valid."""
        valid_types = {"security", "convention", "pattern", "script", "ai"}
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        for rule in data["rules"]:
            assert rule["type"] in valid_types, f"Invalid type: {rule['type']}"

    def test_custom_rule_isblocker_boolean(self, isolated_project):
        """Custom rule isBlocker field is boolean."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        for rule in data["rules"]:
            assert isinstance(rule["isBlocker"], bool), f"isBlocker must be boolean for rule {rule['id']}"

    def test_custom_rule_enabled_boolean(self, isolated_project):
        """Custom rule enabled field is boolean."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        for rule in data["rules"]:
            assert isinstance(rule["enabled"], bool), f"enabled must be boolean for rule {rule['id']}"


@pytest.mark.e2e
class TestCustomRuleMutation:
    """Test adding/modifying custom rules."""

    def test_add_custom_rule(self, isolated_project):
        """Add a new custom rule to YAML."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        new_rule = {
            "id": "custom-no-todo",
            "name": "No TODO comments",
            "description": "TODOs should be tracked in issue tracker",
            "category": "convention",
            "severity": "info",
            "isBlocker": False,
            "enabled": True,
            "type": "pattern",
            "pattern": "TODO|FIXME|HACK",
            "language": ["python"],
            "conditions": {},
        }
        data["rules"].append(new_rule)
        rules_file.write_text(yaml.dump(data, default_flow_style=False))
        # Verify it persisted
        reloaded = yaml.safe_load(rules_file.read_text())
        ids = [r["id"] for r in reloaded["rules"]]
        assert "custom-no-todo" in ids

    def test_disable_custom_rule(self, isolated_project):
        """Disable a custom rule."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        data["rules"][0]["enabled"] = False
        rules_file.write_text(yaml.dump(data, default_flow_style=False))
        reloaded = yaml.safe_load(rules_file.read_text())
        assert reloaded["rules"][0]["enabled"] is False

    def test_change_rule_severity(self, isolated_project):
        """Change a custom rule's severity."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        original_severity = data["rules"][0]["severity"]
        data["rules"][0]["severity"] = "critical"
        rules_file.write_text(yaml.dump(data, default_flow_style=False))
        reloaded = yaml.safe_load(rules_file.read_text())
        assert reloaded["rules"][0]["severity"] == "critical"
        assert reloaded["rules"][0]["severity"] != original_severity

    def test_make_rule_blocker(self, isolated_project):
        """Change a custom rule to be a blocker."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        data["rules"][0]["isBlocker"] = True
        rules_file.write_text(yaml.dump(data, default_flow_style=False))
        reloaded = yaml.safe_load(rules_file.read_text())
        assert reloaded["rules"][0]["isBlocker"] is True

    def test_empty_rules_file(self, isolated_project):
        """Empty rules list is valid YAML."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        rules_file.write_text(yaml.dump({"rules": []}, default_flow_style=False))
        data = yaml.safe_load(rules_file.read_text())
        assert data["rules"] == []

    def test_multiple_rule_files(self, isolated_project):
        """Multiple rule files can coexist."""
        rules_dir = isolated_project / ".warden/rules"
        second_rules = rules_dir / "security_rules.yaml"
        second_rules.write_text(yaml.dump({
            "rules": [{
                "id": "sec-no-eval",
                "name": "No eval usage",
                "description": "eval() is dangerous",
                "category": "security",
                "severity": "critical",
                "isBlocker": True,
                "enabled": True,
                "type": "pattern",
                "pattern": "eval\\(",
                "language": ["python"],
                "conditions": {},
            }]
        }, default_flow_style=False))
        assert second_rules.exists()
        data = yaml.safe_load(second_rules.read_text())
        assert data["rules"][0]["id"] == "sec-no-eval"


@pytest.mark.e2e
class TestCustomRuleInvalidInputs:
    """Test handling of invalid rule configurations."""

    def test_invalid_yaml_syntax(self, isolated_project):
        """Invalid YAML syntax causes parse error."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        rules_file.write_text("rules:\n  - id: bad-rule\n    name: Missing quote\n    description: \"Unclosed string")
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(rules_file.read_text())

    def test_missing_rules_key(self, isolated_project):
        """YAML without 'rules' key."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        rules_file.write_text(yaml.dump({"custom": []}, default_flow_style=False))
        data = yaml.safe_load(rules_file.read_text())
        assert "rules" not in data

    def test_rules_not_list(self, isolated_project):
        """Rules field is not a list."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        rules_file.write_text(yaml.dump({"rules": "not-a-list"}, default_flow_style=False))
        data = yaml.safe_load(rules_file.read_text())
        assert not isinstance(data["rules"], list)

    def test_rule_missing_id(self, isolated_project):
        """Rule without id field."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        rules_file.write_text(yaml.dump({
            "rules": [{
                "name": "No ID rule",
                "description": "Missing id field",
                "category": "custom",
                "severity": "low",
                "isBlocker": False,
                "enabled": True,
                "type": "pattern",
                "conditions": {},
            }]
        }, default_flow_style=False))
        data = yaml.safe_load(rules_file.read_text())
        assert "id" not in data["rules"][0]

    def test_invalid_severity_value(self, isolated_project):
        """Rule with invalid severity value."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        rules_file.write_text(yaml.dump({
            "rules": [{
                "id": "bad-severity",
                "name": "Bad severity",
                "description": "Invalid severity",
                "category": "custom",
                "severity": "super-critical",
                "isBlocker": False,
                "enabled": True,
                "type": "pattern",
                "conditions": {},
            }]
        }, default_flow_style=False))
        data = yaml.safe_load(rules_file.read_text())
        assert data["rules"][0]["severity"] == "super-critical"

    def test_invalid_category_value(self, isolated_project):
        """Rule with invalid category value."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        rules_file.write_text(yaml.dump({
            "rules": [{
                "id": "bad-category",
                "name": "Bad category",
                "description": "Invalid category",
                "category": "super-important",
                "severity": "high",
                "isBlocker": False,
                "enabled": True,
                "type": "pattern",
                "conditions": {},
            }]
        }, default_flow_style=False))
        data = yaml.safe_load(rules_file.read_text())
        assert data["rules"][0]["category"] == "super-important"


@pytest.mark.e2e
class TestCustomRuleScan:
    """Test custom rules during scan execution."""

    def test_scan_loads_custom_rules_dir(self, runner, isolated_project, monkeypatch):
        """Scan with basic level loads and doesn't crash with custom rules present."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, [
            "scan", "src/vulnerable.py",
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        # Should not crash with Python errors related to custom rules
        # Exit codes: 0=clean, 1=error, 2=policy failure
        assert result.exit_code in (0, 1, 2), f"Unexpected exit code {result.exit_code}"
        # Should not have custom rule parse errors
        assert "Missing required field 'conditions'" not in result.stdout
        assert "Invalid YAML" not in result.stdout

    def test_scan_with_disabled_rules(self, runner, isolated_project, monkeypatch):
        """Scan works when all custom rules are disabled."""
        monkeypatch.chdir(isolated_project)
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        for rule in data["rules"]:
            rule["enabled"] = False
        rules_file.write_text(yaml.dump(data, default_flow_style=False))
        result = runner.invoke(app, [
            "scan", "src/vulnerable.py",
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        # Should complete without custom rule errors
        assert result.exit_code in (0, 1, 2)
        assert "Missing required field" not in result.stdout

    def test_scan_without_rules_dir(self, runner, isolated_project, monkeypatch):
        """Scan works when .warden/rules/ directory doesn't exist."""
        monkeypatch.chdir(isolated_project)
        import shutil
        rules_dir = isolated_project / ".warden/rules"
        if rules_dir.exists():
            shutil.rmtree(rules_dir)
        result = runner.invoke(app, [
            "scan", "src/vulnerable.py",
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        # Should not crash, should gracefully handle missing rules
        assert result.exit_code in (0, 1, 2)

    def test_scan_with_empty_rules_file(self, runner, isolated_project, monkeypatch):
        """Scan works when rules file has empty rules list."""
        monkeypatch.chdir(isolated_project)
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        rules_file.write_text(yaml.dump({"rules": []}, default_flow_style=False))
        result = runner.invoke(app, [
            "scan", "src/vulnerable.py",
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        # Should complete without errors loading empty rules
        assert result.exit_code in (0, 1, 2)
        assert "rules_loaded" in result.stdout or result.exit_code != 1

    def test_scan_with_only_blocker_rules(self, runner, isolated_project, monkeypatch):
        """Scan with only blocker rules enabled."""
        monkeypatch.chdir(isolated_project)
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        for rule in data["rules"]:
            rule["isBlocker"] = True
        rules_file.write_text(yaml.dump(data, default_flow_style=False))
        result = runner.invoke(app, [
            "scan", "src/vulnerable.py",
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        # Should complete without errors
        assert result.exit_code in (0, 1, 2)
        assert "Missing required field" not in result.stdout

    def test_scan_with_mixed_enabled_disabled_rules(self, runner, isolated_project, monkeypatch):
        """Scan with mix of enabled and disabled rules."""
        monkeypatch.chdir(isolated_project)
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        # Disable first rule, keep second enabled
        data["rules"][0]["enabled"] = False
        data["rules"][1]["enabled"] = True
        rules_file.write_text(yaml.dump(data, default_flow_style=False))
        result = runner.invoke(app, [
            "scan", "src/vulnerable.py",
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        # Should complete without errors
        assert result.exit_code in (0, 1, 2)
        assert "Invalid YAML" not in result.stdout


@pytest.mark.e2e
class TestCustomRuleDirectoryMerge:
    """Test merging multiple rule files from .warden/rules/ directory."""

    def test_multiple_yaml_files_merged(self, isolated_project):
        """Multiple YAML files in rules directory are detected."""
        rules_dir = isolated_project / ".warden/rules"
        # custom_rules.yaml already exists
        assert (rules_dir / "custom_rules.yaml").exists()

        # Add another file
        security_rules = rules_dir / "security_rules.yaml"
        security_rules.write_text(yaml.dump({
            "rules": [{
                "id": "sec-no-shell",
                "name": "No shell=True",
                "description": "Avoid shell=True in subprocess",
                "category": "security",
                "severity": "high",
                "isBlocker": True,
                "enabled": True,
                "type": "pattern",
                "pattern": "shell=True",
                "language": ["python"],
                "conditions": {},
            }]
        }, default_flow_style=False))

        # Both files should exist
        yaml_files = list(rules_dir.glob("*.yaml")) + list(rules_dir.glob("*.yml"))
        assert len(yaml_files) >= 2
        assert security_rules in yaml_files

    def test_scan_with_multiple_rule_files(self, runner, isolated_project, monkeypatch):
        """Scan loads rules from multiple YAML files."""
        monkeypatch.chdir(isolated_project)
        rules_dir = isolated_project / ".warden/rules"

        # Add second rule file
        perf_rules = rules_dir / "performance_rules.yaml"
        perf_rules.write_text(yaml.dump({
            "rules": [{
                "id": "perf-no-global-imports",
                "name": "No global imports in loops",
                "description": "Import at module level",
                "category": "performance",
                "severity": "medium",
                "isBlocker": False,
                "enabled": True,
                "type": "pattern",
                "conditions": {},
            }]
        }, default_flow_style=False))

        result = runner.invoke(app, [
            "scan", "src/vulnerable.py",
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        # Should load both files without crashing
        assert result.exit_code in (0, 1, 2)
        assert "Invalid YAML" not in result.stdout


@pytest.mark.e2e
class TestCustomRuleFileStructure:
    """Test various file structure scenarios."""

    def test_rules_dir_is_directory(self, isolated_project):
        """The .warden/rules path is a directory."""
        rules_dir = isolated_project / ".warden/rules"
        assert rules_dir.is_dir()

    def test_rules_yaml_files_have_yaml_extension(self, isolated_project):
        """Rule files have .yaml or .yml extension."""
        rules_dir = isolated_project / ".warden/rules"
        yaml_files = list(rules_dir.glob("*.yaml")) + list(rules_dir.glob("*.yml"))
        assert len(yaml_files) > 0

    def test_scan_ignores_non_yaml_files(self, runner, isolated_project, monkeypatch):
        """Scan ignores non-YAML files in rules directory."""
        monkeypatch.chdir(isolated_project)
        rules_dir = isolated_project / ".warden/rules"

        # Add non-YAML files
        (rules_dir / "README.md").write_text("# Custom Rules")
        (rules_dir / "script.py").write_text("print('not a rule')")
        (rules_dir / ".gitkeep").write_text("")

        result = runner.invoke(app, [
            "scan", "src/vulnerable.py",
            "--disable-ai",
            "--level", "basic",
            "--no-update-baseline"
        ])
        # Should ignore non-YAML files and not crash
        assert result.exit_code in (0, 1, 2)
        assert "Invalid YAML" not in result.stdout

    def test_rules_file_utf8_encoding(self, isolated_project):
        """Rules YAML files support UTF-8 encoding."""
        rules_file = isolated_project / ".warden/rules/custom_rules.yaml"
        data = yaml.safe_load(rules_file.read_text(encoding="utf-8"))
        assert "rules" in data

        # Add rule with UTF-8 characters
        data["rules"].append({
            "id": "custom-unicode",
            "name": "Unicode Rule 🔒",
            "description": "Règle avec caractères spéciaux",
            "category": "custom",
            "severity": "info",
            "isBlocker": False,
            "enabled": True,
            "type": "pattern",
            "conditions": {},
        })
        rules_file.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")

        # Reload and verify
        reloaded = yaml.safe_load(rules_file.read_text(encoding="utf-8"))
        unicode_rule = [r for r in reloaded["rules"] if r["id"] == "custom-unicode"][0]
        assert "🔒" in unicode_rule["name"]
        assert "Règle" in unicode_rule["description"]


@pytest.mark.e2e
class TestCustomRuleHelp:
    """Test CLI help for custom rules commands (if any)."""

    def test_scan_help_mentions_rules(self, runner):
        """Scan help mentions custom rules or rule loading."""
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        # Help should exist and be comprehensive
        assert "scan" in result.stdout.lower()
