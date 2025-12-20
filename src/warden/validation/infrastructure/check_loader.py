"""
Check loader for community validation checks.

Discovers and loads checks from:
1. Entry points (PyPI packages) - per frame
2. Local check directory (~/.warden/checks/{frame_name}/)
3. Programmatic registration (frame.register_check())
"""

import os
import sys
import yaml
import importlib.util
from pathlib import Path
from typing import List, Type, Dict, Any

from warden.validation.domain.check import ValidationCheck
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class CheckLoader:
    """
    Discovers and loads validation checks for frames.

    Discovery order (per frame):
    1. Built-in checks (frame's own checks)
    2. Entry point checks (PyPI: "warden.checks.{frame_id}")
    3. Local directory checks (~/.warden/checks/{frame_id}/)
    """

    def __init__(self, frame_id: str) -> None:
        """
        Initialize check loader for a specific frame.

        Args:
            frame_id: Frame identifier (e.g., "security", "chaos")
        """
        self.frame_id = frame_id
        self.discovered_checks: List[Type[ValidationCheck]] = []

    def discover_all(self) -> List[Type[ValidationCheck]]:
        """
        Discover all available checks for this frame.

        Returns:
            List of ValidationCheck classes

        Raises:
            CheckLoadError: If check discovery fails critically
        """
        logger.info(
            "check_discovery_started",
            frame_id=self.frame_id,
        )

        # 1. Discover entry point checks (PyPI)
        entry_point_checks = self._discover_entry_point_checks()
        logger.info(
            "entry_point_checks_discovered",
            frame_id=self.frame_id,
            count=len(entry_point_checks),
            checks=[c.__name__ for c in entry_point_checks],
        )

        # 2. Discover local directory checks
        local_checks = self._discover_local_checks()
        logger.info(
            "local_checks_discovered",
            frame_id=self.frame_id,
            count=len(local_checks),
            checks=[c.__name__ for c in local_checks],
        )

        # Combine all discovered checks
        all_checks = entry_point_checks + local_checks

        # Remove duplicates (by check.id)
        unique_checks = self._deduplicate_checks(all_checks)

        logger.info(
            "check_discovery_complete",
            frame_id=self.frame_id,
            total_discovered=len(all_checks),
            unique_checks=len(unique_checks),
        )

        self.discovered_checks = unique_checks
        return unique_checks

    def _discover_entry_point_checks(self) -> List[Type[ValidationCheck]]:
        """
        Discover checks via Python entry points (PyPI packages).

        Entry point group: "warden.checks.{frame_id}"

        Example pyproject.toml (for SecurityFrame):
            [tool.poetry.plugins."warden.checks.security"]
            mycompany_api_key = "warden_check_mycompany.security:APIKeyCheck"

        Returns:
            List of ValidationCheck classes from entry points
        """
        checks: List[Type[ValidationCheck]] = []

        try:
            # Try importlib.metadata (Python 3.10+)
            try:
                from importlib.metadata import entry_points
            except ImportError:
                # Fallback to pkg_resources (older Python)
                import pkg_resources

                group_name = f"warden.checks.{self.frame_id}"
                eps = pkg_resources.iter_entry_points(group_name)
                for entry_point in eps:
                    try:
                        check_class = entry_point.load()
                        self._validate_check_class(check_class)
                        checks.append(check_class)
                        logger.info(
                            "entry_point_check_loaded",
                            frame_id=self.frame_id,
                            plugin=entry_point.name,
                            check=check_class.__name__,
                        )
                    except Exception as e:
                        logger.error(
                            "entry_point_check_load_failed",
                            frame_id=self.frame_id,
                            plugin=entry_point.name,
                            error=str(e),
                        )
                return checks

            # Python 3.10+ path
            group_name = f"warden.checks.{self.frame_id}"
            eps = entry_points(group=group_name)
            for entry_point in eps:
                try:
                    check_class = entry_point.load()
                    self._validate_check_class(check_class)
                    checks.append(check_class)
                    logger.info(
                        "entry_point_check_loaded",
                        frame_id=self.frame_id,
                        plugin=entry_point.name,
                        check=check_class.__name__,
                    )
                except Exception as e:
                    logger.error(
                        "entry_point_check_load_failed",
                        frame_id=self.frame_id,
                        plugin=entry_point.name,
                        error=str(e),
                    )

        except Exception as e:
            logger.error(
                "entry_point_check_discovery_failed",
                frame_id=self.frame_id,
                error=str(e),
            )

        return checks

    def _discover_local_checks(self) -> List[Type[ValidationCheck]]:
        """
        Discover checks from local check directory.

        Default: ~/.warden/checks/{frame_id}/

        Each check:
            ~/.warden/checks/security/mycompany-api-key/
                check.yaml
                check.py

        Returns:
            List of ValidationCheck classes from local checks
        """
        checks: List[Type[ValidationCheck]] = []

        # Get check directory for this frame
        check_dir = Path.home() / ".warden" / "checks" / self.frame_id

        if not check_dir.exists():
            logger.debug(
                "local_check_directory_not_found",
                frame_id=self.frame_id,
                path=str(check_dir),
            )
            return checks

        # Scan for checks
        for check_path in check_dir.iterdir():
            if not check_path.is_dir():
                continue

            manifest_path = check_path / "check.yaml"
            if not manifest_path.exists():
                logger.warning(
                    "check_manifest_missing",
                    frame_id=self.frame_id,
                    check_dir=check_path.name,
                    expected_file="check.yaml",
                )
                continue

            try:
                # Load check
                check_class = self._load_local_check(check_path, manifest_path)
                checks.append(check_class)
                logger.info(
                    "local_check_loaded",
                    frame_id=self.frame_id,
                    check=check_path.name,
                    class_name=check_class.__name__,
                )

            except Exception as e:
                logger.error(
                    "local_check_load_failed",
                    frame_id=self.frame_id,
                    check=check_path.name,
                    error=str(e),
                )

        return checks

    def _load_local_check(
        self, check_path: Path, manifest_path: Path
    ) -> Type[ValidationCheck]:
        """
        Load a single local check.

        Args:
            check_path: Path to check directory
            manifest_path: Path to check.yaml

        Returns:
            ValidationCheck class

        Raises:
            CheckLoadError: If check cannot be loaded
        """
        # Load manifest
        with open(manifest_path) as f:
            manifest_data = yaml.safe_load(f)

        # Import check module
        check_module_path = check_path / "check.py"
        if not check_module_path.exists():
            raise CheckLoadError(f"check.py not found in {check_path}")

        # Dynamic import
        spec = importlib.util.spec_from_file_location(
            f"warden_check_{self.frame_id}_{manifest_data['id']}", check_module_path
        )
        if spec is None or spec.loader is None:
            raise CheckLoadError(f"Cannot load module from {check_module_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        # Find ValidationCheck subclass
        check_class = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, ValidationCheck)
                and attr is not ValidationCheck
            ):
                check_class = attr
                break

        if check_class is None:
            raise CheckLoadError(
                f"No ValidationCheck subclass found in {check_module_path}"
            )

        # Validate
        self._validate_check_class(check_class)

        return check_class

    def _validate_check_class(self, check_class: Type[ValidationCheck]) -> None:
        """
        Validate that check class meets requirements.

        Args:
            check_class: Check class to validate

        Raises:
            CheckValidationError: If validation fails
        """
        # Check it's a subclass
        if not issubclass(check_class, ValidationCheck):
            raise CheckValidationError(
                f"{check_class.__name__} must inherit from ValidationCheck"
            )

        # Check required attributes
        required_attrs = ["id", "name", "execute"]
        for attr in required_attrs:
            if not hasattr(check_class, attr):
                raise CheckValidationError(
                    f"{check_class.__name__} missing required attribute: {attr}"
                )

    def _deduplicate_checks(
        self, checks: List[Type[ValidationCheck]]
    ) -> List[Type[ValidationCheck]]:
        """
        Remove duplicate checks (by check.id).

        Args:
            checks: List of check classes (may contain duplicates)

        Returns:
            Deduplicated list of check classes
        """
        seen_ids: Dict[str, Type[ValidationCheck]] = {}

        for check_class in checks:
            # Get check_id (instantiate to call property)
            try:
                check_instance = check_class()
                check_id = check_instance.id
            except Exception:
                # If instantiation fails, use class name as fallback
                check_id = check_class.__name__.lower()

            if check_id not in seen_ids:
                seen_ids[check_id] = check_class
            else:
                logger.warning(
                    "duplicate_check_detected",
                    frame_id=self.frame_id,
                    check_id=check_id,
                    existing=seen_ids[check_id].__name__,
                    duplicate=check_class.__name__,
                )

        return list(seen_ids.values())


class CheckLoadError(Exception):
    """Raised when check loading fails."""

    pass


class CheckValidationError(Exception):
    """Raised when check validation fails."""

    pass
