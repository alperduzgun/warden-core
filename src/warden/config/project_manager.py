"""Project configuration manager for .warden/project.toml lifecycle."""

from __future__ import annotations

from pathlib import Path

import structlog

from warden.config.project_config import ProjectConfig
from warden.config.project_detector import ProjectDetector

logger = structlog.get_logger(__name__)


class ProjectConfigManager:
    """Manages .warden/project.toml creation, loading, and caching."""

    WARDEN_DIR = ".warden"
    CONFIG_FILE = "project.toml"

    def __init__(self, project_root: Path) -> None:
        """Initialize project config manager.

        Args:
            project_root: Root directory of the project.
        """
        self.project_root = project_root
        self.warden_dir = project_root / self.WARDEN_DIR
        self.config_path = self.warden_dir / self.CONFIG_FILE

    async def load_or_create(self) -> ProjectConfig:
        """Load existing config or create new one with auto-detection.

        This is the main entry point for getting project configuration.
        On first run: Creates .warden/project.toml with detected values.
        On subsequent runs: Loads cached values from .warden/project.toml.

        Returns:
            ProjectConfig with either loaded or newly detected values.
        """
        if self.config_exists():
            logger.info(
                "project_config_found",
                config_path=str(self.config_path),
            )
            return await self.load()

        logger.info(
            "project_config_not_found_detecting",
            project_root=str(self.project_root),
        )
        return await self.create_and_save()

    def config_exists(self) -> bool:
        """Check if .warden/project.toml exists.

        Returns:
            True if config file exists.
        """
        return self.config_path.exists()

    async def load(self) -> ProjectConfig:
        """Load existing project configuration.

        Returns:
            Loaded ProjectConfig.

        Raises:
            FileNotFoundError: If config file doesn't exist.
        """
        logger.debug("loading_project_config", config_path=str(self.config_path))

        config = ProjectConfig.from_file(self.config_path)

        logger.info(
            "project_config_loaded",
            project_name=config.name,
            language=config.language,
            sdk_version=config.sdk_version,
            framework=config.framework,
        )

        return config

    async def create_and_save(self) -> ProjectConfig:
        """Create new project config with auto-detection and save it.

        Detects:
        - Project name (from package.json, pyproject.toml, or directory)
        - Primary language (by counting source files)
        - SDK version (from version files)
        - Framework (using FrameworkDetector)
        - Project type (application, library, microservice, monorepo)

        Returns:
            Newly created ProjectConfig.
        """
        detector = ProjectDetector(self.project_root)

        logger.info("detecting_project_metadata", project_root=str(self.project_root))

        # Auto-detect all metadata
        project_name = detector.get_project_name()
        language = await detector.detect_language()
        sdk_version = await detector.detect_sdk_version(language)
        framework = await detector.detect_framework()
        project_type = await detector.detect_project_type()

        logger.info(
            "project_metadata_detected",
            name=project_name,
            language=language,
            sdk_version=sdk_version,
            framework=framework,
            project_type=project_type,
        )

        # Create config
        config = ProjectConfig(
            name=project_name,
            language=language,
            sdk_version=sdk_version,
            framework=framework,
            project_type=project_type,
        )

        # Validate
        issues = config.validate()
        if issues:
            logger.warning("project_config_validation_issues", issues=issues)

        # Save to .warden/project.toml
        await self.save(config)

        return config

    async def save(self, config: ProjectConfig) -> None:
        """Save project configuration to .warden/project.toml.

        Args:
            config: ProjectConfig to save.
        """
        logger.debug("saving_project_config", config_path=str(self.config_path))

        # Ensure .warden directory exists
        self.warden_dir.mkdir(parents=True, exist_ok=True)

        # Save config
        config.save(self.config_path)

        logger.info(
            "project_config_saved",
            config_path=str(self.config_path),
            project_name=config.name,
        )

    async def update(
        self,
        *,
        name: str | None = None,
        language: str | None = None,
        sdk_version: str | None = None,
        framework: str | None = None,
        project_type: str | None = None,
    ) -> ProjectConfig:
        """Update existing project configuration.

        Args:
            name: New project name (optional).
            language: New language (optional).
            sdk_version: New SDK version (optional).
            framework: New framework (optional).
            project_type: New project type (optional).

        Returns:
            Updated ProjectConfig.

        Raises:
            FileNotFoundError: If config doesn't exist.
        """
        # Load existing config
        config = await self.load()

        # Update fields
        if name is not None:
            config.name = name
        if language is not None:
            config.language = language
        if sdk_version is not None:
            config.sdk_version = sdk_version
        if framework is not None:
            config.framework = framework
        if project_type is not None:
            config.project_type = project_type

        # Validate
        issues = config.validate()
        if issues:
            logger.warning("project_config_validation_issues", issues=issues)

        # Save updated config
        await self.save(config)

        return config

    async def delete(self) -> None:
        """Delete project configuration file.

        This will cause the next run to auto-detect again.
        """
        if self.config_path.exists():
            self.config_path.unlink()
            logger.info("project_config_deleted", config_path=str(self.config_path))

    async def reset(self) -> ProjectConfig:
        """Delete existing config and create fresh one with re-detection.

        Returns:
            Newly created ProjectConfig with fresh detection.
        """
        logger.info("resetting_project_config", project_root=str(self.project_root))

        # Delete existing config
        await self.delete()

        # Create new config with fresh detection
        return await self.create_and_save()
