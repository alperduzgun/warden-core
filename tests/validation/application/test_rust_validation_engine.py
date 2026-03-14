"""Tests for warden.validation.application.rust_validation_engine.

Covers _hit_to_finding conversion with and without remediation data.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from warden.validation.application.rust_validation_engine import (
    RUST_AVAILABLE,
    RustValidationEngine,
)
from warden.validation.domain.frame import Remediation


def _make_hit(rule_id: str = "py-no-eval", file_path: str = "/project/src/app.py",
              line_number: int = 10, column: int = 5, snippet: str = "eval(x)"):
    """Create a mock MatchHit."""
    return SimpleNamespace(
        rule_id=rule_id,
        file_path=file_path,
        line_number=line_number,
        column=column,
        snippet=snippet,
    )


class TestHitToFinding:

    def test_finding_without_remediation(self):
        """When rule has no remediation field, finding.remediation should be None."""
        engine = RustValidationEngine(Path("/project"))
        engine.rules_metadata["py-no-eval"] = {
            "id": "py-no-eval",
            "severity": "critical",
            "message": "eval is bad",
        }

        hit = _make_hit()
        finding = engine._hit_to_finding(hit)

        assert finding.id == "py-no-eval"
        assert finding.severity == "critical"
        assert finding.message == "eval is bad"
        assert finding.remediation is None

    def test_finding_with_remediation(self):
        """When rule has remediation field, finding should include Remediation object."""
        engine = RustValidationEngine(Path("/project"))
        engine.rules_metadata["py-no-eval"] = {
            "id": "py-no-eval",
            "severity": "critical",
            "message": "eval is bad",
            "remediation": "Use ast.literal_eval() instead.",
        }

        hit = _make_hit()
        finding = engine._hit_to_finding(hit)

        assert finding.remediation is not None
        assert isinstance(finding.remediation, Remediation)
        assert finding.remediation.description == "Use ast.literal_eval() instead."
        assert finding.remediation.code == ""

    def test_finding_location_and_line(self):
        """Finding should have correct location, line, and column."""
        engine = RustValidationEngine(Path("/project"))
        engine.rules_metadata["test-rule"] = {"severity": "high", "message": "test"}

        hit = _make_hit(rule_id="test-rule", line_number=42, column=8)
        finding = engine._hit_to_finding(hit)

        assert finding.location == "src/app.py:42"
        assert finding.line == 42
        assert finding.column == 8

    def test_finding_is_blocker_for_critical(self):
        """Critical severity findings should be blockers."""
        engine = RustValidationEngine(Path("/project"))
        engine.rules_metadata["crit"] = {"severity": "critical", "message": "x"}

        finding = engine._hit_to_finding(_make_hit(rule_id="crit"))
        assert finding.is_blocker is True

    def test_finding_not_blocker_for_high(self):
        """High severity findings should not be blockers."""
        engine = RustValidationEngine(Path("/project"))
        engine.rules_metadata["high"] = {"severity": "high", "message": "x"}

        finding = engine._hit_to_finding(_make_hit(rule_id="high"))
        assert finding.is_blocker is False

    def test_message_override(self):
        """message_override parameter should take precedence."""
        engine = RustValidationEngine(Path("/project"))
        engine.rules_metadata["r1"] = {"severity": "low", "message": "original"}

        finding = engine._hit_to_finding(_make_hit(rule_id="r1"), message_override="custom msg")
        assert finding.message == "custom msg"

    def test_unknown_rule_uses_defaults(self):
        """Unknown rule_id should use default severity and message."""
        engine = RustValidationEngine(Path("/project"))
        # No rules_metadata entry

        finding = engine._hit_to_finding(_make_hit(rule_id="unknown-rule"))
        assert finding.severity == "high"  # default
        assert "unknown-rule" in finding.message
        assert finding.remediation is None


@pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust engine not available")
class TestLoadRulesFromYaml:

    @pytest.mark.asyncio
    async def test_loads_rules_with_remediation(self, tmp_path):
        """YAML rules with remediation field should be stored in metadata."""
        yaml_content = """
rules:
  - id: test-rule
    pattern: "dangerous()"
    severity: high
    message: "Don't use dangerous()"
    remediation: "Use safe() instead."
"""
        yaml_file = tmp_path / "rules.yaml"
        yaml_file.write_text(yaml_content)

        engine = RustValidationEngine(tmp_path)
        await engine.load_rules_from_yaml_async(yaml_file)

        assert "test-rule" in engine.rules_metadata
        assert engine.rules_metadata["test-rule"]["remediation"] == "Use safe() instead."

    @pytest.mark.asyncio
    async def test_loads_rules_without_remediation(self, tmp_path):
        """YAML rules without remediation field should work fine."""
        yaml_content = """
rules:
  - id: test-rule
    pattern: "bad()"
    severity: medium
    message: "Avoid bad()"
"""
        yaml_file = tmp_path / "rules.yaml"
        yaml_file.write_text(yaml_content)

        engine = RustValidationEngine(tmp_path)
        await engine.load_rules_from_yaml_async(yaml_file)

        assert "test-rule" in engine.rules_metadata
        assert "remediation" not in engine.rules_metadata["test-rule"]
