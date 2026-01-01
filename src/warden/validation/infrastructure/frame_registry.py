"""
Frame registry for built-in and external validation frames.

Discovers and loads frames from:
1. Built-in frames (warden.validation.frames)
2. Entry points (PyPI packages)
3. Local frame directory (~/.warden/frames/)
4. Environment variable (WARDEN_FRAME_PATHS)
"""

import os
import sys
import yaml
import importlib
import importlib.util
from pathlib import Path
from typing import List, Type, Dict, Any
from dataclasses import dataclass

from warden.validation.domain.frame import ValidationFrame, ValidationFrameError
from warden.validation.infrastructure.frame_metadata import FrameMetadata
from warden.validation.domain.enums import FramePriority
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class FrameListItem:
    """
    Frame metadata for UI display (Claude Code plugin style).

    Used by CLI commands to show frame information in a user-friendly format.
    """

    frame_id: str
    name: str
    description: str
    enabled: bool
    source: str  # "Built-in" | "Custom" | "Community"
    priority: str  # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    is_blocker: bool
    version: str
    author: str
    check_count: int  # Number of checks/validators in frame
    category: str  # "Global" | "Language-Specific" | "Framework-Specific"


class FrameRegistry:
    """
    Discovers and registers validation frames.

    Discovery order:
    1. Built-in frames (warden.validation.frames.*)
    2. Entry point frames (PyPI packages)
    3. Local directory frames (~/.warden/frames/)
    4. Environment variable frames (WARDEN_FRAME_PATHS)
    """

    def __init__(self) -> None:
        """Initialize frame registry."""
        self.registered_frames: Dict[str, Type[ValidationFrame]] = {}
        self.frame_metadata: Dict[str, FrameMetadata] = {}
        self._config_cache: Dict[str, Dict[str, Any]] = {}  # Cache for merged configs

    def discover_all(self) -> List[Type[ValidationFrame]]:
        """
        Discover all available frames from all sources.

        Returns:
            List of ValidationFrame classes

        Raises:
            ValidationFrameError: If frame discovery fails critically
        """
        logger.info("frame_discovery_started")

        # 1. Discover built-in frames
        builtin_frames = self._discover_builtin_frames()
        logger.info(
            "builtin_frames_discovered",
            count=len(builtin_frames),
            frames=[f.__name__ for f in builtin_frames],
        )

        # 2. Discover entry point frames (PyPI)
        entry_point_frames = self._discover_entry_point_frames()
        logger.info(
            "entry_point_frames_discovered",
            count=len(entry_point_frames),
            frames=[f.__name__ for f in entry_point_frames],
        )

        # 3. Discover local directory frames
        local_frames = self._discover_local_frames()
        logger.info(
            "local_frames_discovered",
            count=len(local_frames),
            frames=[f.__name__ for f in local_frames],
        )

        # 4. Discover environment variable frames
        env_frames = self._discover_env_frames()
        logger.info(
            "env_frames_discovered",
            count=len(env_frames),
            frames=[f.__name__ for f in env_frames],
        )

        # Combine all discovered frames
        all_frames = builtin_frames + entry_point_frames + local_frames + env_frames

        # Remove duplicates (by frame_id)
        unique_frames = self._deduplicate_frames(all_frames)

        # Register all unique frames
        for frame_class in unique_frames:
            self.register(frame_class)

        logger.info(
            "frame_discovery_complete",
            total_discovered=len(all_frames),
            unique_frames=len(unique_frames),
        )

        return unique_frames

    def register(self, frame_class: Type[ValidationFrame]) -> None:
        """
        Register a frame class.

        Args:
            frame_class: ValidationFrame class to register
        """
        # Instantiate to get frame_id
        instance = frame_class()
        frame_id = instance.frame_id

        if frame_id in self.registered_frames:
            logger.warning(
                "frame_already_registered",
                frame_id=frame_id,
                existing=self.registered_frames[frame_id].__name__,
                new=frame_class.__name__,
            )
            return

        self.registered_frames[frame_id] = frame_class
        logger.debug("frame_registered", frame_id=frame_id, frame=frame_class.__name__)

    def get(self, frame_id: str) -> Type[ValidationFrame] | None:
        """
        Get a registered frame by ID.

        Args:
            frame_id: Frame identifier

        Returns:
            ValidationFrame class or None if not found
        """
        return self.registered_frames.get(frame_id)

    def get_all(self) -> List[Type[ValidationFrame]]:
        """Get all registered frames."""
        return list(self.registered_frames.values())

    def get_frame_by_id(self, frame_id: str) -> Type[ValidationFrame] | None:
        """
        Get a frame class by its ID.

        Args:
            frame_id: Frame identifier (e.g., 'security', 'redis-security')

        Returns:
            ValidationFrame class or None if not found
        """
        return self.registered_frames.get(frame_id)

    def get_all_frames_as_dict(self) -> Dict[str, Type[ValidationFrame]]:
        """
        Get all registered frames as a dictionary.

        This method is used by CLI commands (scan, validate) to dynamically
        discover and load frames from config files.

        Returns:
            Dictionary mapping frame_id to ValidationFrame class
            Example: {'security': SecurityFrame, 'redis-security': RedisSecurityFrame}

        Note:
            Automatically calls discover_all() to ensure all frames are registered.
        """
        # Ensure all frames are discovered
        if not self.registered_frames:
            self.discover_all()

        return self.registered_frames.copy()

    def get_all_frames_with_metadata(self) -> List[FrameListItem]:
        """
        Get all registered frames with display metadata (for CLI UI).

        Returns UI-friendly frame metadata for commands like `warden frame list`.
        Includes frame status, source, version, and other display information.

        Returns:
            List of FrameListItem objects with display metadata

        Example:
            >>> registry = get_registry()
            >>> frames = registry.get_all_frames_with_metadata()
            >>> for frame in frames:
            ...     print(f"{frame.name} - {frame.source} - {frame.priority}")
            Security Analysis - Built-in - CRITICAL
            Redis Security - Custom - HIGH
        """
        # Ensure all frames are discovered
        if not self.registered_frames:
            self.discover_all()

        frames_list: List[FrameListItem] = []

        for frame_id, frame_class in self.registered_frames.items():
            # Instantiate to get metadata
            instance = frame_class()

            # Determine source
            module_name = frame_class.__module__
            if module_name.startswith("warden.validation.frames."):
                source = "Built-in"
            elif module_name.startswith("warden.external."):
                source = "Custom"
            else:
                source = "Community"

            # Get priority as string (use enum name, not value)
            if hasattr(instance.priority, "name"):
                priority_str = instance.priority.name  # CRITICAL, HIGH, etc.
            else:
                priority_str = str(instance.priority).upper()

            # Get category as string (use enum value for display)
            if hasattr(instance.category, "value"):
                category_str = str(instance.category.value)
            else:
                category_str = str(instance.category)

            # Count checks (heuristic: count methods starting with check_ or validate_)
            check_count = sum(
                1
                for attr_name in dir(instance)
                if (attr_name.startswith("check_") or attr_name.startswith("validate_"))
                and callable(getattr(instance, attr_name))
            )

            # Default to 0 if no checks found (frame might use different pattern)
            if check_count == 0:
                check_count = 1  # Assume at least 1 validation

            # Create FrameListItem
            item = FrameListItem(
                frame_id=frame_id,
                name=instance.name,
                description=instance.description,
                enabled=True,  # TODO: Get from config (.warden/config.yaml)
                source=source,
                priority=priority_str.upper(),
                is_blocker=instance.is_blocker,
                version=instance.version,
                author=instance.author,
                check_count=check_count,
                category=category_str,
            )

            frames_list.append(item)

        # Sort by priority (CRITICAL > HIGH > MEDIUM > LOW) then name
        priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        frames_list.sort(
            key=lambda f: (
                priority_order.get(f.priority, 999),
                f.name,
            )
        )

        return frames_list

    def _discover_builtin_frames(self) -> List[Type[ValidationFrame]]:
        """
        Discover built-in frames from warden.validation.frames.

        Auto-discovers frames by scanning the frames directory for frame modules.
        Each frame must follow the naming convention: <frame_name>/<frame_name>_frame.py

        Returns:
            List of built-in ValidationFrame classes
        """
        frames: List[Type[ValidationFrame]] = []

        try:
            # Get frames directory path
            frames_dir = Path(__file__).parent.parent / "frames"

            if not frames_dir.exists():
                logger.error(
                    "frames_directory_not_found",
                    path=str(frames_dir),
                )
                return frames

            logger.debug(
                "scanning_builtin_frames",
                frames_dir=str(frames_dir),
            )

            # Scan each subdirectory in frames/
            for frame_path in frames_dir.iterdir():
                # Skip non-directories, __pycache__, and private directories
                if not frame_path.is_dir() or frame_path.name.startswith("_"):
                    continue

                # Expected frame file: <frame_name>/<frame_name>_frame.py
                frame_file = frame_path / f"{frame_path.name}_frame.py"

                if not frame_file.exists() or not frame_file.is_file():
                    logger.debug(
                        "frame_file_not_found",
                        frame_name=frame_path.name,
                        expected_file=str(frame_file),
                    )
                    continue

                try:
                    # Dynamically import the frame module
                    logger.debug(f"Attempting to import frame: {frame_path.name}")
                    module_path = f"warden.validation.frames.{frame_path.name}.{frame_path.name}_frame"
                    module = importlib.import_module(module_path)

                    # Find ValidationFrame subclass in the module
                    frame_class = None
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)

                        # Check if it's a ValidationFrame subclass (but not ValidationFrame itself)
                        if (
                            isinstance(attr, type)
                            and issubclass(attr, ValidationFrame)
                            and attr is not ValidationFrame
                        ):
                            frame_class = attr
                            break

                    if frame_class:
                        frames.append(frame_class)
                        logger.debug(f"Discovered built-in frame: {frame_path.name}")
                        logger.debug(
                            "builtin_frame_discovered",
                            frame_name=frame_path.name,
                            frame_class=frame_class.__name__,
                        )
                    else:
                        logger.debug(f"No class found in frame: {frame_path.name}")
                        logger.warning(
                            "no_frame_class_found_in_module",
                            frame_name=frame_path.name,
                            module=module_path,
                        )

                except ImportError as e:
                    logger.debug(f"Import failed for {frame_path.name}: {e}")
                    logger.warning(
                        "builtin_frame_import_failed",
                        frame_name=frame_path.name,
                        error=str(e),
                    )
                except Exception as e:
                    logger.debug(f"Exception discovering {frame_path.name}: {e}")
                    logger.error(
                        "builtin_frame_discovery_error",
                        frame_name=frame_path.name,
                        error=str(e),
                        error_type=type(e).__name__,
                    )

            logger.info(
                "builtin_frames_discovered",
                count=len(frames),
                frames=[f.__name__ for f in frames],
            )

        except Exception as e:
            logger.error(
                "builtin_frames_discovery_failed",
                error=str(e),
                error_type=type(e).__name__,
            )

        return frames

    def _discover_entry_point_frames(self) -> List[Type[ValidationFrame]]:
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
                            "entry_point_frame_loaded",
                            name=entry_point.name,
                            frame=frame_class.__name__,
                        )
                    except Exception as e:
                        logger.error(
                            "entry_point_frame_load_failed",
                            name=entry_point.name,
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
                        "entry_point_frame_loaded",
                        name=entry_point.name,
                        frame=frame_class.__name__,
                    )
                except Exception as e:
                    logger.error(
                        "entry_point_frame_load_failed",
                        name=entry_point.name,
                        error=str(e),
                    )

        except Exception as e:
            logger.error("entry_point_discovery_failed", error=str(e))

        return frames

    def _discover_local_frames(self) -> List[Type[ValidationFrame]]:
        """
        Discover frames from local directories.

        Searches in TWO locations:
        1. Global: ~/.warden/frames/ (for all projects)
        2. Project-specific: <cwd>/.warden/frames/ (for current project only)

        Each frame should be in its own directory with:
        - frame.py (contains ValidationFrame subclass)
        - frame.yaml (metadata)

        Returns:
            List of ValidationFrame classes from local directories
        """
        frames: List[Type[ValidationFrame]] = []

        # 1. Global frames directory (~/.warden/frames/)
        global_frames_dir = Path.home() / ".warden" / "frames"

        # 2. Project-specific frames directory (<cwd>/.warden/frames/)
        project_frames_dir = Path.cwd() / ".warden" / "frames"

        # Scan both locations
        search_paths = [
            ("global", global_frames_dir),
            ("project", project_frames_dir),
        ]

        for source, frames_dir in search_paths:
            if not frames_dir.exists():
                logger.debug(
                    "local_frames_directory_not_found",
                    source=source,
                    path=str(frames_dir),
                )
                continue

            logger.debug(
                "scanning_local_frames",
                source=source,
                path=str(frames_dir),
            )

            # Scan for frame directories
            for frame_path in frames_dir.iterdir():
                # Skip if not a directory
                if not frame_path.is_dir():
                    continue

                # Skip hidden directories, __pycache__, and system directories
                if frame_path.name.startswith('.') or frame_path.name == '__pycache__':
                    logger.debug("skipping_system_directory", path=str(frame_path))
                    continue

                try:
                    frame_class = self._load_local_frame(frame_path)
                    if frame_class:
                        frames.append(frame_class)
                        logger.info(
                            "local_frame_loaded",
                            source=source,
                            path=str(frame_path),
                            frame=frame_class.__name__,
                        )
                except Exception as e:
                    logger.error(
                        "local_frame_load_failed",
                        source=source,
                        path=str(frame_path),
                        error=str(e),
                    )

        return frames

    def _discover_env_frames(self) -> List[Type[ValidationFrame]]:
        """
        Discover frames from WARDEN_FRAME_PATHS environment variable.

        Format: WARDEN_FRAME_PATHS=/path/to/frames1:/path/to/frames2

        Returns:
            List of ValidationFrame classes from environment paths
        """
        frames: List[Type[ValidationFrame]] = []
        env_paths = os.getenv("WARDEN_FRAME_PATHS", "")

        if not env_paths:
            return frames

        for path_str in env_paths.split(":"):
            path = Path(path_str.strip())

            if not path.exists() or not path.is_dir():
                logger.warning("env_frame_path_not_found", path=str(path))
                continue

            # Scan for frame directories
            for frame_path in path.iterdir():
                # Skip if not a directory
                if not frame_path.is_dir():
                    continue

                # Skip hidden directories, __pycache__, and system directories
                if frame_path.name.startswith('.') or frame_path.name == '__pycache__':
                    logger.debug("skipping_system_directory_env", path=str(frame_path))
                    continue

                try:
                    frame_class = self._load_local_frame(frame_path)
                    if frame_class:
                        frames.append(frame_class)
                        logger.info(
                            "env_frame_loaded",
                            path=str(frame_path),
                            frame=frame_class.__name__,
                        )
                except Exception as e:
                    logger.error(
                        "env_frame_load_failed",
                        path=str(frame_path),
                        error=str(e),
                    )

        return frames

    def _load_local_frame(self, frame_dir: Path) -> Type[ValidationFrame] | None:
        """
        Load a frame from a local directory.

        Args:
            frame_dir: Path to frame directory

        Returns:
            ValidationFrame class or None if loading failed
        """
        # Check for frame.py
        frame_file = frame_dir / "frame.py"
        if not frame_file.exists() or not frame_file.is_file():
            logger.debug("frame_py_not_found", path=str(frame_dir))
            return None

        # Load metadata (optional but recommended)
        metadata_file = frame_dir / "frame.yaml"
        frame_metadata = None
        if metadata_file.exists() and metadata_file.is_file():
            try:
                frame_metadata = FrameMetadata.from_yaml(metadata_file)
                logger.debug(
                    "frame_metadata_loaded",
                    frame=frame_metadata.name,
                    version=frame_metadata.version,
                )
            except Exception as e:
                logger.warning(
                    "frame_metadata_load_failed",
                    path=str(metadata_file),
                    error=str(e),
                )

        # Load frame module
        module_name = f"warden.external.{frame_dir.name}"
        spec = importlib.util.spec_from_file_location(module_name, frame_file)

        if not spec or not spec.loader:
            logger.error("frame_spec_creation_failed", path=str(frame_file))
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Find ValidationFrame subclass
        for attr_name in dir(module):
            attr = getattr(module, attr_name)

            if (
                isinstance(attr, type)
                and issubclass(attr, ValidationFrame)
                and attr is not ValidationFrame
            ):
                self._validate_frame_class(attr)

                # Store metadata if loaded
                if frame_metadata:
                    instance = attr()
                    self.frame_metadata[instance.frame_id] = frame_metadata
                    logger.debug(
                        "frame_metadata_stored",
                        frame_id=instance.frame_id,
                        metadata=frame_metadata.to_dict(),
                    )

                return attr

        logger.warning("no_frame_class_found", path=str(frame_dir))
        return None

    def _validate_frame_class(self, frame_class: Type[ValidationFrame]) -> None:
        """
        Validate that a class is a proper ValidationFrame.

        Args:
            frame_class: Class to validate

        Raises:
            ValidationFrameError: If validation fails
        """
        if not issubclass(frame_class, ValidationFrame):
            raise ValidationFrameError(
                f"{frame_class.__name__} is not a ValidationFrame subclass"
            )

        # Try to instantiate to check for required attributes
        try:
            instance = frame_class()
            _ = instance.name
            _ = instance.description
            _ = instance.priority
            _ = instance.scope
        except Exception as e:
            raise ValidationFrameError(
                f"Frame {frame_class.__name__} validation failed: {e}"
            )

    def _deduplicate_frames(
        self, frames: List[Type[ValidationFrame]]
    ) -> List[Type[ValidationFrame]]:
        """
        Remove duplicate frames (by frame_id).

        Args:
            frames: List of frames (may contain duplicates)

        Returns:
            List of unique frames
        """
        seen_ids = set()
        unique_frames = []

        for frame_class in frames:
            instance = frame_class()
            frame_id = instance.frame_id

            if frame_id not in seen_ids:
                seen_ids.add(frame_id)
                unique_frames.append(frame_class)
            else:
                logger.debug(
                    "duplicate_frame_skipped",
                    frame_id=frame_id,
                    frame=frame_class.__name__,
                )

        return unique_frames

    def get_frame_config(
        self, frame_id: str, user_config: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """
        Get merged frame configuration (defaults from metadata + user overrides).

        Merges configuration from multiple sources:
        1. Frame metadata (frame.yaml config_schema defaults)
        2. User configuration (.warden/config.yaml frames_config)

        Args:
            frame_id: Frame identifier
            user_config: Optional user configuration from .warden/config.yaml

        Returns:
            Merged configuration dictionary

        Example:
            >>> # frame.yaml
            >>> config_schema:
            >>>   enabled:
            >>>     type: "boolean"
            >>>     default: true
            >>>   check_ssl:
            >>>     type: "boolean"
            >>>     default: true
            >>>
            >>> # .warden/config.yaml
            >>> frames_config:
            >>>   redis-security:
            >>>     check_ssl: false  # Override
            >>>
            >>> # Result
            >>> {"enabled": true, "check_ssl": false}
        """
        # Check cache first
        cache_key = f"{frame_id}:{hash(str(user_config))}"
        if cache_key in self._config_cache:
            return self._config_cache[cache_key].copy()

        # Start with empty config
        merged_config: Dict[str, Any] = {}

        # 1. Get defaults from frame metadata (if available)
        if frame_id in self.frame_metadata:
            metadata = self.frame_metadata[frame_id]
            default_config = self._generate_default_config(metadata)
            merged_config.update(default_config)

            logger.debug(
                "frame_default_config_generated",
                frame_id=frame_id,
                defaults=default_config,
            )

        # 2. Merge user configuration (overrides defaults)
        if user_config:
            merged_config.update(user_config)

            logger.debug(
                "frame_config_merged",
                frame_id=frame_id,
                user_overrides=user_config,
                final_config=merged_config,
            )

        # Cache the result
        self._config_cache[cache_key] = merged_config.copy()

        return merged_config

    def _generate_default_config(self, metadata: FrameMetadata) -> Dict[str, Any]:
        """
        Generate default configuration from frame metadata schema.

        Extracts default values from config_schema in frame.yaml.

        Args:
            metadata: Frame metadata with config_schema

        Returns:
            Default configuration dictionary

        Example:
            >>> # frame.yaml
            >>> config_schema:
            >>>   enabled:
            >>>     type: "boolean"
            >>>     default: true
            >>>   check_ssl:
            >>>     type: "boolean"
            >>>     default: true
            >>>
            >>> # Generated config
            >>> {"enabled": true, "check_ssl": true}
        """
        default_config: Dict[str, Any] = {}

        # Always default to enabled unless explicitly configured
        default_config["enabled"] = True

        # Extract defaults from config_schema
        if metadata.config_schema:
            for field_name, field_schema in metadata.config_schema.items():
                if isinstance(field_schema, dict) and "default" in field_schema:
                    default_config[field_name] = field_schema["default"]

        logger.debug(
            "default_config_generated",
            frame_id=metadata.id,
            schema_fields=len(metadata.config_schema),
            defaults=default_config,
        )

        return default_config


# Singleton instance
_registry = FrameRegistry()


def get_registry() -> FrameRegistry:
    """Get the global frame registry instance."""
    return _registry
