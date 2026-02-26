"""
Tests for SARIF remediation fixes output (#197).

Validates that findings with remediation data produce correct SARIF fixes
entries, and findings without remediation are unaffected.
"""

import json
import tempfile
from pathlib import Path

import pytest

from warden.reports.generator import ReportGenerator


class TestSarifRemediationFixes:
    """Test SARIF fixes array generation from remediation data."""

    def _make_scan_results(self, findings: list[dict]) -> dict:
        """Helper to wrap findings in a scan_results structure."""
        return {
            "frame_results": [
                {
                    "frame_id": "test-frame",
                    "frame_name": "Test Frame",
                    "findings": findings,
                }
            ]
        }

    def test_finding_with_remediation_produces_fixes(self):
        """A finding with remediation.code should emit a SARIF fixes array."""
        findings = [
            {
                "id": "sql-injection",
                "severity": "critical",
                "message": "SQL injection vulnerability",
                "location": "app.py:42",
                "line": 42,
                "column": 1,
                "remediation": {
                    "description": "Use parameterized queries",
                    "code": "cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))",
                },
            }
        ]
        scan_results = self._make_scan_results(findings)

        with tempfile.NamedTemporaryFile(suffix=".sarif", delete=False) as f:
            out_path = Path(f.name)

        try:
            gen = ReportGenerator()
            gen.generate_sarif_report(scan_results, out_path)

            sarif = json.loads(out_path.read_text())
            results = sarif["runs"][0]["results"]
            assert len(results) >= 1

            result = results[0]
            assert "fixes" in result
            fixes = result["fixes"]
            assert len(fixes) == 1

            fix = fixes[0]
            assert fix["description"]["text"] == "Use parameterized queries"

            changes = fix["artifactChanges"]
            assert len(changes) == 1
            assert changes[0]["artifactLocation"]["uri"] == "app.py"

            replacements = changes[0]["replacements"]
            assert len(replacements) == 1
            assert replacements[0]["deletedRegion"]["startLine"] == 42
            assert (
                replacements[0]["insertedContent"]["text"]
                == "cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))"
            )
        finally:
            out_path.unlink(missing_ok=True)

    def test_finding_without_remediation_has_no_fixes(self):
        """A finding with no remediation should not have a fixes key."""
        findings = [
            {
                "id": "todo-fixme",
                "severity": "low",
                "message": "TODO comment found",
                "location": "utils.py:10",
                "line": 10,
                "column": 1,
            }
        ]
        scan_results = self._make_scan_results(findings)

        with tempfile.NamedTemporaryFile(suffix=".sarif", delete=False) as f:
            out_path = Path(f.name)

        try:
            gen = ReportGenerator()
            gen.generate_sarif_report(scan_results, out_path)

            sarif = json.loads(out_path.read_text())
            results = sarif["runs"][0]["results"]
            assert len(results) >= 1

            result = results[0]
            assert "fixes" not in result
        finally:
            out_path.unlink(missing_ok=True)

    def test_finding_with_empty_remediation_code_has_no_fixes(self):
        """A finding with remediation but empty code should not have fixes."""
        findings = [
            {
                "id": "empty-catch",
                "severity": "high",
                "message": "Empty catch block",
                "location": "handler.py:20",
                "line": 20,
                "column": 1,
                "remediation": {
                    "description": "Log the error or handle it properly",
                    "code": "",
                },
            }
        ]
        scan_results = self._make_scan_results(findings)

        with tempfile.NamedTemporaryFile(suffix=".sarif", delete=False) as f:
            out_path = Path(f.name)

        try:
            gen = ReportGenerator()
            gen.generate_sarif_report(scan_results, out_path)

            sarif = json.loads(out_path.read_text())
            results = sarif["runs"][0]["results"]
            assert len(results) >= 1

            result = results[0]
            assert "fixes" not in result
        finally:
            out_path.unlink(missing_ok=True)

    def test_finding_with_unified_diff_in_remediation(self):
        """Remediation with unified_diff should still emit fixes from code."""
        findings = [
            {
                "id": "xss-reflected",
                "severity": "critical",
                "message": "Reflected XSS",
                "location": "views.py:55",
                "line": 55,
                "column": 8,
                "remediation": {
                    "description": "Escape HTML output",
                    "code": "from html import escape\noutput = escape(user_input)",
                    "unified_diff": "--- original\n+++ fixed\n@@ -1 +1,2 @@\n-output = user_input\n+from html import escape\n+output = escape(user_input)",
                },
            }
        ]
        scan_results = self._make_scan_results(findings)

        with tempfile.NamedTemporaryFile(suffix=".sarif", delete=False) as f:
            out_path = Path(f.name)

        try:
            gen = ReportGenerator()
            gen.generate_sarif_report(scan_results, out_path)

            sarif = json.loads(out_path.read_text())
            result = sarif["runs"][0]["results"][0]

            assert "fixes" in result
            assert result["fixes"][0]["artifactChanges"][0]["replacements"][0][
                "insertedContent"
            ]["text"] == "from html import escape\noutput = escape(user_input)"
        finally:
            out_path.unlink(missing_ok=True)
