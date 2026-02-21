"""
Tests for MachineContext population from taint analysis data.

Verifies:
1. _aggregate_findings enriches findings with taint-derived MachineContext
2. _enrich_finding_with_taint matches line numbers correctly
3. Graceful handling when no taint data available
4. LLM structured output enrichment via _machine_context
"""

from dataclasses import dataclass, field

import pytest

from warden.validation.domain.check import CheckFinding, CheckResult, CheckSeverity
from warden.validation.domain.frame import Finding, MachineContext
from warden.validation.frames.security.frame import SecurityFrame


@dataclass
class MockTaintSource:
    name: str
    node_type: str = "call"
    line: int = 10
    confidence: float = 0.9


@dataclass
class MockTaintSink:
    name: str
    sink_type: str = "SQL-value"
    line: int = 45


@dataclass
class MockTaintPath:
    source: MockTaintSource
    sink: MockTaintSink
    transformations: list = field(default_factory=list)
    sanitizers: list = field(default_factory=list)
    is_sanitized: bool = False
    confidence: float = 0.85


class TestAggregateFindings:
    """Test _aggregate_findings with taint context."""

    def setup_method(self):
        self.frame = SecurityFrame.__new__(SecurityFrame)
        self.frame.frame_id = "security"

    def test_aggregate_without_taint_context(self):
        """Findings aggregate normally when no taint context."""
        check_results = [
            CheckResult(
                check_id="sql-injection",
                check_name="SQL Injection Check",
                passed=False,
                findings=[
                    CheckFinding(
                        check_id="sql-injection",
                        check_name="SQL Injection",
                        severity=CheckSeverity.HIGH,
                        message="SQL injection detected",
                        location="app.py:45",
                        suggestion="Use parameterized queries",
                    ),
                ],
            ),
        ]
        findings = self.frame._aggregate_findings(check_results)
        assert len(findings) == 1
        assert findings[0].machine_context is None

    def test_aggregate_with_matching_taint(self):
        """Findings get MachineContext when taint path matches."""
        taint_paths = [
            MockTaintPath(
                source=MockTaintSource(name="request.args", line=10),
                sink=MockTaintSink(name="cursor.execute", sink_type="SQL-value", line=45),
                transformations=["f-string"],
                sanitizers=[],
            ),
        ]

        check_results = [
            CheckResult(
                check_id="sql-injection",
                check_name="SQL Injection Check",
                passed=False,
                findings=[
                    CheckFinding(
                        check_id="sql-injection",
                        check_name="SQL Injection",
                        severity=CheckSeverity.HIGH,
                        message="SQL injection at cursor.execute",
                        location="app.py:45",
                        suggestion="Use parameterized queries",
                    ),
                ],
            ),
        ]

        findings = self.frame._aggregate_findings(check_results, taint_context=taint_paths)
        assert len(findings) == 1

        mc = findings[0].machine_context
        assert mc is not None
        assert mc.source == "request.args (line 10)"
        assert mc.sink == "cursor.execute (line 45)"
        assert mc.sink_type == "SQL-value"
        assert "request.args" in mc.data_flow_path
        assert "cursor.execute" in mc.data_flow_path

    def test_aggregate_no_match_when_line_far(self):
        """No MachineContext when taint path lines don't match finding."""
        taint_paths = [
            MockTaintPath(
                source=MockTaintSource(name="request.args", line=10),
                sink=MockTaintSink(name="cursor.execute", line=200),
            ),
        ]

        check_results = [
            CheckResult(
                check_id="xss",
                check_name="XSS Check",
                passed=False,
                findings=[
                    CheckFinding(
                        check_id="xss",
                        check_name="XSS",
                        severity=CheckSeverity.MEDIUM,
                        message="XSS detected",
                        location="app.py:100",
                        suggestion="Escape output",
                    ),
                ],
            ),
        ]

        findings = self.frame._aggregate_findings(check_results, taint_context=taint_paths)
        assert len(findings) == 1
        assert findings[0].machine_context is None

    def test_aggregate_with_sanitizers(self):
        """MachineContext includes sanitizer information."""
        taint_paths = [
            MockTaintPath(
                source=MockTaintSource(name="request.body", line=5),
                sink=MockTaintSink(name="render_html", sink_type="HTML-content", line=20),
                sanitizers=["html.escape", "bleach.clean"],
                is_sanitized=False,
                confidence=0.7,
            ),
        ]

        check_results = [
            CheckResult(
                check_id="xss",
                check_name="XSS Check",
                passed=False,
                findings=[
                    CheckFinding(
                        check_id="xss",
                        check_name="XSS",
                        severity=CheckSeverity.MEDIUM,
                        message="Potential XSS",
                        location="views.py:20",
                        suggestion="Sanitize output",
                    ),
                ],
            ),
        ]

        findings = self.frame._aggregate_findings(check_results, taint_context=taint_paths)
        mc = findings[0].machine_context
        assert mc is not None
        assert mc.sanitizers_applied == ["html.escape", "bleach.clean"]


