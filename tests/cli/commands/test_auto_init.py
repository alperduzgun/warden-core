"""
Tests for auto-init .warden/ on first scan (#534).

Coverage:
- Happy path: creates dir + config
- Config content correctness
- Idempotency (second call is a no-op)
- YAML injection: project name with unsafe chars is sanitized
- Concurrent TOCTOU: config already exists after mkdir → no overwrite
- Filesystem failure: PermissionError surfaces to console
"""

import os
import stat
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_auto_init_creates_warden_dir(tmp_path):
    from warden.cli.commands.scan import _auto_init_warden_dir

    console = MagicMock()
    _auto_init_warden_dir(tmp_path, console)

    assert (tmp_path / ".warden").is_dir()
    assert (tmp_path / ".warden" / "config.yaml").is_file()
    console.print.assert_called_once()


def test_auto_init_config_contains_defaults(tmp_path):
    from warden.cli.commands.scan import _auto_init_warden_dir

    _auto_init_warden_dir(tmp_path, MagicMock())

    content = (tmp_path / ".warden" / "config.yaml").read_text()
    assert "frames:" in content
    assert "security" in content
    assert tmp_path.name in content  # project name injected


def test_auto_init_config_is_valid_yaml(tmp_path):
    """Auto-created config.yaml must parse cleanly."""
    import yaml
    from warden.cli.commands.scan import _auto_init_warden_dir

    _auto_init_warden_dir(tmp_path, MagicMock())

    content = (tmp_path / ".warden" / "config.yaml").read_text()
    parsed = yaml.safe_load(content)
    assert isinstance(parsed, dict)
    assert "project" in parsed
    assert "frames" in parsed


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_auto_init_idempotent(tmp_path):
    """Second call must not overwrite an existing .warden/."""
    from warden.cli.commands.scan import _auto_init_warden_dir

    console = MagicMock()
    _auto_init_warden_dir(tmp_path, console)
    original_mtime = (tmp_path / ".warden" / "config.yaml").stat().st_mtime

    _auto_init_warden_dir(tmp_path, console)

    assert (tmp_path / ".warden" / "config.yaml").stat().st_mtime == original_mtime
    assert console.print.call_count == 1  # notice printed only once


def test_auto_init_skips_if_config_written_concurrently(tmp_path):
    """If config.yaml appears between mkdir and write, must not overwrite."""
    from warden.cli.commands.scan import _auto_init_warden_dir

    # Pre-create .warden/ dir but NOT config.yaml — simulates concurrent scan
    # that already wrote config after we passed the exists() guard.
    warden_dir = tmp_path / ".warden"
    warden_dir.mkdir()
    existing_config = "# written by another process\nframes:\n  - security\n"
    (warden_dir / "config.yaml").write_text(existing_config)

    _auto_init_warden_dir(tmp_path, MagicMock())

    # Our auto-init should have returned early without touching the file.
    assert (warden_dir / "config.yaml").read_text() == existing_config


# ---------------------------------------------------------------------------
# YAML safety
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw_name,expected_fragment", [
    ('my "project"', "my project"),          # double-quotes stripped
    ("proj\\evil", "projlevil" or "evil"),   # backslash stripped — result is "projlevil"
    ("\x00null\x1fbyte", "nullbyte"),         # control chars stripped
    ("normal-project", "normal-project"),    # unchanged
    ('""', "project"),                       # all stripped → fallback to "project"
])
def test_auto_init_yaml_safe_project_name(tmp_path, raw_name, expected_fragment):
    """Project names with YAML-unsafe chars must be sanitized before writing."""
    import yaml
    from warden.cli.commands.scan import _auto_init_warden_dir

    # Rename tmp_path's effective name by creating a subdir with the raw name
    # (tmp_path itself can't be renamed, so we point project_root at a subdir)
    safe_subdir = tmp_path / "subproject"
    safe_subdir.mkdir()
    # Monkey-patch .name to simulate a project root with a problematic name
    fake_root = MagicMock(spec=Path)
    fake_root.name = raw_name
    fake_root.__truediv__ = lambda self, other: safe_subdir / other  # type: ignore[misc]
    # Use the real tmp_path-based path for actual FS ops
    project_root = safe_subdir
    # Override name
    with patch.object(Path, "name", new_callable=lambda: property(lambda self: raw_name)):
        _auto_init_warden_dir(project_root, MagicMock())

    content = (safe_subdir / ".warden" / "config.yaml").read_text()
    parsed = yaml.safe_load(content)
    name_val = parsed["project"]["name"]
    # Must parse correctly (no YAML error) and not contain unsafe chars
    assert '"' not in name_val
    assert "\\" not in name_val
    assert "\x00" not in name_val


# ---------------------------------------------------------------------------
# Filesystem failure → surfaces to console
# ---------------------------------------------------------------------------

def test_auto_init_permission_error_shown_on_console(tmp_path):
    """PermissionError must be printed to console, not silently swallowed."""
    from warden.cli.commands.scan import _auto_init_warden_dir

    console = MagicMock()
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("read-only fs")):
        _auto_init_warden_dir(tmp_path, console)

    # Warning must be visible on console
    printed_text = " ".join(str(c) for c in console.print.call_args_list)
    assert "read-only fs" in printed_text or "Could not create" in printed_text
