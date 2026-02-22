
from pathlib import Path

from warden.mcp.infrastructure.mcp_config_paths import is_safe_to_create_dir


def test_is_safe_to_create_dir_known_config_dirs():
    """Known MCP config directories under home should be safe."""
    home = Path.home()
    assert is_safe_to_create_dir(home / ".config" / "Claude") is True
    assert is_safe_to_create_dir(home / ".cursor") is True
    assert is_safe_to_create_dir(home / ".windsurf") is True


def test_is_safe_to_create_dir_parent_of_config():
    """Parent directories of known config paths should be safe."""
    home = Path.home()
    # .config is parent of .config/Claude/claude_desktop_config.json
    assert is_safe_to_create_dir(home / ".config") is True


def test_is_safe_to_create_dir_unknown_subdir_is_unsafe():
    """Arbitrary subdirectories under home are NOT safe."""
    home = Path.home()
    assert is_safe_to_create_dir(home / ".config" / "myapp") is False
    assert is_safe_to_create_dir(home / "random_dir") is False


def test_is_safe_to_create_dir_traversal_attempts():
    """Attempting to bypass with '..' should be rejected."""
    assert is_safe_to_create_dir(Path("/Users/user/.config/../malicious")) is False
    assert is_safe_to_create_dir(Path("../../AppData")) is False


def test_is_safe_to_create_dir_outside_home():
    """Paths outside user home should always be unsafe."""
    assert is_safe_to_create_dir(Path("/tmp/fakeAppData")) is False
    assert is_safe_to_create_dir(Path("/tmp/malicious.config/payload")) is False


def test_is_safe_to_create_dir_substring_bypass():
    """Substring matching should not fool the safety check."""
    assert is_safe_to_create_dir(Path("/tmp/fakeAppData")) is False
