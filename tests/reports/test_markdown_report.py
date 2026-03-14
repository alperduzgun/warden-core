"""Tests for Markdown report generation."""

import tempfile
from pathlib import Path

from warden.reports.generator import ReportGenerator


class TestMarkdownReport:
    """Test Markdown report output."""

    def _make_scan_results(self, findings: list[dict]) -> dict:
        return {
            "quality_score": 8.5,
            "total_findings": len(findings),
            "frame_results": [
                {
                    "frame_id": "security",
                    "status": "completed",
                    "findings": findings,
                }
            ],
        }

    def test_empty_findings(self, tmp_path: Path):
        """Empty findings should produce a PASS report."""
        gen = ReportGenerator()
        out = tmp_path / "report.md"
        gen.generate_markdown_report(self._make_scan_results([]), out)

        content = out.read_text()
        assert "**Status:** PASS" in content
        assert "**Total Findings:** 0" in content
        assert "| security | completed | 0 |" in content

    def test_findings_with_remediation(self, tmp_path: Path):
        """Findings with remediation should include remediation block."""
        findings = [
            {
                "id": "py-no-eval",
                "severity": "critical",
                "message": "eval() is dangerous",
                "location": "app.py:10",
                "remediation": {
                    "description": "Use ast.literal_eval() instead.",
                },
            }
        ]
        gen = ReportGenerator()
        out = tmp_path / "report.md"
        gen.generate_markdown_report(self._make_scan_results(findings), out)

        content = out.read_text()
        assert "**Status:** FAIL" in content
        assert "[CRITICAL] py-no-eval" in content
        assert "`app.py:10`" in content
        assert "ast.literal_eval()" in content

    def test_atomic_write(self, tmp_path: Path):
        """Report should be written atomically."""
        gen = ReportGenerator()
        out = tmp_path / "report.md"
        gen.generate_markdown_report(self._make_scan_results([]), out)

        assert out.exists()
        # No temp files left behind
        temps = list(tmp_path.glob(".tmp_*"))
        assert len(temps) == 0
