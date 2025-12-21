"""Unit tests for rules CLI commands.

Tests the complete rules command group:
- validate: Validate rules configuration files
- list: List all configured rules
- test: Test a rule against a specific file
- show: Show detailed rule information
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from warden.cli.commands.rules import app
from warden.rules.domain.enums import RuleCategory, RuleSeverity
from warden.rules.domain.models import CustomRule, CustomRuleViolation, ProjectRuleConfig


@pytest.fixture
def cli_runner():
    """Fixture providing Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_rules_file(tmp_path):
    """Create a temporary valid rules file for testing."""
    rules_content = {
        "project": {
            "name": "test-project",
            "language": "python",
            "framework": "cli"
        },
        "rules": [
            {
                "id": "test-rule-1",
                "name": "Test Rule 1",
                "category": "security",
                "severity": "critical",
                "isBlocker": True,
                "description": "Test security rule",
                "enabled": True,
                "type": "security",
                "conditions": {
                    "secrets": {
                        "patterns": ["secret\\s*=\\s*"]
                    }
                },
                "message": "No secrets allowed",
                "examples": {
                    "invalid": ["secret = 'password'"],
                    "valid": ["secret = os.getenv('SECRET')"]
                }
            },
            {
                "id": "test-rule-2",
                "name": "Test Rule 2",
                "category": "convention",
                "severity": "medium",
                "isBlocker": False,
                "description": "Test convention rule",
                "enabled": True,
                "type": "convention",
                "conditions": {
                    "naming": {
                        "asyncMethodSuffix": "_async"
                    }
                }
            },
            {
                "id": "test-rule-disabled",
                "name": "Disabled Rule",
                "category": "performance",
                "severity": "low",
                "isBlocker": False,
                "description": "Disabled test rule",
                "enabled": False,
                "type": "convention",
                "conditions": {}
            }
        ],
        "ai_validation": {
            "enabled": True,
            "llm_provider": "azure_openai"
        },
        "exclude": {
            "paths": ["node_modules/", "venv/"],
            "files": ["*.test.py"]
        }
    }

    rules_file = tmp_path / "test_rules.yaml"
    with open(rules_file, "w") as f:
        yaml.dump(rules_content, f)

    return rules_file


@pytest.fixture
def temp_invalid_yaml(tmp_path):
    """Create a temporary invalid YAML file."""
    invalid_file = tmp_path / "invalid.yaml"
    with open(invalid_file, "w") as f:
        f.write("invalid: yaml: content::\n  - broken")
    return invalid_file


@pytest.fixture
def temp_test_file(tmp_path):
    """Create a temporary Python file for testing rules against."""
    test_file = tmp_path / "test.py"
    test_file.write_text("""
async def my_function():
    secret = "hardcoded_password"
    return secret
""")
    return test_file


