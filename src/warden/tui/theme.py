"""
Warden TUI Color Theme

GitHub-inspired dark theme matching the Warden Panel.
Colors extracted from warden-panel/tailwind.config.js
"""

from textual.design import ColorSystem


class WardenColorSystem(ColorSystem):
    """
    Warden color system matching the Panel's GitHub-inspired dark theme

    All color values are extracted from:
    /Users/alper/Documents/Development/warden-panel/tailwind.config.js
    """

    # Backgrounds
    bg_primary = "#0d1117"      # Main background
    bg_secondary = "#161b22"    # Sidebar, cards
    bg_tertiary = "#21262d"     # Hover states

    # Borders
    border_default = "#30363d"  # Default border
    border_subtle = "#21262d"   # Subtle borders

    # Text
    text_primary = "#e6edf3"    # Primary text
    text_secondary = "#8b949e"  # Secondary text
    text_tertiary = "#484f58"   # Muted text

    # Status colors
    success = "#3fb950"         # Success green
    success_dark = "#238636"    # Dark green
    success_hover = "#2ea043"   # Hover green

    warning = "#d29922"         # Warning yellow

    error = "#f85149"           # Error red
    error_dark = "#b62324"      # Dark red
    error_hover = "#da3633"     # Hover red

    high = "#db6161"            # High severity

    info = "#58a6ff"            # Info blue
    info_dark = "#1f6feb"       # Dark blue

    purple = "#a371f7"          # Purple
    pink = "#f778ba"            # Pink
    orange = "#f78166"          # Orange (active tab)


# Textual CSS variable mapping
WARDEN_THEME_COLORS = f"""
/* Warden GitHub-inspired Dark Theme */

* {{
    /* Backgrounds */
    --warden-bg-primary: {WardenColorSystem.bg_primary};
    --warden-bg-secondary: {WardenColorSystem.bg_secondary};
    --warden-bg-tertiary: {WardenColorSystem.bg_tertiary};

    /* Borders */
    --warden-border: {WardenColorSystem.border_default};
    --warden-border-subtle: {WardenColorSystem.border_subtle};

    /* Text */
    --warden-text: {WardenColorSystem.text_primary};
    --warden-text-secondary: {WardenColorSystem.text_secondary};
    --warden-text-tertiary: {WardenColorSystem.text_tertiary};

    /* Status */
    --warden-success: {WardenColorSystem.success};
    --warden-success-dark: {WardenColorSystem.success_dark};
    --warden-warning: {WardenColorSystem.warning};
    --warden-error: {WardenColorSystem.error};
    --warden-error-dark: {WardenColorSystem.error_dark};
    --warden-high: {WardenColorSystem.high};
    --warden-info: {WardenColorSystem.info};
    --warden-info-dark: {WardenColorSystem.info_dark};
    --warden-purple: {WardenColorSystem.purple};
    --warden-pink: {WardenColorSystem.pink};
    --warden-orange: {WardenColorSystem.orange};
}}

/* Override Textual defaults with Warden colors */
* {{
    scrollbar-background: {WardenColorSystem.bg_tertiary};
    scrollbar-color: {WardenColorSystem.info};
    scrollbar-color-hover: {WardenColorSystem.info_dark};
    scrollbar-color-active: {WardenColorSystem.success};
}}

Screen {{
    background: {WardenColorSystem.bg_primary};
}}
"""


def get_severity_color(severity: str) -> str:
    """
    Get color for severity level

    Args:
        severity: Severity level (critical, high, medium, low)

    Returns:
        Hex color code
    """
    severity_map = {
        "critical": WardenColorSystem.error,
        "high": WardenColorSystem.high,
        "medium": WardenColorSystem.warning,
        "low": WardenColorSystem.info,
    }
    return severity_map.get(severity.lower(), WardenColorSystem.text_secondary)


def get_status_color(status: str) -> str:
    """
    Get color for status

    Args:
        status: Status (pass, warning, fail, success, error)

    Returns:
        Hex color code
    """
    status_map = {
        "pass": WardenColorSystem.success,
        "success": WardenColorSystem.success,
        "warning": WardenColorSystem.warning,
        "fail": WardenColorSystem.error,
        "error": WardenColorSystem.error,
        "running": WardenColorSystem.info,
        "pending": WardenColorSystem.text_secondary,
    }
    return status_map.get(status.lower(), WardenColorSystem.text_primary)
