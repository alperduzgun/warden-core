"""
Configuration loader for suppression rules.

Loads and saves suppression configuration from .warden/suppressions.yaml.

Functions:
- load_suppression_config: Load configuration from YAML file
- save_suppression_config: Save configuration to YAML file
- create_default_config: Create default configuration with common patterns
"""

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from warden.suppression.models import (
    SuppressionConfig,
    SuppressionEntry,
    SuppressionType,
)


def _to_snake_case(name: str) -> str:
    """Convert camelCase to snake_case."""
    result = []
    for i, char in enumerate(name):
        if char.isupper() and i > 0:
            result.append('_')
            result.append(char.lower())
        else:
            result.append(char.lower())
    return ''.join(result)


def _to_camel_case(name: str) -> str:
    """Convert snake_case to camelCase."""
    parts = name.split('_')
    return parts[0] + ''.join(word.capitalize() for word in parts[1:])


def _convert_keys_to_snake_case(data: Any) -> Any:
    """Recursively convert dictionary keys from camelCase to snake_case."""
    if isinstance(data, dict):
        return {
            _to_snake_case(key): _convert_keys_to_snake_case(value)
            for key, value in data.items()
        }
    elif isinstance(data, list):
        return [_convert_keys_to_snake_case(item) for item in data]
    else:
        return data


def _convert_keys_to_camel_case(data: Any) -> Any:
    """Recursively convert dictionary keys from snake_case to camelCase."""
    if isinstance(data, dict):
        return {
            _to_camel_case(key): _convert_keys_to_camel_case(value)
            for key, value in data.items()
        }
    elif isinstance(data, list):
        return [_convert_keys_to_camel_case(item) for item in data]
    else:
        return data


def load_suppression_config(
    config_path: Path | None = None,
    project_root: Path | None = None,
) -> SuppressionConfig:
    """
    Load suppression configuration from YAML file.

    Args:
        config_path: Path to suppressions.yaml file
        project_root: Project root directory (uses .warden/suppressions.yaml)

    Returns:
        SuppressionConfig loaded from file or default config

    Raises:
        ValueError: If YAML is invalid or missing required fields
    """
    # Determine config path
    if config_path is None:
        if project_root is None:
            raise ValueError("Either config_path or project_root must be provided")
        config_path = project_root / ".warden" / "suppressions.yaml"

    # Security: Prevent path traversal attacks
    if project_root is not None:
        try:
            resolved = config_path.resolve()
            root_resolved = project_root.resolve()
            if not str(resolved).startswith(str(root_resolved)):
                raise ValueError(f"Config path escapes project root: {config_path}")
        except (OSError, ValueError) as e:
            raise ValueError(f"Invalid config path: {e}")

    # If file doesn't exist, return default config
    if not config_path.exists():
        return SuppressionConfig(
            enabled=True,
            entries=[],
            global_rules=[],
            ignored_files=[],
        )

    # Load YAML
    try:
        with open(config_path, encoding='utf-8') as f:
            content = f.read()
            if not content.strip():
                # Empty file
                return SuppressionConfig(enabled=True)
            data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {config_path}: {e}")

    if data is None:
        # Empty YAML
        return SuppressionConfig(enabled=True)

    # Convert camelCase keys to snake_case
    data = _convert_keys_to_snake_case(data)

    # Validate and convert entries
    entries = []
    if 'entries' in data:
        for entry_data in data['entries']:
            # Validate required fields
            if 'id' not in entry_data:
                raise ValueError(
                    f"Missing required field 'id' in suppression entry"
                )

            if 'type' not in entry_data:
                raise ValueError(
                    f"Missing required field 'type' in suppression entry {entry_data.get('id')}"
                )

            # Convert type string to enum
            type_str = entry_data['type']
            try:
                if type_str == 'inline':
                    entry_type = SuppressionType.INLINE
                elif type_str == 'config':
                    entry_type = SuppressionType.CONFIG
                elif type_str == 'global':
                    entry_type = SuppressionType.GLOBAL
                else:
                    raise ValueError(f"Invalid suppression type: {type_str}")
            except Exception:
                raise ValueError(
                    f"Invalid suppression type '{type_str}' in entry {entry_data.get('id')}"
                )

            # Create entry
            entry = SuppressionEntry(
                id=entry_data['id'],
                type=entry_type,
                rules=entry_data.get('rules', []),
                file=entry_data.get('file'),
                line=entry_data.get('line'),
                reason=entry_data.get('reason'),
                enabled=entry_data.get('enabled', True),
            )
            entries.append(entry)

    # Create config
    config = SuppressionConfig(
        enabled=data.get('enabled', True),
        entries=entries,
        global_rules=data.get('global_rules', []),
        ignored_files=data.get('ignored_files', []),
    )

    return config


def save_suppression_config(
    config: SuppressionConfig,
    config_path: Path | None = None,
    project_root: Path | None = None,
) -> None:
    """
    Save suppression configuration to YAML file.

    Args:
        config: SuppressionConfig to save
        config_path: Path to suppressions.yaml file
        project_root: Project root directory (uses .warden/suppressions.yaml)

    Raises:
        ValueError: If neither config_path nor project_root is provided
    """
    # Determine config path
    if config_path is None:
        if project_root is None:
            raise ValueError("Either config_path or project_root must be provided")
        config_path = project_root / ".warden" / "suppressions.yaml"

    # Create parent directory if needed
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to dict
    data: dict[str, Any] = {}
    data['enabled'] = config.enabled

    # Add non-empty lists
    if config.global_rules:
        data['global_rules'] = config.global_rules

    if config.ignored_files:
        data['ignored_files'] = config.ignored_files

    if config.entries:
        entries_data = []
        for entry in config.entries:
            entry_dict = {
                'id': entry.id,
                'type': entry.type.name.lower(),  # Convert enum to lowercase string
            }
            if entry.rules:
                entry_dict['rules'] = entry.rules
            if entry.file:
                entry_dict['file'] = entry.file
            if entry.line is not None:
                entry_dict['line'] = entry.line
            if entry.reason:
                entry_dict['reason'] = entry.reason
            if not entry.enabled:
                entry_dict['enabled'] = entry.enabled
            entries_data.append(entry_dict)
        data['entries'] = entries_data

    # Convert to camelCase
    data = _convert_keys_to_camel_case(data)

    # Save to YAML
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def create_default_config(
    config_path: Path | None = None,
    project_root: Path | None = None,
) -> SuppressionConfig:
    """
    Create and save default suppression configuration.

    Args:
        config_path: Path to suppressions.yaml file
        project_root: Project root directory (uses .warden/suppressions.yaml)

    Returns:
        Default SuppressionConfig

    Raises:
        ValueError: If neither config_path nor project_root is provided
    """
    # Create default config with common ignore patterns
    config = SuppressionConfig(
        enabled=True,
        entries=[],
        global_rules=[],
        ignored_files=[
            'test_*.py',
            '*_test.py',
            'tests/*.py',
            '*/test/*.py',
            '*.test.js',
            '*.test.ts',
            '*.spec.js',
            '*.spec.ts',
            '__pycache__/*',
            '*.pyc',
            'node_modules/*',
            'dist/*',
            'build/*',
        ],
    )

    # Save to file
    save_suppression_config(config, config_path=config_path, project_root=project_root)

    return config
