"""
Config discovery system for Warden.

Hierarchy:
1. .warden/config.yaml (Project-specific, highest priority)
2. ~/.warden/config.yaml (User-global)
3. Built-in templates (Fallback)
"""
from pathlib import Path
from typing import Optional

from warden.config.domain.models import PipelineConfig
from warden.config.yaml_parser import parse_yaml


def find_project_config(start_path: Path) -> Optional[Path]:
    """
    Find .warden/config.yaml in project directory.

    Walks up from start_path to find .warden/config.yaml.
    Stops at git root or filesystem root.

    Args:
        start_path: Starting directory (usually cwd or file path)

    Returns:
        Path to .warden/config.yaml or None
    """
    current = start_path.resolve()

    # Walk up to find .warden/config.yaml
    while current != current.parent:
        warden_config = current / ".warden" / "config.yaml"
        if warden_config.exists():
            return warden_config

        # Stop at git root
        if (current / ".git").exists():
            warden_config = current / ".warden" / "config.yaml"
            if warden_config.exists():
                return warden_config
            break

        current = current.parent

    return None


def find_user_config() -> Optional[Path]:
    """
    Find user-global config at ~/.warden/config.yaml.

    Returns:
        Path to ~/.warden/config.yaml or None
    """
    user_config = Path.home() / ".warden" / "config.yaml"
    return user_config if user_config.exists() else None


def get_builtin_template(name: str) -> Optional[Path]:
    """
    Get built-in template path.

    Args:
        name: Template name (e.g., 'security-only', 'full-validation')

    Returns:
        Path to template or None
    """
    # Handle .yaml extension
    if not name.endswith('.yaml'):
        name = f"{name}.yaml"

    template_path = Path(__file__).parent / "templates" / name
    return template_path if template_path.exists() else None


def discover_config(
    start_path: Optional[Path] = None,
    template_name: Optional[str] = None
) -> Optional[PipelineConfig]:
    """
    Discover and load pipeline config with hierarchy.

    Priority:
    1. Explicit template_name (if provided)
    2. .warden/config.yaml (project-specific)
    3. ~/.warden/config.yaml (user-global)
    4. Built-in 'quick-scan' template (fallback)

    Args:
        start_path: Starting directory for search (default: cwd)
        template_name: Explicit template name (overrides discovery)

    Returns:
        PipelineConfig or None
    """
    start_path = start_path or Path.cwd()

    # 1. Explicit template override
    if template_name:
        template_path = get_builtin_template(template_name)
        if template_path:
            return parse_yaml(str(template_path))

    # 2. Project-specific config
    project_config = find_project_config(start_path)
    if project_config:
        return parse_yaml(str(project_config))

    # 3. User-global config
    user_config = find_user_config()
    if user_config:
        return parse_yaml(str(user_config))

    # 4. Fallback to built-in template
    fallback = get_builtin_template("quick-scan")
    if fallback:
        return parse_yaml(str(fallback))

    return None


def get_config_source(
    start_path: Optional[Path] = None,
    template_name: Optional[str] = None
) -> str:
    """
    Get human-readable config source description.

    Args:
        start_path: Starting directory for search
        template_name: Explicit template name

    Returns:
        Config source description
    """
    start_path = start_path or Path.cwd()

    if template_name:
        return f"template:{template_name}"

    project_config = find_project_config(start_path)
    if project_config:
        return f"project:{project_config.parent.parent.name}"

    user_config = find_user_config()
    if user_config:
        return "user-global"

    return "builtin:quick-scan"
