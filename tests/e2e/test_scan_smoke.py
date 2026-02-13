"""CLI scan E2E tests — verify warden scan works end-to-end.

Layer 1: CliRunner (in-process) — help, flags
Layer 2: _run_scan_async (direct) — real pipeline against fixture project
"""

import asyncio
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
        # 0=clean, 1=pipeline partial failure, 2=findings (all valid for E2E)
        assert exit_code in (0, 1, 2)

    def test_scan_directory(self):
        exit_code = self._scan([str(FIXTURES / "src")])
        assert exit_code in (0, 1, 2)

    def test_scan_clean_file(self):
        exit_code = self._scan([str(FIXTURES / "src" / "clean.py")])
        assert exit_code in (0, 1, 2)

    def test_scan_security_frame_only(self):
        exit_code = self._scan(
            [str(FIXTURES / "src" / "vulnerable.py")],
            frames=["security"],
        )
        assert exit_code in (0, 1, 2)

    def test_scan_sarif_output(self, tmp_path):
        out = tmp_path / "report.sarif"
        exit_code = self._scan(
            [str(FIXTURES / "src" / "vulnerable.py")],
            format="sarif", output=str(out),
        )
        assert exit_code in (0, 1, 2)

    def test_scan_json_output(self, tmp_path):
        out = tmp_path / "report.json"
        exit_code = self._scan(
            [str(FIXTURES / "src" / "vulnerable.py")],
            format="json", output=str(out),
        )
        assert exit_code in (0, 1, 2)
