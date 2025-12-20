"""
Plugin loader for community validation frames.

Discovers and loads frames from:
1. Entry points (PyPI packages)
2. Local plugin directory (~/.warden/plugins/)
3. Environment variable (WARDEN_PLUGIN_PATHS)
"""

import os
import sys
import yaml
import importlib.util
from pathlib import Path
from typing import List, Type, Dict, Any
from dataclasses import dataclass

from warden.validation.domain.frame import ValidationFrame, ValidationFrameError
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PluginMetadata:
    """Plugin metadata from plugin.yaml."""

    name: str
    id: str
    version: str
    author: str
    description: str
    category: str
    priority: str
    is_blocker: bool = False
    min_warden_version: str | None = None
    max_warden_version: str | None = None
    config_schema: Dict[str, Any] | None = None
    applicability: List[str] | None = None
    tags: List[str] | None = None


class PluginLoader:
    """
    Discovers and loads validation frame plugins.

    Discovery order:
    1. Built-in frames (warden.validation.frames.*)
    2. Entry point plugins (PyPI packages)
    3. Local directory plugins (~/.warden/plugins/)
    4. Environment variable plugins (WARDEN_PLUGIN_PATHS)
    """

    def __init__(self) -> None:
        """Initialize plugin loader."""
        self.discovered_frames: List[Type[ValidationFrame]] = []
        self.plugin_metadata: Dict[str, PluginMetadata] = {}

    def discover_all(self) -> List[Type[ValidationFrame]]:
        """
        Discover all available frames from all sources.

        Returns:
            List of ValidationFrame classes

        Raises:
            PluginLoadError: If plugin discovery fails critically
        """
        logger.info("plugin_discovery_started")

        # 1. Discover built-in frames
        builtin_frames = self._discover_builtin_frames()
        logger.info(
            "builtin_frames_discovered",
            count=len(builtin_frames),
            frames=[f.__name__ for f in builtin_frames],
        )

        # 2. Discover entry point plugins (PyPI)
        entry_point_frames = self._discover_entry_point_plugins()
        logger.info(
            "entry_point_plugins_discovered",
            count=len(entry_point_frames),
            frames=[f.__name__ for f in entry_point_frames],
        )

        # 3. Discover local directory plugins
        local_frames = self._discover_local_plugins()
        logger.info(
            "local_plugins_discovered",
            count=len(local_frames),
            frames=[f.__name__ for f in local_frames],
        )

        # 4. Discover environment variable plugins
        env_frames = self._discover_env_plugins()
        logger.info(
            "env_plugins_discovered",
            count=len(env_frames),
            frames=[f.__name__ for f in env_frames],
        )

        # Combine all discovered frames
        all_frames = builtin_frames + entry_point_frames + local_frames + env_frames

        # Remove duplicates (by frame_id)
        unique_frames = self._deduplicate_frames(all_frames)

        logger.info(
            "plugin_discovery_complete",
            total_discovered=len(all_frames),
            unique_frames=len(unique_frames),
        )

        self.discovered_frames = unique_frames
        return unique_frames

    def _discover_builtin_frames(self) -> List[Type[ValidationFrame]]:
        """
        Discover built-in frames from warden.validation.frames.

        Returns:
            List of built-in ValidationFrame classes
        """
        frames: List[Type[ValidationFrame]] = []

        try:
            # Import built-in frames module
            from warden.validation import frames as frames_module

            # Get all ValidationFrame subclasses
            for attr_name in dir(frames_module):
                attr = getattr(frames_module, attr_name)

                # Check if it's a ValidationFrame subclass
                if (
                    isinstance(attr, type)
                    and issubclass(attr, ValidationFrame)
                    and attr is not ValidationFrame
                ):
                    frames.append(attr)
                    logger.debug(
                        "builtin_frame_discovered",
                        frame=attr.__name__,
                        module=attr.__module__,
                    )

        except ImportError:
            logger.warning("builtin_frames_module_not_found")

        return frames

    def _discover_entry_point_plugins(self) -> List[Type[ValidationFrame]]:
        """
        Discover frames via Python entry points (PyPI packages).

        Entry point group: "warden.frames"

        Example pyproject.toml:
            [tool.poetry.plugins."warden.frames"]
            mycompany_security = "warden_frame_mycompany.frame:MyCompanySecurityFrame"

        Returns:
            List of ValidationFrame classes from entry points
        """
        frames: List[Type[ValidationFrame]] = []

        try:
            # Try importlib.metadata (Python 3.10+)
            try:
                from importlib.metadata import entry_points
            except ImportError:
                # Fallback to pkg_resources (older Python)
                import pkg_resources

                eps = pkg_resources.iter_entry_points("warden.frames")
                for entry_point in eps:
                    try:
                        frame_class = entry_point.load()
                        self._validate_frame_class(frame_class)
                        frames.append(frame_class)
                        logger.info(
                            "entry_point_plugin_loaded",
                            plugin=entry_point.name,
                            frame=frame_class.__name__,
                        )
                    except Exception as e:
                        logger.error(
                            "entry_point_plugin_load_failed",
                            plugin=entry_point.name,
                            error=str(e),
                        )
                return frames

            # Python 3.10+ path
            eps = entry_points(group="warden.frames")
            for entry_point in eps:
                try:
                    frame_class = entry_point.load()
                    self._validate_frame_class(frame_class)
                    frames.append(frame_class)
                    logger.info(
                        "entry_point_plugin_loaded",
                        plugin=entry_point.name,
                        frame=frame_class.__name__,
                    )
                except Exception as e:
                    logger.error(
                        "entry_point_plugin_load_failed",
                        plugin=entry_point.name,
                        error=str(e),
                    )

        except Exception as e:
            logger.error("entry_point_discovery_failed", error=str(e))

        return frames

    def _discover_local_plugins(self) -> List[Type[ValidationFrame]]:
        """
        Discover frames from local plugin directory.

        Default: ~/.warden/plugins/

        Each plugin:
            ~/.warden/plugins/mycompany-security/
                plugin.yaml
                frame.py

        Returns:
            List of ValidationFrame classes from local plugins
        """
        frames: List[Type[ValidationFrame]] = []

        # Get plugin directory
        plugin_dir = Path.home() / ".warden" / "plugins"

        if not plugin_dir.exists():
            logger.debug("local_plugin_directory_not_found", path=str(plugin_dir))
            return frames

        # Scan for plugins
        for plugin_path in plugin_dir.iterdir():
            if not plugin_path.is_dir():
                continue

            manifest_path = plugin_path / "plugin.yaml"
            if not manifest_path.exists():
                logger.warning(
                    "plugin_manifest_missing",
                    plugin_dir=plugin_path.name,
                    expected_file="plugin.yaml",
                )
                continue

            try:
                # Load plugin
                frame_class = self._load_local_plugin(plugin_path, manifest_path)
                frames.append(frame_class)
                logger.info(
                    "local_plugin_loaded",
                    plugin=plugin_path.name,
                    frame=frame_class.__name__,
                )

            except Exception as e:
                logger.error(
                    "local_plugin_load_failed",
                    plugin=plugin_path.name,
                    error=str(e),
                )

        return frames

    def _load_local_plugin(
        self, plugin_path: Path, manifest_path: Path
    ) -> Type[ValidationFrame]:
        """
        Load a single local plugin.

        Args:
            plugin_path: Path to plugin directory
            manifest_path: Path to plugin.yaml

        Returns:
            ValidationFrame class

        Raises:
            PluginLoadError: If plugin cannot be loaded
        """
        # Load manifest
        with open(manifest_path) as f:
            manifest_data = yaml.safe_load(f)

        metadata = PluginMetadata(
            name=manifest_data["name"],
            id=manifest_data["id"],
            version=manifest_data["version"],
            author=manifest_data["author"],
            description=manifest_data["description"],
            category=manifest_data["category"],
            priority=manifest_data["priority"],
            is_blocker=manifest_data.get("is_blocker", False),
            min_warden_version=manifest_data.get("compatibility", {}).get(
                "min_version"
            ),
            max_warden_version=manifest_data.get("compatibility", {}).get(
                "max_version"
            ),
        )

        # Import frame module
        frame_module_path = plugin_path / "frame.py"
        if not frame_module_path.exists():
            raise PluginLoadError(f"frame.py not found in {plugin_path}")

        # Dynamic import
        spec = importlib.util.spec_from_file_location(
            f"warden_plugin_{metadata.id}", frame_module_path
        )
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Cannot load module from {frame_module_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        # Find ValidationFrame subclass
        frame_class = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, ValidationFrame)
                and attr is not ValidationFrame
            ):
                frame_class = attr
                break

        if frame_class is None:
            raise PluginLoadError(
                f"No ValidationFrame subclass found in {frame_module_path}"
            )

        # Validate
        self._validate_frame_class(frame_class)

        # Store metadata
        self.plugin_metadata[metadata.id] = metadata

        return frame_class

    def _discover_env_plugins(self) -> List[Type[ValidationFrame]]:
        """
        Discover frames from environment variable paths.

        Environment: WARDEN_PLUGIN_PATHS=/opt/plugins:/home/user/custom-frames

        Returns:
            List of ValidationFrame classes from env paths
        """
        frames: List[Type[ValidationFrame]] = []

        env_paths = os.getenv("WARDEN_PLUGIN_PATHS", "")
        if not env_paths:
            return frames

        for path_str in env_paths.split(":"):
            path = Path(path_str.strip())
            if not path.exists():
                logger.warning("env_plugin_path_not_found", path=str(path))
                continue

            # Same logic as local plugins
            # (simplified for now - in production, implement full scan)
            logger.info("env_plugin_path_scanned", path=str(path))

        return frames

    def _validate_frame_class(self, frame_class: Type[ValidationFrame]) -> None:
        """
        Validate that frame class meets requirements.

        Args:
            frame_class: Frame class to validate

        Raises:
            PluginValidationError: If validation fails
        """
        # Check it's a subclass
        if not issubclass(frame_class, ValidationFrame):
            raise PluginValidationError(
                f"{frame_class.__name__} must inherit from ValidationFrame"
            )

        # Check required attributes
        required_attrs = ["name", "description", "category", "priority"]
        for attr in required_attrs:
            if not hasattr(frame_class, attr):
                raise PluginValidationError(
                    f"{frame_class.__name__} missing required attribute: {attr}"
                )

        # Check execute method
        if not hasattr(frame_class, "execute"):
            raise PluginValidationError(
                f"{frame_class.__name__} must implement execute() method"
            )

    def _deduplicate_frames(
        self, frames: List[Type[ValidationFrame]]
    ) -> List[Type[ValidationFrame]]:
        """
        Remove duplicate frames (by frame_id).

        If duplicates exist, prioritize:
        1. Built-in frames
        2. Entry point plugins
        3. Local plugins

        Args:
            frames: List of frame classes (may contain duplicates)

        Returns:
            Deduplicated list of frame classes
        """
        seen_ids: Dict[str, Type[ValidationFrame]] = {}

        for frame_class in frames:
            # Get frame_id (instantiate to call property)
            try:
                frame_instance = frame_class()
                frame_id = frame_instance.frame_id
            except Exception:
                # If instantiation fails, use class name as fallback
                frame_id = frame_class.__name__.lower()

            if frame_id not in seen_ids:
                seen_ids[frame_id] = frame_class
            else:
                logger.warning(
                    "duplicate_frame_detected",
                    frame_id=frame_id,
                    existing=seen_ids[frame_id].__name__,
                    duplicate=frame_class.__name__,
                )

        return list(seen_ids.values())


class PluginLoadError(Exception):
    """Raised when plugin loading fails."""

    pass


class PluginValidationError(Exception):
    """Raised when plugin validation fails."""

    pass
