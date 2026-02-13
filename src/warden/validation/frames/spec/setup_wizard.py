"""
SpecFrame Setup Wizard.

Orchestrates the discovery, validation, and configuration generation
for the SpecFrame platform setup system.

This module ties together platform detection and validation to provide
a streamlined setup experience.

Usage:
    wizard = SetupWizard()
    projects = await wizard.discover_projects_async("../")
    validation = wizard.validate_setup(projects)
    if validation.is_valid:
        config = wizard.generate_config(projects)
        wizard.save_config(config)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

from warden.shared.infrastructure.logging import get_logger
from warden.validation.frames.spec.models import PlatformRole, PlatformType
from warden.validation.frames.spec.platform_detector import (
    DetectedProject,
    PlatformDetector,
)
from warden.validation.frames.spec.validation import (
    IssueSeverity,
    SpecConfigValidator,
    ValidationIssue,
    ValidationResult,
)

logger = get_logger(__name__)


@dataclass
class SetupWizardConfig:
    """
    Configuration for the setup wizard.

    Attributes:
        search_path: Root path to search for projects
        max_depth: Maximum directory depth to search
        min_confidence: Minimum confidence threshold for detection
        exclude_dirs: Directories to skip during detection
        auto_suggest_roles: Automatically suggest roles based on platform type
    """
    search_path: str = ".."
    max_depth: int = 3
    min_confidence: float = 0.7
    exclude_dirs: set[str] | None = None
    auto_suggest_roles: bool = True


@dataclass
class PlatformSetupInput:
    """
    Input for manual platform configuration.

    Used when user wants to manually add a platform
    instead of using auto-detection.

    Attributes:
        name: Platform name (unique identifier)
        path: Path to platform root directory
        platform_type: Platform type (flutter, spring, react, etc.)
        role: Platform role (consumer/provider/both)
        description: Optional description
    """
    name: str
    path: str
    platform_type: str
    role: str
    description: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for configuration."""
        result = {
            "name": self.name,
            "path": self.path,
            "type": self.platform_type,
            "role": self.role,
        }
        if self.description:
            result["description"] = self.description
        return result