class TestRulesValidateCommand:
    """Test suite for 'warden rules validate' command."""

    def test_validate_valid_config(self, cli_runner, temp_rules_file):
        """Test validating a valid rules configuration."""
        result = cli_runner.invoke(app, ["validate", str(temp_rules_file)])

        assert result.exit_code == 0
        assert "Configuration is valid" in result.stdout
        assert "test-project" in result.stdout
        assert "Total Rules" in result.stdout
        assert "Enabled Rules" in result.stdout

    def test_validate_file_not_found(self, cli_runner):
        """Test validation with non-existent file."""
        result = cli_runner.invoke(app, ["validate", "/nonexistent/file.yaml"])

        assert result.exit_code == 1
        assert "File not found" in result.stdout

    def test_validate_invalid_yaml(self, cli_runner, temp_invalid_yaml):
        """Test validation with invalid YAML syntax."""
        result = cli_runner.invoke(app, ["validate", str(temp_invalid_yaml)])

        assert result.exit_code == 1
        assert "Error" in result.stdout or "error" in result.stdout.lower()

    def test_validate_shows_severity_distribution(self, cli_runner, temp_rules_file):
        """Test that validation shows severity distribution."""
        result = cli_runner.invoke(app, ["validate", str(temp_rules_file)])

        assert result.exit_code == 0
        assert "Critical Severity" in result.stdout
        assert "Medium Severity" in result.stdout

    def test_validate_shows_blocker_count(self, cli_runner, temp_rules_file):
        """Test that validation shows blocker rule count."""
        result = cli_runner.invoke(app, ["validate", str(temp_rules_file)])

        assert result.exit_code == 0
        assert "Blocker Rules" in result.stdout

    def test_validate_detects_duplicates(self, cli_runner, tmp_path):
        """Test validation detects duplicate rule IDs."""
        duplicate_rules = {
            "project": {"name": "test", "language": "python"},
            "rules": [
                {
                    "id": "duplicate-id",
                    "name": "Rule 1",
                    "category": "security",
                    "severity": "high",
                    "isBlocker": True,
                    "description": "First rule",
                    "enabled": True,
                    "type": "security",
                    "conditions": {"secrets": {"patterns": ["secret"]}}
                },
                {
                    "id": "duplicate-id",  # Duplicate!
                    "name": "Rule 2",
                    "category": "security",
                    "severity": "high",
                    "isBlocker": True,
                    "description": "Second rule",
                    "enabled": True,
                    "type": "security",
                    "conditions": {"secrets": {"patterns": ["token"]}}
                }
            ]
        }

        dup_file = tmp_path / "duplicates.yaml"
        with open(dup_file, "w") as f:
            yaml.dump(duplicate_rules, f)

        result = cli_runner.invoke(app, ["validate", str(dup_file)])

        assert result.exit_code == 1
        assert "Validation Failed" in result.stdout
        assert "duplicate-id" in result.stdout.lower() or "Duplicate" in result.stdout


class TestRulesListCommand:
    """Test suite for 'warden rules list' command."""

    def test_list_default_config(self, cli_runner, temp_rules_file, monkeypatch):
        """Test listing rules from default config location."""
        # Mock Path.exists to return True for .warden/rules.yaml
        monkeypatch.chdir(temp_rules_file.parent)

        result = cli_runner.invoke(app, ["list", "--config", str(temp_rules_file)])

        assert result.exit_code == 0
        assert "Custom Rules" in result.stdout
        assert "test-rule-1" in result.stdout
        assert "test-rule-2" in result.stdout

    def test_list_shows_only_enabled_by_default(self, cli_runner, temp_rules_file):
        """Test that list shows only enabled rules by default."""
        result = cli_runner.invoke(app, ["list", "--config", str(temp_rules_file)])

        assert result.exit_code == 0
        # Should show enabled rules
        assert "test-rule-1" in result.stdout
        assert "test-rule-2" in result.stdout
        # Should NOT show disabled rule
        assert "test-rule-disabled" not in result.stdout

    def test_list_shows_disabled_with_flag(self, cli_runner, temp_rules_file):
        """Test listing all rules including disabled ones."""
        result = cli_runner.invoke(
            app,
            ["list", "--config", str(temp_rules_file), "--show-disabled"]
        )

        assert result.exit_code == 0
        # Should show ALL rules
        assert "test-rule-1" in result.stdout
        assert "test-rule-2" in result.stdout
        assert "test-rule-disabled" in result.stdout

    def test_list_shows_severity_colors(self, cli_runner, temp_rules_file):
        """Test that list shows severity levels."""
        result = cli_runner.invoke(app, ["list", "--config", str(temp_rules_file)])

        assert result.exit_code == 0
        assert "CRITICAL" in result.stdout or "critical" in result.stdout
        assert "MEDIUM" in result.stdout or "medium" in result.stdout

    def test_list_shows_blocker_indicator(self, cli_runner, temp_rules_file):
        """Test that list shows blocker indicators."""
        result = cli_runner.invoke(app, ["list", "--config", str(temp_rules_file)])

        assert result.exit_code == 0
        assert "YES" in result.stdout or "no" in result.stdout

    def test_list_file_not_found(self, cli_runner):
        """Test list command with non-existent config file."""
        result = cli_runner.invoke(app, ["list", "--config", "/nonexistent.yaml"])

        assert result.exit_code == 1
        assert "not found" in result.stdout

    def test_list_shows_summary(self, cli_runner, temp_rules_file):
        """Test that list shows summary statistics."""
        result = cli_runner.invoke(app, ["list", "--config", str(temp_rules_file)])

        assert result.exit_code == 0
        assert "Enabled:" in result.stdout
        assert "Blockers:" in result.stdout


