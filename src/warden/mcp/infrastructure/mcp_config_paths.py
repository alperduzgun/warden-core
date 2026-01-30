"""
MCP Configuration Paths

Centralized definition of MCP configuration file paths for AI tools.
Single source of truth - used by both serve.py and health_adapter.py.
"""

from pathlib import Path
from typing import Dict, List


def get_mcp_config_paths() -> Dict[str, Path]:
    """
    Get all known MCP configuration file paths for AI tools.

    Returns:
        Dict mapping tool name to config file path.
    """
    home = Path.home()
    return {
        "Claude Desktop (macOS)": home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        "Claude Desktop (Windows)": home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json",
        "Claude Desktop (Linux)": home / ".config" / "Claude" / "claude_desktop_config.json",
        "Claude Code CLI": home / ".config" / "claude-code" / "mcp_settings.json",
        "Cursor": home / ".cursor" / "mcp.json",
        "Windsurf": home / ".windsurf" / "mcp.json",
        "Gemini (Antigravity)": home / ".gemini" / "antigravity" / "mcp_config.json",
    }


def get_mcp_config_paths_list() -> List[Path]:
    """
    Get list of MCP config paths (without tool names).

    Returns:
        List of Path objects.
    """
    return list(get_mcp_config_paths().values())


# Directories that are safe to create if missing
# These are standard user config directories across platforms
SAFE_CONFIG_DIR_PATTERNS = frozenset({
    ".config",           # Linux/Unix standard
    "Application Support",  # macOS
    "AppData",           # Windows
    ".cursor",           # Cursor IDE
    ".windsurf",         # Windsurf IDE
    ".gemini",           # Google Gemini
})


def is_safe_to_create_dir(path: Path) -> bool:
    """
    Check if a directory is safe to create (user config directories only).

    Args:
        path: Directory path to check.

    Returns:
        True if safe to create, False otherwise.
    """
    path_str = str(path)
    return any(pattern in path_str for pattern in SAFE_CONFIG_DIR_PATTERNS)
