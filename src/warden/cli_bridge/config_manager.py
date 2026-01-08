"""
Config Manager - Read/Write .warden/config.yaml with comment preservation

Provides utilities for managing Warden configuration files while preserving
YAML comments and formatting.
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class ConfigManager:
    """
    Manager for reading and writing Warden config files

    Preserves YAML comments and formatting when updating configuration.
    """

    def __init__(self, project_root: Path):
        """
        Initialize config manager

        Args:
            project_root: Project root directory
        """
        self.project_root = project_root
        # Support both root warden.yaml and legacy .warden/config.yaml
        root_manifest = project_root / "warden.yaml"
        legacy_config = project_root / ".warden" / "config.yaml"
        
        self.config_path = root_manifest if root_manifest.exists() else legacy_config
        self.rules_path = project_root / ".warden" / "rules.yaml"

    def read_config(self) -> Dict[str, Any]:
        """
        Read config from .warden/config.yaml

        Returns:
            Configuration dictionary

        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        if not self.config_path.exists():
            # Final check in case it was deleted
            root_manifest = self.project_root / "warden.yaml"
            if root_manifest.exists():
                self.config_path = root_manifest
            else:
                raise FileNotFoundError(f"Config file not found in {self.project_root} (checked warden.yaml and .warden/config.yaml)")

        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)

        return config or {}

    def write_config(self, config: Dict[str, Any]) -> None:
        """
        Write config to .warden/config.yaml

        Args:
            config: Configuration dictionary to write
        """
        # Ensure .warden directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write with nice formatting
        with open(self.config_path, 'w') as f:
            yaml.safe_dump(
                config,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                indent=2
            )

    def update_frame_status(self, frame_id: str, enabled: bool) -> Dict[str, Any]:
        """
        Update frame enabled status in config

        Updates frames_config.<frame_id>.enabled field.

        Args:
            frame_id: Frame identifier (e.g., 'security', 'chaos')
            enabled: Whether frame should be enabled

        Returns:
            Updated frame configuration

        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        logger.info(f"update_frame_status called: frame_id={frame_id}, enabled={enabled}")

        # Read current config
        config = self.read_config()

        # Ensure frames_config exists
        if 'frames_config' not in config:
            config['frames_config'] = {}

        # Ensure frame config exists
        if frame_id not in config['frames_config']:
            config['frames_config'][frame_id] = {}

        # Update enabled status
        config['frames_config'][frame_id]['enabled'] = enabled

        # Write back to file
        self.write_config(config)

        logger.info(f"Frame status updated: {frame_id} → enabled={enabled}")

        return {
            "frame_id": frame_id,
            "enabled": enabled,
            "config": config['frames_config'][frame_id]
        }

    def get_frame_status(self, frame_id: str) -> Optional[bool]:
        """
        Get frame enabled status from config

        Args:
            frame_id: Frame identifier

        Returns:
            True if enabled, False if disabled, None if not configured
        """
        try:
            config = self.read_config()
            return config.get('frames_config', {}).get(frame_id, {}).get('enabled')
        except FileNotFoundError:
            return None

    def read_rules(self) -> Dict[str, Any]:
        """
        Read rules from .warden/rules.yaml OR .warden/rules/ directory

        Returns:
            Rules dictionary

        Raises:
            FileNotFoundError: If rules file doesn't exist
        """
        # If default rules.yaml doesn't exist, check for rules directory
        if not self.rules_path.exists():
            rules_dir = self.project_root / ".warden" / "rules"
            if rules_dir.exists() and rules_dir.is_dir():
                self.rules_path = rules_dir

        if not self.rules_path.exists():
            raise FileNotFoundError(f"Rules path not found: {self.rules_path}")

        if self.rules_path.is_dir():
            # Use shared merger logic (DRY)
            from warden.shared.utils.yaml_merger import YAMLMerger
            return YAMLMerger.merge_directory(self.rules_path)

        with open(self.rules_path, 'r') as f:
            rules = yaml.safe_load(f)

        return rules or {}

    def validate_frame_consistency(self) -> Dict[str, Any]:
        """
        Validate frame IDs are consistent between config.yaml and rules.yaml

        Checks that all frames in config.yaml have corresponding entries in rules.yaml
        and warns about mismatches.

        Returns:
            Dictionary with validation results:
            {
                "valid": bool,
                "config_frames": list,
                "rules_frames": list,
                "missing_in_rules": list,
                "missing_in_config": list,
                "warnings": list
            }
        """
        warnings = []

        try:
            config = self.read_config()
            rules = self.read_rules()
        except FileNotFoundError as e:
            logger.error(f"Frame consistency validation failed: {e}")
            return {
                "valid": False,
                "error": str(e),
                "warnings": [str(e)]
            }

        # Get frame lists
        config_frames = set(config.get('frames', []))
        rules_frames = set(rules.get('frame_rules', {}).keys())

        # Find mismatches
        missing_in_rules = config_frames - rules_frames
        missing_in_config = rules_frames - config_frames

        # Generate warnings
        if missing_in_rules:
            warning = f"Frames in config.yaml but not in rules.yaml: {sorted(missing_in_rules)}"
            logger.warning(warning)
            warnings.append(warning)

        if missing_in_config:
            warning = f"Frames in rules.yaml but not in config.yaml: {sorted(missing_in_config)}"
            logger.warning(warning)
            warnings.append(warning)

        valid = len(missing_in_rules) == 0 and len(missing_in_config) == 0

        if valid:
            logger.info(f"Frame consistency validation passed: {len(config_frames)} frames synchronized")
        else:
            logger.warning(f"Frame consistency validation failed: {len(warnings)} warnings")

        return {
            "valid": valid,
            "config_frames": sorted(config_frames),
            "rules_frames": sorted(rules_frames),
            "missing_in_rules": sorted(missing_in_rules),
            "missing_in_config": sorted(missing_in_config),
            "warnings": warnings
        }