class TestRulesTestCommand:
    """Test suite for 'warden rules test' command."""

    @patch('warden.cli.commands.rules.CustomRuleValidator')
    def test_test_rule_no_violations(self, mock_validator_class, cli_runner, temp_rules_file, temp_test_file):
        """Test running a rule that finds no violations."""
        # Mock validator to return no violations
        mock_validator = MagicMock()
        mock_validator.validate_file = AsyncMock(return_value=[])
        mock_validator_class.return_value = mock_validator

        result = cli_runner.invoke(
            app,
            ["test", "test-rule-1", str(temp_test_file), "--config", str(temp_rules_file)]
        )

        assert result.exit_code == 0
        assert "No violations found" in result.stdout or "passes" in result.stdout

    @patch('warden.cli.commands.rules.CustomRuleValidator')
    def test_test_rule_with_violations(self, mock_validator_class, cli_runner, temp_rules_file, temp_test_file):
        """Test running a rule that finds violations."""
        # Create mock violation
        violation = CustomRuleViolation(
            rule_id="test-rule-1",
            rule_name="Test Rule 1",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            is_blocker=True,
            file=str(temp_test_file),
            line=3,
            message="Secret detected",
            code_snippet="secret = 'hardcoded_password'",
            suggestion="Use environment variables"
        )

        # Mock validator to return violations
        mock_validator = MagicMock()
        mock_validator.validate_file = AsyncMock(return_value=[violation])
        mock_validator_class.return_value = mock_validator

        result = cli_runner.invoke(
            app,
            ["test", "test-rule-1", str(temp_test_file), "--config", str(temp_rules_file)]
        )

        assert result.exit_code == 1
        assert "violation" in result.stdout.lower()
        assert "Secret detected" in result.stdout

    def test_test_rule_not_found(self, cli_runner, temp_rules_file, temp_test_file):
        """Test testing a non-existent rule."""
        result = cli_runner.invoke(
            app,
            ["test", "nonexistent-rule", str(temp_test_file), "--config", str(temp_rules_file)]
        )

        assert result.exit_code == 1
        assert "not found" in result.stdout

    def test_test_file_not_found(self, cli_runner, temp_rules_file):
        """Test testing against a non-existent file."""
        result = cli_runner.invoke(
            app,
            ["test", "test-rule-1", "/nonexistent/file.py", "--config", str(temp_rules_file)]
        )

        assert result.exit_code == 1
        assert "not found" in result.stdout

    def test_test_config_not_found(self, cli_runner, temp_test_file):
        """Test testing with non-existent config."""
        result = cli_runner.invoke(
            app,
            ["test", "test-rule-1", str(temp_test_file), "--config", "/nonexistent.yaml"]
        )

        assert result.exit_code == 1
        assert "not found" in result.stdout

    @patch('warden.cli.commands.rules.CustomRuleValidator')
    def test_test_shows_code_snippets(self, mock_validator_class, cli_runner, temp_rules_file, temp_test_file):
        """Test that violations show code snippets."""
        violation = CustomRuleViolation(
            rule_id="test-rule-1",
            rule_name="Test Rule 1",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            is_blocker=True,
            file=str(temp_test_file),
            line=3,
            message="Secret detected",
            code_snippet='secret = "hardcoded_password"',
            suggestion="Use os.getenv()"
        )

        mock_validator = MagicMock()
        mock_validator.validate_file = AsyncMock(return_value=[violation])
        mock_validator_class.return_value = mock_validator

        result = cli_runner.invoke(
            app,
            ["test", "test-rule-1", str(temp_test_file), "--config", str(temp_rules_file)]
        )

        assert result.exit_code == 1
        assert "Code Snippets" in result.stdout or "Line" in result.stdout
        assert "Use os.getenv()" in result.stdout


