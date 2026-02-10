"""CLI scan smoke tests — verify scan machinery works end-to-end.

Uses examples/ directory as real scan target.
Uses _run_scan_async directly (bypasses Typer/Click make_metavar bug).
"""

import asyncio
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.e2e
class TestScanImports:
    """Verify CLI modules load without errors."""

    def test_app_import(self):
        """Main Typer app imports successfully."""
        from warden.main import app
        assert app is not None

    def test_scan_command_import(self):
        """Scan command function imports."""
        from warden.cli.commands.scan import scan_command
        assert callable(scan_command)

    def test_warden_bridge_import(self):
        """WardenBridge (scan engine) imports."""
        from warden.cli.commands.scan import WardenBridge
        assert WardenBridge is not None


@pytest.mark.e2e
class TestScanDirect:
    """Test _run_scan_async directly against examples/ directory."""

    def test_scan_single_file(self):
        """Scan a single example file end-to-end."""
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
        # 0=clean, 2=findings — both valid
        assert exit_code in (0, 2), f"Unexpected exit code: {exit_code}"

    def test_scan_examples_dir(self):
        """Scan entire examples/ directory end-to-end."""
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

    def test_scan_with_security_frame(self):
        """Scan with only SecurityFrame against known-vulnerable file."""
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
