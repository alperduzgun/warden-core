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
import importlib.util
from pathlib import Path
from typing import List, Type, Dict, Any
from dataclasses import dataclass

from warden.validation.domain.frame import ValidationFrame, ValidationFrameError
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class FrameMetadata:
    """Frame metadata from frame.yaml."""

    name: str
    id: str
    version: str
    author: str
    description: str
    category: str
    priority: int  # 1=CRITICAL, 2=HIGH, 3=MEDIUM, 4=LOW, 5=INFORMATIONAL
    scope: str  # "file_level" or "repository_level"
    is_blocker: bool = False
    min_warden_version: str | None = None
    max_warden_version: str | None = None
    config_schema: Dict[str, Any] | None = None
    applicability: List[str] | None = None
    tags: List[str] | None = None


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

    def _discover_builtin_frames(self) -> List[Type[ValidationFrame]]:
        """
        Discover built-in frames from warden.validation.frames.

        Returns:
            List of built-in ValidationFrame classes
        """
        frames: List[Type[ValidationFrame]] = []

        try:
            # Import built-in frames
            from warden.validation.frames.security_frame import SecurityFrame
            from warden.validation.frames.chaos_frame import ChaosFrame

            frames = [SecurityFrame, ChaosFrame]

            logger.debug(
                "builtin_frames_loaded",
                frames=[f.__name__ for f in frames],
            )

        except ImportError as e:
            logger.warning("builtin_frames_import_failed", error=str(e))

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
        Discover frames from ~/.warden/frames/.

        Each frame should be in its own directory with:
        - frame.py (contains ValidationFrame subclass)
        - frame.yaml (metadata)

        Returns:
            List of ValidationFrame classes from local directory
        """
        frames: List[Type[ValidationFrame]] = []
        frames_dir = Path.home() / ".warden" / "frames"

        if not frames_dir.exists():
            logger.debug("local_frames_directory_not_found", path=str(frames_dir))
            return frames

        # Scan for frame directories
        for frame_path in frames_dir.iterdir():
            if not frame_path.is_dir():
                continue

            try:
                frame_class = self._load_local_frame(frame_path)
                if frame_class:
                    frames.append(frame_class)
                    logger.info(
                        "local_frame_loaded",
                        path=str(frame_path),
                        frame=frame_class.__name__,
                    )
            except Exception as e:
                logger.error(
                    "local_frame_load_failed",
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
                if not frame_path.is_dir():
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
        if not frame_file.exists():
            logger.debug("frame_py_not_found", path=str(frame_dir))
            return None

        # Load metadata (optional)
        metadata_file = frame_dir / "frame.yaml"
        if metadata_file.exists():
            try:
                with open(metadata_file) as f:
                    metadata_dict = yaml.safe_load(f)
                    metadata = FrameMetadata(**metadata_dict)
                    logger.debug("frame_metadata_loaded", frame=metadata.name)
            except Exception as e:
                logger.warning("frame_metadata_load_failed", error=str(e))

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


# Singleton instance
_registry = FrameRegistry()


def get_registry() -> FrameRegistry:
    """Get the global frame registry instance."""
    return _registry