class TestEnrichFindingWithTaint:
    """Test the static _enrich_finding_with_taint method."""

    def test_enrich_by_line_number(self):
        """Finding with line number near taint sink gets enriched."""
        finding = Finding(
            id="security-sql-injection-0",
            severity="high",
            message="SQL injection",
            location="app.py:45",
            line=45,
        )

        taint_paths = [
            MockTaintPath(
                source=MockTaintSource(name="user_input", line=10),
                sink=MockTaintSink(name="db.execute", sink_type="SQL-value", line=44),
            ),
        ]

        SecurityFrame._enrich_finding_with_taint(finding, taint_paths)
        assert finding.machine_context is not None
        assert finding.machine_context.vulnerability_class == "sql-injection"

    def test_enrich_extracts_line_from_location(self):
        """Line number extracted from location string when .line is 0."""
        finding = Finding(
            id="security-xss-0",
            severity="medium",
            message="XSS detected",
            location="template.html:30",
            line=0,
        )

        taint_paths = [
            MockTaintPath(
                source=MockTaintSource(name="request.args", line=5),
                sink=MockTaintSink(name="render", sink_type="HTML-content", line=30),
            ),
        ]

        SecurityFrame._enrich_finding_with_taint(finding, taint_paths)
        assert finding.machine_context is not None

    def test_enrich_no_match_returns_none(self):
        """No enrichment when no taint paths match."""
        finding = Finding(
            id="security-secrets-0",
            severity="high",
            message="Hardcoded secret",
            location="config.py:5",
            line=5,
        )

        taint_paths = [
            MockTaintPath(
                source=MockTaintSource(name="env", line=100),
                sink=MockTaintSink(name="log", line=200),
            ),
        ]

        SecurityFrame._enrich_finding_with_taint(finding, taint_paths)
        assert finding.machine_context is None

    def test_enrich_handles_empty_taint_paths(self):
        """Empty taint paths list should not crash."""
        finding = Finding(
            id="security-test-0",
            severity="low",
            message="Test",
            location="test.py:1",
            line=1,
        )

        SecurityFrame._enrich_finding_with_taint(finding, [])
        assert finding.machine_context is None

    def test_enrich_handles_malformed_taint_path(self):
        """Taint path without expected attributes should be skipped."""
        finding = Finding(
            id="security-test-0",
            severity="low",
            message="Test",
            location="test.py:10",
            line=10,
        )

        # Malformed path without source/sink attributes
        SecurityFrame._enrich_finding_with_taint(finding, [{"not": "a taint path"}])
        assert finding.machine_context is None


