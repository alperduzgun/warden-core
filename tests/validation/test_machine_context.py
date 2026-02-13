"""Tests for MachineContext and ExploitEvidence."""
import pytest
from warden.validation.domain.frame import (
    Finding, MachineContext, ExploitEvidence, Remediation
)


class TestMachineContext:
    def test_basic_creation(self):
        mc = MachineContext(vulnerability_class="sql-injection")
        assert mc.vulnerability_class == "sql-injection"
        assert mc.source is None
        assert mc.data_flow_path == []

    def test_full_creation(self):
        mc = MachineContext(
            vulnerability_class="sql-injection",
            source="request.args['id']",
            sink="cursor.execute()",
            sink_type="SQL-value",
            data_flow_path=["request.args", "user_id", "query"],
            sanitizers_applied=[],
            suggested_fix_type="parameterized_query",
            related_files=["db.py"]
        )
        assert mc.sink == "cursor.execute()"

    def test_to_json_minimal(self):
        mc = MachineContext(vulnerability_class="xss-reflected")
        j = mc.to_json()
        assert j == {"vulnerability_class": "xss-reflected"}
        assert "source" not in j  # None fields omitted

    def test_to_json_full(self):
        mc = MachineContext(
            vulnerability_class="sql-injection",
            source="request.args['id']",
            sink="cursor.execute()",
            sink_type="SQL-value",
            data_flow_path=["a", "b"],
            suggested_fix_type="parameterized_query",
        )
        j = mc.to_json()
        assert j["source"] == "request.args['id']"
        assert j["data_flow_path"] == ["a", "b"]


class TestExploitEvidence:
    def test_basic_creation(self):
        ee = ExploitEvidence(
            witness_payload="' OR 1=1 --",
            attack_vector="URL parameter 'id'"
        )
        assert ee.witness_payload == "' OR 1=1 --"

    def test_to_json_html_escapes(self):
        ee = ExploitEvidence(
            witness_payload="<script>alert(1)</script>",
            attack_vector="<img onerror='alert(1)'>"
        )
        j = ee.to_json()
        assert "<script>" not in j["witness_payload"]
        assert "&lt;script&gt;" in j["witness_payload"]

    def test_confidence(self):
        ee = ExploitEvidence(
            witness_payload="test",
            attack_vector="test",
            confidence=0.95
        )
        assert ee.to_json()["confidence"] == 0.95


class TestFindingWithContext:
    def test_finding_without_context(self):
        f = Finding(id="f1", severity="high", message="test", location="file.py:1")
        j = f.to_json()
        assert "machineContext" not in j
        assert "exploitEvidence" not in j

    def test_finding_with_machine_context(self):
        mc = MachineContext(vulnerability_class="sql-injection", sink="cursor.execute()")
        f = Finding(id="f1", severity="critical", message="SQLi", location="db.py:45", machine_context=mc)
        j = f.to_json()
        assert "machineContext" in j
        assert j["machineContext"]["vulnerability_class"] == "sql-injection"

    def test_finding_with_exploit_evidence(self):
        ee = ExploitEvidence(witness_payload="' OR 1=1 --", attack_vector="URL param")
        f = Finding(id="f1", severity="critical", message="SQLi", location="db.py:45", exploit_evidence=ee)
        j = f.to_json()
        assert "exploitEvidence" in j

    def test_finding_with_both(self):
        mc = MachineContext(vulnerability_class="sql-injection")
        ee = ExploitEvidence(witness_payload="test", attack_vector="test")
        f = Finding(
            id="f1", severity="critical", message="SQLi", location="db.py:45",
            machine_context=mc, exploit_evidence=ee
        )
        j = f.to_json()
        assert "machineContext" in j
        assert "exploitEvidence" in j

    def test_backward_compat_to_dict(self):
        f = Finding(id="f1", severity="high", message="test", location="file.py:1")
        assert f.to_dict() == f.to_json()
