"""
Configuration loader for suppression settings.

This module provides functions to load suppression configuration from YAML files.

Configuration file location: .warden/suppressions.yaml

Example YAML format:
```yaml
enabled: true
globalRules:
  - unused-import
  - magic-number
ignoredFiles:
  - test_*.py
  - migrations/*.py
entries:
  - id: suppress-1
    type: config
    rules:
      - sql-injection
    file: legacy/*.py
    reason: Legacy code, to be refactored
  - id: suppress-2
    type: config
    rules: []
    file: generated/*.py
    reason: Auto-generated code
```
"""

from pathlib import Path
from typing import Optional, Dict, Any
import yaml

from warden.suppression.models import (
    SuppressionConfig,
    SuppressionEntry,
    SuppressionType,
)


DEFAULT_CONFIG_PATH = ".warden/suppressions.yaml"


def load_suppression_config(
    config_path: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> SuppressionConfig:
    """
    Load suppression configuration from YAML file.

    Args:
        config_path: Path to configuration file (optional)
        project_root: Project root directory (optional, used to resolve default path)

    Returns:
        SuppressionConfig with loaded settings

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is malformed
    """
    # Determine config file path
    if config_path is None:
        if project_root is None:
            project_root = Path.cwd()
        config_path = project_root / DEFAULT_CONFIG_PATH

    # Return default config if file doesn't exist
    if not config_path.exists():
        return SuppressionConfig()

    # Load YAML
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {config_path}: {e}") from e

    if data is None:
        return SuppressionConfig()

    # Parse configuration
    return _parse_config(data)


def _parse_config(data: Dict[str, Any]) -> SuppressionConfig:
    """
    Parse configuration from dictionary.

    Args:
        data: Configuration dictionary from YAML

    Returns:
        SuppressionConfig instance

    Raises:
        ValueError: If configuration is malformed
    """
    # Get basic fields (convert camelCase to snake_case)
    enabled = data.get('enabled', True)
    global_rules = data.get('globalRules', [])
    ignored_files = data.get('ignoredFiles', [])

    # Parse entries
    entries = []
    for entry_data in data.get('entries', []):
        entry = _parse_entry(entry_data)
        entries.append(entry)

    return SuppressionConfig(
        enabled=enabled,
        entries=entries,
        global_rules=global_rules,
        ignored_files=ignored_files,
    )


def _parse_entry(data: Dict[str, Any]) -> SuppressionEntry:
    """
    Parse suppression entry from dictionary.

    Args:
        data: Entry dictionary from YAML

    Returns:
        SuppressionEntry instance

    Raises:
        ValueError: If entry is malformed
    """
    # Required fields
    if 'id' not in data:
        raise ValueError("Suppression entry missing required field 'id'")

    entry_id = data['id']

    # Parse type
    type_str = data.get('type', 'config')
    if type_str == 'inline':
        suppression_type = SuppressionType.INLINE
    elif type_str == 'config':
        suppression_type = SuppressionType.CONFIG
    elif type_str == 'global':
        suppression_type = SuppressionType.GLOBAL
    else:
        raise ValueError(f"Invalid suppression type: {type_str}")

    # Optional fields
    rules = data.get('rules', [])
    file_pattern = data.get('file')
    line = data.get('line')
    reason = data.get('reason')
    enabled = data.get('enabled', True)

    return SuppressionEntry(
        id=entry_id,
        type=suppression_type,
        rules=rules,
        file=file_pattern,
        line=line,
        reason=reason,
        enabled=enabled,
    )


def save_suppression_config(
    config: SuppressionConfig,
    config_path: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> None:
    """
    Save suppression configuration to YAML file.

    Args:
        config: SuppressionConfig to save
        config_path: Path to configuration file (optional)
        project_root: Project root directory (optional, used to resolve default path)

    Raises:
        IOError: If file cannot be written
    """
    # Determine config file path
    if config_path is None:
        if project_root is None:
            project_root = Path.cwd()
        config_path = project_root / DEFAULT_CONFIG_PATH

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to dictionary
    data = _config_to_dict(config)

    # Write YAML
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _config_to_dict(config: SuppressionConfig) -> Dict[str, Any]:
    """
    Convert SuppressionConfig to dictionary for YAML export.

    Args:
        config: SuppressionConfig instance

    Returns:
        Dictionary for YAML export
    """
    data: Dict[str, Any] = {
        'enabled': config.enabled,
    }

    # Add global rules if present
    if config.global_rules:
        data['globalRules'] = config.global_rules

    # Add ignored files if present
    if config.ignored_files:
        data['ignoredFiles'] = config.ignored_files

    # Add entries if present
    if config.entries:
        data['entries'] = [_entry_to_dict(entry) for entry in config.entries]

    return data


def _entry_to_dict(entry: SuppressionEntry) -> Dict[str, Any]:
    """
    Convert SuppressionEntry to dictionary for YAML export.

    Args:
        entry: SuppressionEntry instance

    Returns:
        Dictionary for YAML export
    """
    data: Dict[str, Any] = {
        'id': entry.id,
        'type': entry.type.name.lower(),
    }

    # Add optional fields
    if entry.rules:
        data['rules'] = entry.rules

    if entry.file:
        data['file'] = entry.file

    if entry.line is not None:
        data['line'] = entry.line

    if entry.reason:
        data['reason'] = entry.reason

    if not entry.enabled:
        data['enabled'] = entry.enabled

    return data


def create_default_config(
    config_path: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> SuppressionConfig:
    """
    Create default suppression configuration file.

    Args:
        config_path: Path to configuration file (optional)
        project_root: Project root directory (optional)

    Returns:
        Default SuppressionConfig instance
    """
    # Create default config with common patterns
    config = SuppressionConfig(
        enabled=True,
        global_rules=[],
        ignored_files=[
            'test_*.py',
            '*_test.py',
            'tests/*.py',
        ],
        entries=[],
    )

    # Save to file
    save_suppression_config(config, config_path, project_root)

    return config