class SetupWizard:
    """
    SpecFrame Setup Wizard.

    Orchestrates the complete setup process:
    1. Project discovery (automatic detection)
    2. Validation (configuration validation)
    3. Configuration generation (YAML output)
    4. Configuration persistence (save to .warden/config.yaml)

    The wizard can merge with existing configurations to avoid
    overwriting other frames' settings.
    """

    def __init__(
        self,
        config: SetupWizardConfig | None = None,
        project_root: Path | None = None,
    ):
        """
        Initialize setup wizard.

        Args:
            config: Wizard configuration
            project_root: Project root directory (for config file location)
        """
        self.config = config or SetupWizardConfig()
        self.project_root = project_root or self._find_project_root()

        # Initialize detector and validator
        self.detector = PlatformDetector(
            max_depth=self.config.max_depth,
            min_confidence=self.config.min_confidence,
            exclude_dirs=self.config.exclude_dirs,
        )
        self.validator = SpecConfigValidator(project_root=self.project_root)

        logger.info(
            "setup_wizard_initialized",
            project_root=str(self.project_root),
            search_path=self.config.search_path,
        )

    def _find_project_root(self) -> Path:
        """
        Find project root by looking for .warden directory.

        Returns:
            Path to project root
        """
        current = Path.cwd()
        while current != current.parent:
            if (current / ".warden").exists():
                return current
            current = current.parent

        # Fallback to cwd if .warden not found
        logger.warning(
            "project_root_not_found",
            fallback=str(Path.cwd()),
        )
        return Path.cwd()

    async def discover_projects_async(
        self,
        search_path: str | None = None,
    ) -> list[DetectedProject]:
        """
        Discover projects automatically using platform detection.

        Scans the filesystem and detects projects based on
        signature files and patterns.

        Args:
            search_path: Root path to search (defaults to wizard config)

        Returns:
            List of detected projects with confidence scores

        Raises:
            ValueError: If search path doesn't exist
        """
        search_path = search_path or self.config.search_path

        logger.info(
            "project_discovery_started",
            search_path=search_path,
            max_depth=self.config.max_depth,
        )

        detected = await self.detector.detect_projects_async(search_path)

        # Deduplicate projects (prefer higher confidence)
        deduplicated = self._deduplicate_projects(detected)

        logger.info(
            "project_discovery_completed",
            projects_found=len(deduplicated),
            projects_before_dedup=len(detected),
        )

        return deduplicated

    def validate_setup(
        self,
        projects: list[DetectedProject] | list[PlatformSetupInput],
    ) -> ValidationResult:
        """
        Validate a list of projects or manual platform inputs.

        Converts projects to platform configurations and validates them
        using the SpecConfigValidator.

        Args:
            projects: List of DetectedProject or PlatformSetupInput

        Returns:
            ValidationResult with issues and metadata
        """
        logger.info(
            "setup_validation_started",
            project_count=len(projects),
        )

        # Convert to platform configurations
        platforms = []
        for project in projects:
            if isinstance(project, DetectedProject):
                platforms.append({
                    "name": project.name,
                    "path": project.path,
                    "type": project.platform_type.value,
                    "role": project.role.value,
                })
            elif isinstance(project, PlatformSetupInput):
                platforms.append(project.to_dict())
            else:
                raise TypeError(
                    f"Expected DetectedProject or PlatformSetupInput, "
                    f"got {type(project)}"
                )

        # Validate
        result = self.validator.validate_platforms(platforms)

        logger.info(
            "setup_validation_completed",
            is_valid=result.is_valid,
            errors=result.error_count,
            warnings=result.warning_count,
        )

        return result

    def generate_config(
        self,
        projects: list[DetectedProject] | list[PlatformSetupInput],
        include_metadata: bool = True,
    ) -> dict:
        """
        Generate SpecFrame configuration from projects.

        Creates a configuration dictionary suitable for merging
        into .warden/config.yaml.

        Args:
            projects: List of DetectedProject or PlatformSetupInput
            include_metadata: Include detection metadata (confidence, evidence)

        Returns:
            Configuration dictionary with spec frame settings
        """
        logger.info(
            "config_generation_started",
            project_count=len(projects),
        )

        platforms = []

        for project in projects:
            if isinstance(project, DetectedProject):
                platform = {
                    "name": project.name,
                    "path": project.path,
                    "type": project.platform_type.value,
                    "role": project.role.value,
                }

                # Add metadata if requested
                if include_metadata:
                    platform["_metadata"] = {
                        "confidence": round(project.confidence, 2),
                        "evidence": project.evidence,
                        **{k: v for k, v in project.metadata.items()
                           if k not in ("absolute_path",)},
                    }

            elif isinstance(project, PlatformSetupInput):
                platform = project.to_dict()

            else:
                raise TypeError(
                    f"Expected DetectedProject or PlatformSetupInput, "
                    f"got {type(project)}"
                )

            platforms.append(platform)

        config = {
            "frames": {
                "spec": {
                    "platforms": platforms,
                    # Default settings
                    "gap_analysis": {
                        "fuzzy_threshold": 0.8,
                        "enable_fuzzy": True,
                    },
                    "resilience": {
                        "extraction_timeout": 300,
                        "gap_analysis_timeout": 120,
                    },
                }
            }
        }

        logger.info(
            "config_generation_completed",
            platforms_configured=len(platforms),
        )

        return config

    def save_config(
        self,
        config: dict,
        merge: bool = True,
        backup: bool = True,
    ) -> Path:
        """
        Save configuration to .warden/config.yaml.

        Args:
            config: Configuration dictionary to save
            merge: Merge with existing config (preserves other frames)
            backup: Create backup of existing config before overwriting

        Returns:
            Path to saved configuration file

        Raises:
            IOError: If config file cannot be written
        """
        config_path = self.project_root / ".warden" / "config.yaml"

        logger.info(
            "config_save_started",
            config_path=str(config_path),
            merge=merge,
            backup=backup,
        )

        # Ensure .warden directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing config once (avoids TOCTOU between exists() and read_text())
        existing_content: str | None = None
        try:
            existing_content = config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            pass  # No existing config

        # Backup existing config if requested
        if backup and existing_content is not None:
            backup_path = config_path.with_suffix(".yaml.backup")
            backup_path.write_text(existing_content, encoding="utf-8")
            logger.info(
                "config_backup_created",
                backup_path=str(backup_path),
            )

        # Merge with existing config if requested
        if merge and existing_content is not None:
            try:
                existing = yaml.safe_load(existing_content)
                if existing and isinstance(existing, dict):
                    config = self._merge_configs(existing, config)
                    logger.info("config_merged_with_existing")
            except yaml.YAMLError as e:
                logger.warning(
                    "config_merge_failed",
                    error=str(e),
                    reason="Existing config is invalid YAML, will overwrite",
                )

        # Write configuration
        config_yaml = yaml.dump(
            config,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

        config_path.write_text(config_yaml, encoding="utf-8")

        logger.info(
            "config_saved",
            config_path=str(config_path),
            size_bytes=len(config_yaml),
        )

        return config_path

    def load_existing_config(self) -> dict | None:
        """
        Load existing configuration from .warden/config.yaml.

        Returns:
            Configuration dictionary if exists, None otherwise
        """
        config_path = self.project_root / ".warden" / "config.yaml"

        if not config_path.exists():
            logger.info("no_existing_config_found")
            return None

        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            logger.info(
                "existing_config_loaded",
                config_path=str(config_path),
            )
            return config
        except yaml.YAMLError as e:
            logger.error(
                "config_load_failed",
                config_path=str(config_path),
                error=str(e),
            )
            return None

    def _merge_configs(self, existing: dict, new: dict) -> dict:
        """
        Deep merge new config into existing config.

        Preserves settings from other frames while updating spec frame config.

        Args:
            existing: Existing configuration
            new: New configuration to merge

        Returns:
            Merged configuration
        """
        merged = existing.copy()

        for key, value in new.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                # Deep merge dictionaries
                merged[key] = self._merge_configs(merged[key], value)
            else:
                # Overwrite with new value
                merged[key] = value

        return merged

    def _deduplicate_projects(
        self,
        projects: list[DetectedProject],
    ) -> list[DetectedProject]:
        """
        Deduplicate projects based on path.

        When multiple detections exist for the same path,
        keep the one with highest confidence.

        Args:
            projects: List of detected projects

        Returns:
            Deduplicated list of projects
        """
        path_to_project: dict[str, DetectedProject] = {}

        for project in projects:
            normalized_path = str(Path(project.path).resolve())

            if normalized_path in path_to_project:
                # Keep higher confidence project
                existing = path_to_project[normalized_path]
                if project.confidence > existing.confidence:
                    logger.debug(
                        "project_dedup_replaced",
                        path=normalized_path,
                        old_type=existing.platform_type.value,
                        new_type=project.platform_type.value,
                        old_confidence=existing.confidence,
                        new_confidence=project.confidence,
                    )
                    path_to_project[normalized_path] = project
            else:
                path_to_project[normalized_path] = project

        return list(path_to_project.values())

    def create_interactive_summary(
        self,
        projects: list[DetectedProject],
        validation: ValidationResult | None = None,
    ) -> str:
        """
        Create a human-readable summary of detected projects.

        Useful for CLI/MCP interactive output.

        Args:
            projects: List of detected projects
            validation: Optional validation result

        Returns:
            Formatted summary string
        """
        lines = []
        lines.append("=" * 60)
        lines.append("SpecFrame Setup - Detected Projects")
        lines.append("=" * 60)
        lines.append("")

        if not projects:
            lines.append("No projects detected.")
            lines.append("")
            lines.append("Try:")
            lines.append("  - Increasing search depth (--max-depth)")
            lines.append("  - Lowering confidence threshold (--min-confidence)")
            lines.append("  - Searching a different directory")
            return "\n".join(lines)

        # Group by role
        consumers = [p for p in projects if p.role == PlatformRole.CONSUMER]
        providers = [p for p in projects if p.role == PlatformRole.PROVIDER]
        both = [p for p in projects if p.role == PlatformRole.BOTH]

        if consumers:
            lines.append(f"CONSUMERS ({len(consumers)}):")
            for p in consumers:
                lines.append(
                    f"  - {p.name} ({p.platform_type.value}) "
                    f"- confidence: {p.confidence:.0%}"
                )
                lines.append(f"    path: {p.path}")
            lines.append("")

        if providers:
            lines.append(f"PROVIDERS ({len(providers)}):")
            for p in providers:
                lines.append(
                    f"  - {p.name} ({p.platform_type.value}) "
                    f"- confidence: {p.confidence:.0%}"
                )
                lines.append(f"    path: {p.path}")
            lines.append("")

        if both:
            lines.append(f"BOTH (BFF Pattern) ({len(both)}):")
            for p in both:
                lines.append(
                    f"  - {p.name} ({p.platform_type.value}) "
                    f"- confidence: {p.confidence:.0%}"
                )
                lines.append(f"    path: {p.path}")
            lines.append("")

        # Add validation summary if provided
        if validation:
            lines.append("-" * 60)
            if validation.is_valid:
                lines.append("VALIDATION: PASSED")
            else:
                lines.append(f"VALIDATION: FAILED ({validation.error_count} errors)")

            if validation.issues:
                lines.append("")
                lines.append("Issues:")
                for issue in validation.issues:
                    severity_symbol = {
                        IssueSeverity.ERROR: "ERROR",
                        IssueSeverity.WARNING: "WARN",
                        IssueSeverity.INFO: "INFO",
                    }.get(issue.severity, "?")

                    lines.append(f"  [{severity_symbol}] {issue.message}")
                    if issue.suggestion:
                        lines.append(f"           {issue.suggestion}")

        lines.append("=" * 60)

        return "\n".join(lines)