class TestRulesShowCommand:
    """Test suite for 'warden rules show' command."""

    def test_show_existing_rule(self, cli_runner, temp_rules_file):
        """Test showing details of an existing rule."""
        result = cli_runner.invoke(
            app,
            ["show", "test-rule-1", "--config", str(temp_rules_file)]
        )

        assert result.exit_code == 0
        assert "Test Rule 1" in result.stdout
        assert "test-rule-1" in result.stdout
        assert "Description:" in result.stdout
        assert "Conditions:" in result.stdout

    def test_show_nonexistent_rule(self, cli_runner, temp_rules_file):
        """Test showing a non-existent rule."""
        result = cli_runner.invoke(
            app,
            ["show", "nonexistent-rule", "--config", str(temp_rules_file)]
        )

        assert result.exit_code == 1
        assert "not found" in result.stdout

    def test_show_displays_severity(self, cli_runner, temp_rules_file):
        """Test that show command displays severity."""
        result = cli_runner.invoke(
            app,
            ["show", "test-rule-1", "--config", str(temp_rules_file)]
        )

        assert result.exit_code == 0
        assert "Severity:" in result.stdout
        assert "CRITICAL" in result.stdout

    def test_show_displays_blocker_status(self, cli_runner, temp_rules_file):
        """Test that show command displays blocker status."""
        result = cli_runner.invoke(
            app,
            ["show", "test-rule-1", "--config", str(temp_rules_file)]
        )

        assert result.exit_code == 0
        assert "Blocker:" in result.stdout
        assert "YES" in result.stdout

    def test_show_displays_examples(self, cli_runner, temp_rules_file):
        """Test that show command displays examples."""
        result = cli_runner.invoke(
            app,
            ["show", "test-rule-1", "--config", str(temp_rules_file)]
        )

        assert result.exit_code == 0
        assert "Examples:" in result.stdout
        assert "Invalid:" in result.stdout or "Valid:" in result.stdout

    def test_show_config_not_found(self, cli_runner):
        """Test show command with non-existent config."""
        result = cli_runner.invoke(
            app,
            ["show", "test-rule-1", "--config", "/nonexistent.yaml"]
        )

        assert result.exit_code == 1
        assert "not found" in result.stdout

    def test_show_displays_conditions(self, cli_runner, temp_rules_file):
        """Test that show command displays rule conditions."""
        result = cli_runner.invoke(
            app,
            ["show", "test-rule-1", "--config", str(temp_rules_file)]
        )

        assert result.exit_code == 0
        assert "Conditions:" in result.stdout
        assert "secrets:" in result.stdout or "patterns:" in result.stdout


class TestRulesCommandIntegration:
    """Integration tests for rules command group."""

    def test_help_command(self, cli_runner):
        """Test that help command works."""
        result = cli_runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "validate" in result.stdout
        assert "list" in result.stdout
        assert "test" in result.stdout
        assert "show" in result.stdout

    def test_validate_help(self, cli_runner):
        """Test validate command help."""
        result = cli_runner.invoke(app, ["validate", "--help"])

        assert result.exit_code == 0
        assert "Validate rules configuration file" in result.stdout

    def test_list_help(self, cli_runner):
        """Test list command help."""
        result = cli_runner.invoke(app, ["list", "--help"])

        assert result.exit_code == 0
        assert "List all configured rules" in result.stdout

    def test_test_help(self, cli_runner):
        """Test test command help."""
        result = cli_runner.invoke(app, ["test", "--help"])

        assert result.exit_code == 0
        assert "Test a specific rule against a file" in result.stdout

    def test_show_help(self, cli_runner):
        """Test show command help."""
        result = cli_runner.invoke(app, ["show", "--help"])

        assert result.exit_code == 0
        assert "Show details of a specific rule" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