class TestMachineContextSerialization:
    """Test MachineContext to_json output."""

    def test_to_json_full(self):
        """Full MachineContext serializes all fields."""
        mc = MachineContext(
            vulnerability_class="sql-injection",
            source="request.args['id']",
            sink="cursor.execute()",
            sink_type="SQL-value",
            data_flow_path=["get_user", "validate", "query_db"],
            sanitizers_applied=["escape_sql"],
            suggested_fix_type="parameterized_query",
        )

        result = mc.to_json()
        assert result["vulnerability_class"] == "sql-injection"
        assert result["source"] == "request.args['id']"
        assert result["sink"] == "cursor.execute()"
        assert result["sink_type"] == "SQL-value"
        assert len(result["data_flow_path"]) == 3
        assert result["sanitizers_applied"] == ["escape_sql"]

    def test_to_json_minimal(self):
        """Minimal MachineContext only has vulnerability_class."""
        mc = MachineContext(vulnerability_class="xss")
        result = mc.to_json()
        assert result == {"vulnerability_class": "xss"}
        assert "source" not in result
        assert "sink" not in result


class TestLLMStructuredOutput:
    """Test _enrich_findings_from_llm on base provider."""

    def test_enrich_from_llm_with_source_sink(self):
        """LLM output with source/sink gets _machine_context attached."""
        from warden.llm.providers.base import ILlmClient

        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "message": "SQL injection",
                    "line_number": 45,
                    "detail": "User input flows to SQL query",
                    "source": "request.args['id'] (line 14)",
                    "sink": "cursor.execute() (line 45)",
                    "data_flow": ["get_user_id", "validate_input", "db.query"],
                },
            ],
        }

        ILlmClient._enrich_findings_from_llm(parsed)

        mc = parsed["findings"][0].get("_machine_context")
        assert mc is not None
        assert mc["source"] == "request.args['id'] (line 14)"
        assert mc["sink"] == "cursor.execute() (line 45)"
        assert len(mc["data_flow_path"]) == 3

    def test_enrich_from_llm_without_structured_fields(self):
        """LLM output without source/sink/data_flow has no _machine_context."""
        from warden.llm.providers.base import ILlmClient

        parsed = {
            "findings": [
                {
                    "severity": "medium",
                    "message": "Potential issue",
                    "line_number": 10,
                    "detail": "Details",
                },
            ],
        }

        ILlmClient._enrich_findings_from_llm(parsed)

        assert "_machine_context" not in parsed["findings"][0]

    def test_enrich_from_llm_partial_fields(self):
        """LLM output with only source (no sink/data_flow) still enriches."""
        from warden.llm.providers.base import ILlmClient

        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "message": "Tainted input",
                    "line_number": 5,
                    "detail": "User input",
                    "source": "request.form['name']",
                },
            ],
        }

        ILlmClient._enrich_findings_from_llm(parsed)

        mc = parsed["findings"][0].get("_machine_context")
        assert mc is not None
        assert mc["source"] == "request.form['name']"
        assert mc["sink"] is None
        assert mc["data_flow_path"] == []

    def test_enrich_handles_invalid_types(self):
        """Non-string source/sink and non-list data_flow get sanitized."""
        from warden.llm.providers.base import ILlmClient

        parsed = {
            "findings": [
                {
                    "severity": "high",
                    "message": "Test",
                    "line_number": 1,
                    "detail": "Test",
                    "source": 12345,  # Not a string
                    "sink": {"complex": "object"},  # Not a string
                    "data_flow": "not a list",  # Not a list
                },
            ],
        }

        ILlmClient._enrich_findings_from_llm(parsed)

        mc = parsed["findings"][0].get("_machine_context")
        assert mc is not None
        assert isinstance(mc["source"], str)
        assert isinstance(mc["sink"], str)
        assert mc["data_flow_path"] == []

    def test_enrich_empty_findings(self):
        """Empty findings list should not crash."""
        from warden.llm.providers.base import ILlmClient

        parsed = {"findings": []}
        ILlmClient._enrich_findings_from_llm(parsed)
        assert parsed["findings"] == []
