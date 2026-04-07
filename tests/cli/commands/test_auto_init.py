"""
Tests for auto-init .warden/ on first scan (#534).
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock


def test_auto_init_creates_warden_dir(tmp_path):
    """First scan on a project without .warden/ should create it."""
    from warden.cli.commands.scan import _auto_init_warden_dir

    console = MagicMock()
    _auto_init_warden_dir(tmp_path, console)

    assert (tmp_path / ".warden").is_dir()
    assert (tmp_path / ".warden" / "config.yaml").is_file()
    console.print.assert_called_once()  # user-visible notice printed


def test_auto_init_config_contains_defaults(tmp_path):
    """Auto-created config.yaml must have sensible defaults."""
    from warden.cli.commands.scan import _auto_init_warden_dir

    _auto_init_warden_dir(tmp_path, MagicMock())

    content = (tmp_path / ".warden" / "config.yaml").read_text()
    assert "frames:" in content
    assert "security" in content
    assert tmp_path.name in content  # project name injected


def test_auto_init_idempotent(tmp_path):
    """Second call must not overwrite an existing config."""
    from warden.cli.commands.scan import _auto_init_warden_dir

    console = MagicMock()
    # First call
    _auto_init_warden_dir(tmp_path, console)
    original_mtime = (tmp_path / ".warden" / "config.yaml").stat().st_mtime

    # Second call — must be a no-op
    _auto_init_warden_dir(tmp_path, console)
    assert (tmp_path / ".warden" / "config.yaml").stat().st_mtime == original_mtime
    assert console.print.call_count == 1  # only printed once
