"""Tests for rule enums."""

import pytest

from warden.rules.domain.enums import RuleCategory, RuleSeverity


class TestRuleCategory:
    """Test RuleCategory enum."""

    def test_all_categories_defined(self):
        """Test all categories are defined."""
        assert RuleCategory.SECURITY.value == "security"
        assert RuleCategory.CONVENTION.value == "convention"
        assert RuleCategory.PERFORMANCE.value == "performance"
        assert RuleCategory.CUSTOM.value == "custom"

    def test_category_from_string(self):
        """Test creating category from string."""
        assert RuleCategory("security") == RuleCategory.SECURITY
        assert RuleCategory("convention") == RuleCategory.CONVENTION
        assert RuleCategory("performance") == RuleCategory.PERFORMANCE
        assert RuleCategory("custom") == RuleCategory.CUSTOM

    def test_invalid_category_raises_error(self):
        """Test invalid category raises ValueError."""
        with pytest.raises(ValueError):
            RuleCategory("invalid")


class TestRuleSeverity:
    """Test RuleSeverity enum."""

    def test_all_severities_defined(self):
        """Test all severities are defined."""
        assert RuleSeverity.CRITICAL.value == "critical"
        assert RuleSeverity.HIGH.value == "high"
        assert RuleSeverity.MEDIUM.value == "medium"
        assert RuleSeverity.LOW.value == "low"

    def test_severity_from_string(self):
        """Test creating severity from string."""
        assert RuleSeverity("critical") == RuleSeverity.CRITICAL
        assert RuleSeverity("high") == RuleSeverity.HIGH
        assert RuleSeverity("medium") == RuleSeverity.MEDIUM
        assert RuleSeverity("low") == RuleSeverity.LOW

    def test_invalid_severity_raises_error(self):
        """Test invalid severity raises ValueError."""
        with pytest.raises(ValueError):
            RuleSeverity("invalid")
