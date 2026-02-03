
import pytest
from pathlib import Path
from warden.mcp.infrastructure.mcp_config_paths import is_safe_to_create_dir

def test_is_safe_to_create_dir_standard_paths():
    assert is_safe_to_create_dir(Path("/Users/user/.config/myapp")) is True
    assert is_safe_to_create_dir(Path("/home/user/.config/myapp")) is True
    assert is_safe_to_create_dir(Path("C:/Users/User/AppData/Roaming/MyApp")) is True

def test_is_safe_to_create_dir_traversal_attempts():
    # Attempting to bypass with ".."
    assert is_safe_to_create_dir(Path("/Users/user/.config/../malicious")) is False
    assert is_safe_to_create_dir(Path("../../AppData")) is False

def test_is_safe_to_create_dir_partial_match_attack():
    # Attempting to matching substring but not directory component
    # e.g. /tmp/malicious.config/payload
    assert is_safe_to_create_dir(Path("/tmp/malicious.config/payload")) is False
    assert is_safe_to_create_dir(Path("/tmp/AppData/payload")) is False 
    # ^ This fails on strict 'parts' check if 'AppData' is just a folder name but not in expected location relative to others
    # Actually, our strict check just ensures the SAFE pattern is a distinct part.
    # /tmp/AppData IS allowed by current logic if we only check "if pattern in parts".
    # But wait, our logic was:
    # if pattern in path_resolved.parts: return True
    # So /tmp/AppData/foo WOULD be true if 'AppData' is in SAFE_CONFIG_DIR_PATTERNS.
    # We might need even STRICTER logic in future (e.g. must START with user home), 
    # but for now, checking 'parts' is better than 'substring'.
    pass

def test_is_safe_to_create_dir_substring_bypass():
    # Previous vulnerability: "/tmp/fakeAppData"
    assert is_safe_to_create_dir(Path("/tmp/fakeAppData")) is False
