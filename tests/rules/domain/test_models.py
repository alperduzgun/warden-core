"""Tests for rule domain models."""

import pytest

from warden.rules.domain.enums import RuleCategory, RuleSeverity
from warden.rules.domain.models import (
    CustomRule,
    CustomRuleViolation,
    ProjectRuleConfig,
)


class TestCustomRule:
    """Test CustomRule model."""

    def test_create_rule(self):
        """Test creating a custom rule."""
        rule = CustomRule(
            id="test-rule",
            name="Test Rule",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            is_blocker=True,
            description="Test description",
            enabled=True,
            type="security",
            conditions={"secrets": {"patterns": ["api_key"]}},
        )

        assert rule.id == "test-rule"
        assert rule.name == "Test Rule"
        assert rule.category == RuleCategory.SECURITY
        assert rule.severity == RuleSeverity.CRITICAL
        assert rule.is_blocker is True
        assert rule.enabled is True

    def test_rule_to_json(self):
        """Test rule serialization to Panel JSON (camelCase)."""
        rule = CustomRule(
            id="test-rule",
            name="Test Rule",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            is_blocker=True,
            description="Test",
            enabled=True,
            type="security",
            conditions={"secrets": {"patterns": ["api_key"]}},
            message="Custom message",
            language=["python"],
            exceptions=["*.test.py"],
        )

        json_data = rule.to_json()

        # Check camelCase conversion
        assert "isBlocker" in json_data
        assert "is_blocker" not in json_data
        assert json_data["isBlocker"] is True

        # Check enum serialization
        assert json_data["category"] == "security"
        assert json_data["severity"] == "critical"

        # Check optional fields
        assert json_data["message"] == "Custom message"
        assert json_data["language"] == ["python"]
        assert json_data["exceptions"] == ["*.test.py"]

    def test_rule_from_json(self):
        """Test rule deserialization from Panel JSON."""
        json_data = {
            "id": "test-rule",
            "name": "Test Rule",
            "category": "security",
            "severity": "critical",
            "isBlocker": True,
            "description": "Test",
            "enabled": True,
            "type": "security",
            "conditions": {"secrets": {"patterns": ["api_key"]}},
            "message": "Custom message",
        }

        rule = CustomRule.from_json(json_data)

        assert rule.id == "test-rule"
        assert rule.is_blocker is True  # camelCase → snake_case
        assert rule.category == RuleCategory.SECURITY
        assert rule.severity == RuleSeverity.CRITICAL
        assert rule.message == "Custom message"

    def test_rule_json_roundtrip(self):
        """Test JSON serialization roundtrip."""
        original = CustomRule(
            id="test-rule",
            name="Test Rule",
            category=RuleCategory.CONVENTION,
            severity=RuleSeverity.HIGH,
            is_blocker=False,
            description="Test",
            enabled=True,
            type="convention",
            conditions={"api": {"routePattern": "^/v[0-9]+/"}},
        )

        json_data = original.to_json()
        parsed = CustomRule.from_json(json_data)

        assert parsed.id == original.id
        assert parsed.is_blocker == original.is_blocker
        assert parsed.category == original.category
        assert parsed.severity == original.severity


class TestCustomRuleViolation:
    """Test CustomRuleViolation model."""

    def test_create_violation(self):
        """Test creating a violation."""
        violation = CustomRuleViolation(
            rule_id="test-rule",
            rule_name="Test Rule",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            is_blocker=True,
            file="test.py",
            line=42,
            message="Violation found",
        )

        assert violation.rule_id == "test-rule"
        assert violation.file == "test.py"
        assert violation.line == 42

    def test_violation_to_json(self):
        """Test violation serialization (camelCase)."""
        violation = CustomRuleViolation(
            rule_id="test-rule",
            rule_name="Test Rule",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            is_blocker=True,
            file="test.py",
            line=42,
            message="Violation found",
            suggestion="Fix it",
            code_snippet="api_key = 'secret'",
        )

        json_data = violation.to_json()

        # Check camelCase
        assert "ruleId" in json_data
        assert "ruleName" in json_data
        assert "isBlocker" in json_data
        assert "codeSnippet" in json_data

        # Check values
        assert json_data["ruleId"] == "test-rule"
        assert json_data["file"] == "test.py"
        assert json_data["line"] == 42


class TestProjectRuleConfig:
    """Test ProjectRuleConfig model."""

    def test_create_config(self):
        """Test creating project config."""
        config = ProjectRuleConfig(
            project_name="test-project",
            language="python",
            framework="fastapi",
        )

        assert config.project_name == "test-project"
        assert config.language == "python"
        assert config.framework == "fastapi"
        assert config.ai_validation_enabled is True

    def test_config_to_json(self):
        """Test config serialization."""
        rule = CustomRule(
            id="rule1",
            name="Rule 1",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            is_blocker=True,
            description="Test",
            enabled=True,
            type="security",
            conditions={},
        )

        config = ProjectRuleConfig(
            project_name="test-project",
            language="python",
            rules=[rule],
            exclude_paths=["node_modules/"],
            exclude_files=["*.test.py"],
        )

        json_data = config.to_json()

        # Check camelCase
        assert "projectName" in json_data
        assert "aiValidationEnabled" in json_data
        assert "excludePaths" in json_data
        assert "excludeFiles" in json_data

        # Check values
        assert json_data["projectName"] == "test-project"
        assert len(json_data["rules"]) == 1
