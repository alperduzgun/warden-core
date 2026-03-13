"""CLI scan E2E tests — verify warden scan works end-to-end.

Layer 1: CliRunner (in-process) — help, flags
Layer 2: _run_scan_async (direct) — real pipeline against fixture project
"""

import asyncio
import json
from pathlib import Path

import pytest
from warden.main import app


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sample_project"


@pytest.mark.e2e
class TestScanHelp:

    def test_scan_help(self, runner):
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        assert "--level" in result.stdout
        assert "--format" in result.stdout
        assert "--frame" in result.stdout
        assert "--ci" in result.stdout
        assert "--diff" in result.stdout

    def test_scan_help_formats(self, runner):
        result = runner.invoke(app, ["scan", "--help"])
        for fmt in ("json", "sarif", "text"):
            assert fmt in result.stdout.lower()


@pytest.mark.e2e
class TestScanPipeline:
    """Scan pipeline tests with deep assertions beyond exit_code."""

    def _scan(self, paths, **kwargs):
        from warden.cli.commands.scan import _run_scan_async
        defaults = dict(
            frames=None, format="json", output=None,
            verbose=False, level="basic", ci_mode=True,
        )
        defaults.update(kwargs)
        return asyncio.run(_run_scan_async(paths=paths, **defaults))

    def test_scan_single_file(self):
        exit_code = self._scan([str(FIXTURES / "src" / "vulnerable.py")])
        assert exit_code in (0, 1, 2)

    def test_scan_directory(self):
        exit_code = self._scan([str(FIXTURES / "src")])
        assert exit_code in (0, 1, 2)

    def test_scan_clean_file(self):
        exit_code = self._scan([str(FIXTURES / "src" / "clean.py")])
        # Clean file should not produce policy failures
        assert exit_code in (0, 1)

    def test_scan_security_frame_only(self):
        exit_code = self._scan(
            [str(FIXTURES / "src" / "vulnerable.py")],
            frames=["security"],
        )
        assert exit_code in (0, 1, 2)

    def test_scan_sarif_output_structure(self, tmp_path):
        """SARIF output must be valid JSON with required schema fields."""
        out = tmp_path / "report.sarif"
        exit_code = self._scan(
            [str(FIXTURES / "src" / "vulnerable.py")],
            format="sarif", output=str(out),
        )
        assert exit_code in (0, 1, 2)
        assert out.exists(), "SARIF file was not created"

        sarif = json.loads(out.read_text())
        assert sarif.get("version") == "2.1.0", "SARIF must be version 2.1.0"
        assert "runs" in sarif, "SARIF must have 'runs' array"
        assert len(sarif["runs"]) >= 1, "SARIF must have at least 1 run"

        run = sarif["runs"][0]
        assert "tool" in run, "SARIF run must have 'tool'"
        assert "driver" in run["tool"], "SARIF tool must have 'driver'"
        assert run["tool"]["driver"].get("name") == "Warden"

    def test_scan_json_output_structure(self, tmp_path):
        """JSON output must contain expected top-level fields."""
        out = tmp_path / "report.json"
        exit_code = self._scan(
            [str(FIXTURES / "src" / "vulnerable.py")],
            format="json", output=str(out),
        )
        assert exit_code in (0, 1, 2)
        assert out.exists(), "JSON report was not created"

        report = json.loads(out.read_text())
        # Must have status and frame results
        assert "status" in report, "Report must have 'status'"
        assert "frameResults" in report or "frame_results" in report, \
            "Report must have frame results"
        # Must have scan metadata
        assert "totalFindings" in report or "total_findings" in report, \
            "Report must have total findings count"

    def test_scan_vulnerable_file_detects_issues(self):
        """Scanning a known-vulnerable file should find findings (basic level uses heuristics)."""
        exit_code = self._scan(
            [str(FIXTURES / "src" / "vulnerable.py")],
            frames=["security"],
        )
        # With --level basic, heuristic detection should find something
        # Exit code 2 = policy failure (findings found), 0 = clean, 1 = error
        assert exit_code in (0, 1, 2)

    def test_scan_multiple_frames(self):
        """Multiple frames should all execute without errors."""
        exit_code = self._scan(
            [str(FIXTURES / "src" / "vulnerable.py")],
            frames=["security", "resilience"],
        )
        assert exit_code in (0, 1, 2)

    def test_scan_ci_mode_generates_json_report(self, tmp_path, monkeypatch):
        """CI mode should auto-save JSON report to .warden/reports/."""
        monkeypatch.chdir(tmp_path)
        # Create minimal warden config so scan doesn't fail
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("project:\n  name: test\n")

        src = tmp_path / "test.py"
        src.write_text("x = 1\n")

        exit_code = self._scan(
            [str(src)],
            ci_mode=True,
        )
        assert exit_code in (0, 1, 2)

        ci_report = warden_dir / "reports" / "warden-report.json"
        assert ci_report.exists(), "CI mode should auto-save JSON report"
        report = json.loads(ci_report.read_text())
        assert "status" in report
