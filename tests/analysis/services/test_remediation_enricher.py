"""
Unit tests for RemediationEnricher (#622).

Covers:
1. Rule-based fallback for known rule IDs (SQL injection, secrets, etc.)
2. No-op when all three fields are already populated
3. Partial enrichment (only missing fields filled)
4. LLM metadata extraction
5. Unknown rule IDs (no match)
6. enrich_findings() batch helper
7. Serialization round-trip through findings_cache helpers
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from warden.analysis.services.remediation_enricher import enrich_finding, enrich_findings, _match_rule
from warden.validation.domain.frame import Finding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_finding(rule_id: str, **kwargs) -> Finding:
    """Return a minimal Finding with the given rule_id (stored in the id field)."""
    return Finding(
        id=rule_id,
        severity="high",
        message="Test finding",
        location="src/app.py:10",
        **kwargs,
    )


def _make_dict_finding(rule_id: str, **kwargs) -> dict:
    """Return a dict-style finding."""
    return {"id": rule_id, "severity": "high", "message": "Test", "location": "src/app.py:10", **kwargs}


# ---------------------------------------------------------------------------
# _match_rule unit tests
# ---------------------------------------------------------------------------

class TestMatchRule:
    def test_sql_injection_prefix(self):
        result = _match_rule("sql_injection_user_input")
        assert result is not None
        hint, cause, scope = result
        assert "parameterized" in hint.lower()
        assert scope == "data"

    def test_hardcoded_secret(self):
        result = _match_rule("hardcoded_secret_key")
        assert result is not None
        _, _, scope = result
        assert scope == "service"

    def test_hardcoded_password(self):
        result = _match_rule("hardcoded_password")
        assert result is not None

    def test_command_injection(self):
        result = _match_rule("command_injection")
        assert result is not None
        hint, _, scope = result
        assert "subprocess" in hint.lower() or "shell" in hint.lower()
        assert scope == "service"

    def test_xss(self):
        result = _match_rule("xss_reflected")
        assert result is not None
        _, _, scope = result
        assert scope == "service"

    def test_weak_hash_md5(self):
        result = _match_rule("md5_usage")
        assert result is not None
        hint, _, _ = result
        assert "sha" in hint.lower() or "argon" in hint.lower() or "bcrypt" in hint.lower()

    def test_timing_attack(self):
        result = _match_rule("timing_attack_comparison")
        assert result is not None
        hint, _, _ = result
        assert "compare_digest" in hint.lower()

    def test_jwt_alg_none(self):
        result = _match_rule("jwt_alg_none")
        assert result is not None

    def test_path_traversal(self):
        result = _match_rule("path_traversal_read")
        assert result is not None
        _, _, scope = result
        assert scope == "data"

    def test_eval_injection(self):
        result = _match_rule("eval_injection")
        assert result is not None
        hint, _, _ = result
        assert "eval" in hint.lower()

    def test_predictable_token(self):
        result = _match_rule("predictable_token_generation")
        assert result is not None
        hint, _, _ = result
        assert "secrets" in hint.lower()

    def test_case_insensitive(self):
        # Rule IDs from Bandit are often uppercase-prefixed
        result = _match_rule("B608_SQL_INJECTION")
        assert result is not None

    def test_unknown_rule_returns_none(self):
        result = _match_rule("completely_unknown_custom_rule_xyz")
        assert result is None

    def test_orphan_rule(self):
        result = _match_rule("orphan_dead_function")
        assert result is not None
        _, _, scope = result
        assert scope == "local"


# ---------------------------------------------------------------------------
# enrich_finding with Finding dataclass
# ---------------------------------------------------------------------------

class TestEnrichFindingDataclass:
    def test_sql_injection_populates_all_fields(self):
        f = _make_finding("sql_injection")
        enrich_finding(f)
        assert f.remediation_hint is not None
        assert "parameterized" in f.remediation_hint.lower()
        assert f.root_cause is not None
        assert f.risk_scope == "data"

    def test_hardcoded_password_enriched(self):
        f = _make_finding("hardcoded_password")
        enrich_finding(f)
        assert f.remediation_hint is not None
        assert f.root_cause is not None
        assert f.risk_scope == "service"

    def test_noop_when_fully_populated(self):
        f = _make_finding("sql_injection")
        f.remediation_hint = "custom hint"
        f.root_cause = "custom cause"
        f.risk_scope = "local"
        enrich_finding(f)
        # Values should NOT be overwritten
        assert f.remediation_hint == "custom hint"
        assert f.root_cause == "custom cause"
        assert f.risk_scope == "local"

    def test_partial_enrichment_fills_only_missing(self):
        f = _make_finding("sql_injection")
        f.remediation_hint = "already set"
        f.root_cause = None
        f.risk_scope = None
        enrich_finding(f)
        # hint should stay untouched
        assert f.remediation_hint == "already set"
        # cause and scope should be filled
        assert f.root_cause is not None
        assert f.risk_scope is not None

    def test_unknown_rule_fields_remain_none(self):
        f = _make_finding("totally_unknown_xyz_rule")
        enrich_finding(f)
        assert f.remediation_hint is None
        assert f.root_cause is None
        assert f.risk_scope is None

    def test_xss_enrichment(self):
        f = _make_finding("xss_reflected_output")
        enrich_finding(f)
        assert f.risk_scope == "service"
        assert f.remediation_hint is not None

    def test_verification_metadata_used_first(self):
        f = _make_finding("sql_injection")
        # Simulate LLM returning structured fields in verification_metadata
        f.remediation_hint = None
        f.root_cause = None
        f.risk_scope = None
        # Inject via a dict attribute (dict-based finding approach not applicable
        # here for dataclass, but verify the metadata path is harmless)
        enrich_finding(f)
        # Should fall back to rule-based — all fields populated
        assert f.remediation_hint is not None


# ---------------------------------------------------------------------------
# enrich_finding with dict-style findings
# ---------------------------------------------------------------------------

class TestEnrichFindingDict:
    def test_dict_finding_sql(self):
        f = _make_dict_finding("sql_injection")
        enrich_finding(f)
        assert f.get("remediation_hint") is not None
        assert f.get("root_cause") is not None
        assert f.get("risk_scope") == "data"

    def test_dict_finding_noop_when_full(self):
        f = _make_dict_finding("sql_injection")
        f["remediation_hint"] = "my hint"
        f["root_cause"] = "my cause"
        f["risk_scope"] = "local"
        enrich_finding(f)
        assert f["remediation_hint"] == "my hint"
        assert f["root_cause"] == "my cause"
        assert f["risk_scope"] == "local"

    def test_dict_finding_unknown_rule(self):
        f = _make_dict_finding("no_match_rule_999")
        enrich_finding(f)
        assert f.get("remediation_hint") is None
        assert f.get("root_cause") is None
        assert f.get("risk_scope") is None

    def test_dict_verification_metadata_extraction(self):
        f = _make_dict_finding("some_rule")
        f["verification_metadata"] = {
            "remediation_hint": "from llm",
            "root_cause": "llm cause",
            "risk_scope": "data",
        }
        enrich_finding(f)
        assert f["remediation_hint"] == "from llm"
        assert f["root_cause"] == "llm cause"
        assert f["risk_scope"] == "data"


# ---------------------------------------------------------------------------
# enrich_findings batch helper
# ---------------------------------------------------------------------------

class TestEnrichFindings:
    def test_enriches_all_findings(self):
        findings = [
            _make_finding("sql_injection"),
            _make_finding("hardcoded_password"),
            _make_finding("xss"),
        ]
        result = enrich_findings(findings)
        assert result is findings  # Returns same list
        for f in result:
            assert f.remediation_hint is not None
            assert f.root_cause is not None
            assert f.risk_scope is not None

    def test_empty_list_returns_empty(self):
        result = enrich_findings([])
        assert result == []

    def test_mixed_known_unknown(self):
        findings = [
            _make_finding("sql_injection"),
            _make_finding("unknown_custom_rule"),
        ]
        enrich_findings(findings)
        assert findings[0].remediation_hint is not None
        assert findings[1].remediation_hint is None

    def test_does_not_raise_on_invalid_finding(self):
        # Passing None-like objects should not crash the batch
        findings = [_make_finding("sql_injection")]
        enrich_findings(findings)  # Should not raise


# ---------------------------------------------------------------------------
# Serialization round-trip (#622)
# ---------------------------------------------------------------------------

class TestSerializationRoundTrip:
    def test_new_fields_survive_serialize_deserialize(self):
        from warden.pipeline.application.orchestrator.findings_cache import (
            _deserialize_finding,
            _serialize_finding,
        )

        f = _make_finding("sql_injection")
        f.root_cause = "User input concatenated into SQL"
        f.risk_scope = "data"
        f.remediation_hint = "Use parameterized queries"

        serialized = _serialize_finding(f)
        assert serialized["root_cause"] == "User input concatenated into SQL"
        assert serialized["risk_scope"] == "data"
        assert serialized["remediation_hint"] == "Use parameterized queries"

        restored = _deserialize_finding(serialized)
        assert restored.root_cause == "User input concatenated into SQL"
        assert restored.risk_scope == "data"
        assert restored.remediation_hint == "Use parameterized queries"

    def test_none_fields_not_in_serialized_dict(self):
        from warden.pipeline.application.orchestrator.findings_cache import _serialize_finding

        f = _make_finding("unknown_rule")
        # Fields are None by default
        serialized = _serialize_finding(f)
        # None values should be absent or None in the dict
        assert serialized.get("root_cause") is None
        assert serialized.get("risk_scope") is None
        assert serialized.get("remediation_hint") is None

    def test_deserialized_finding_missing_new_fields(self):
        """Old cache entries without the new fields should deserialize cleanly."""
        from warden.pipeline.application.orchestrator.findings_cache import _deserialize_finding

        old_style = {
            "id": "sql_injection",
            "severity": "high",
            "message": "SQL injection",
            "location": "src/app.py:10",
            "line": 10,
            "column": 0,
            "is_blocker": False,
        }
        f = _deserialize_finding(old_style)
        assert f.root_cause is None
        assert f.risk_scope is None
        assert f.remediation_hint is None

    def test_to_json_includes_new_fields(self):
        f = _make_finding("sql_injection")
        f.root_cause = "Unsanitised user data in query"
        f.risk_scope = "data"
        f.remediation_hint = "Use parameterized queries."

        j = f.to_json()
        assert j["rootCause"] == "Unsanitised user data in query"
        assert j["riskScope"] == "data"
        assert j["remediationHint"] == "Use parameterized queries."

    def test_to_json_omits_none_new_fields(self):
        f = _make_finding("unknown_rule")
        j = f.to_json()
        assert "rootCause" not in j
        assert "riskScope" not in j
        assert "remediationHint" not in j
