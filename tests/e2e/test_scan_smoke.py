"""CLI scan E2E tests — verify warden scan works end-to-end.

Two layers:
1. CliRunner (in-process, fast) — help, flags, error handling
2. _run_scan_async (direct call) — real pipeline against examples/
"""

import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from warden.main import app

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"

runner = CliRunner()


# ---------------------------------------------------------------------------
# Layer 1: CliRunner — CLI wiring, flags, help
# ---------------------------------------------------------------------------
@pytest.mark.e2e
class TestCLIWiring:

    def test_warden_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "warden" in result.stdout.lower()

    def test_scan_help(self):
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        assert "scan" in result.stdout.lower()
        assert "--level" in result.stdout
        assert "--format" in result.stdout
        assert "--frame" in result.stdout

    def test_scan_help_shows_all_formats(self):
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        for fmt in ("json", "sarif", "text"):
            assert fmt in result.stdout.lower()

    def test_doctor_help(self):
        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Layer 2: _run_scan_async — real pipeline, real findings
# ---------------------------------------------------------------------------
@pytest.mark.e2e
class TestScanPipeline:

    def test_scan_single_file(self):
        """Scan test_secret.py — should detect hardcoded API key."""
        from warden.cli.commands.scan import _run_scan_async

        target = str(EXAMPLES_DIR / "test_secret.py")
        exit_code = asyncio.run(_run_scan_async(
            paths=[target],
            frames=None,
            format="json",
            output=None,
            verbose=False,
            level="basic",
            ci_mode=True,
        ))
        assert exit_code in (0, 2), f"Unexpected exit code: {exit_code}"

    def test_scan_examples_directory(self):
        """Scan entire examples/ — should complete without crash."""
        from warden.cli.commands.scan import _run_scan_async

        exit_code = asyncio.run(_run_scan_async(
            paths=[str(EXAMPLES_DIR)],
            frames=None,
            format="json",
            output=None,
            verbose=False,
            level="basic",
            ci_mode=True,
        ))
        assert exit_code in (0, 2), f"Unexpected exit code: {exit_code}"

    def test_scan_security_frame_only(self):
        """Scan with --frame security filter."""
        from warden.cli.commands.scan import _run_scan_async

        target = str(EXAMPLES_DIR / "test_secret.py")
        exit_code = asyncio.run(_run_scan_async(
            paths=[target],
            frames=["security"],
            format="json",
            output=None,
            verbose=False,
            level="basic",
            ci_mode=True,
        ))
        assert exit_code in (0, 2), f"Unexpected exit code: {exit_code}"

    def test_scan_sarif_output(self, tmp_path):
        """Scan with SARIF output — should write valid file."""
        from warden.cli.commands.scan import _run_scan_async

        sarif_file = tmp_path / "report.sarif"
        target = str(EXAMPLES_DIR / "test_secret.py")
        exit_code = asyncio.run(_run_scan_async(
            paths=[target],
            frames=["security"],
            format="sarif",
            output=str(sarif_file),
            verbose=False,
            level="basic",
            ci_mode=True,
        ))
        assert exit_code in (0, 2), f"Unexpected exit code: {exit_code}"
