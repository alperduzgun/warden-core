"""
MCP Configuration Paths

Centralized definition of MCP configuration file paths for AI tools.
Single source of truth - used by both serve.py and health_adapter.py.
"""

from pathlib import Path


def get_mcp_config_paths() -> dict[str, Path]:
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


def get_mcp_config_paths_list() -> list[Path]:
    """
    Get list of MCP config paths (without tool names).

    Returns:
        List of Path objects.
    """
    return list(get_mcp_config_paths().values())


# Directories that are safe to create if missing
# These are standard user config directories across platforms
SAFE_CONFIG_DIR_PATTERNS = frozenset(
    {
        ".config",  # Linux/Unix standard
        "Application Support",  # macOS
        "AppData",  # Windows
        ".cursor",  # Cursor IDE
        ".windsurf",  # Windsurf IDE
        ".gemini",  # Google Gemini
    }
)


def is_safe_to_create_dir(path: Path) -> bool:
    """
    Check if a directory is safe to create (user config directories only).

    Args:
        path: Directory path to check.

    Returns:
        True if safe to create, False otherwise.
    """
    try:
        path_resolved = path.resolve()
        home = Path.home().resolve()

        # 1. Sandbox: Must be within user's home directory
        if not path_resolved.is_relative_to(home):
            return False

        # 2. Strict Whitelist: Must be part of a known config file path
        # We only allow creating directories that lead to our known targets
        known_config_files = get_mcp_config_paths().values()

        for config_file in known_config_files:
            # We compare with the parent directory of the config file (the folder we want to exist)
            # We use string comparison for the 'part of' check to handle parents safely
            # or better: check if the config_file's folder is relative to the path we are creating
            # e.g. if we create ~/.config, then ~/.config/Claude is relative to it.

            # Using str check to avoid resolving issues if file doesn't exist
            # But here we are checking the PATH TO CREATE

            try:
                # Get the canonical path for the known config
                target_dir = config_file.parent.resolve()
            except OSError:
                # If target parent doesn't exist, we can't resolve it fully,
                # but we can construct it from home + relative parts if defined that way.
                # In get_mcp_config_paths, they are defined using Path.home() so they are absolute.
                target_dir = config_file.parent

            # Check: Is the target_dir inside (or equal to) the path we are creating?
            # No, we want to create 'path'.
            # So 'target_dir' should be 'path' (we are creating the final dir)
            # OR 'target_dir' should be inside 'path' (we are creating a parent)?
            # NO.
            # If we do `mkdir -p ~/.config/Claude`, we might be creating `~/.config` (parent).
            # So `target_dir` (~/.config/Claude) is relative to `path` (~/.config).

            # Case 1: Creating the final dir (~/.cursor)
            if target_dir == path_resolved:
                return True

            # Case 2: Creating a parent (~/.config for ~/.config/Claude)
            if target_dir.is_relative_to(path_resolved):
                return True

        return False
    except Exception:
        return False
