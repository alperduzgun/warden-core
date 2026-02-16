"""
SpecFrame Configuration Validator.

Validates platform configurations before they are used by the SpecFrame.
Provides clear error messages and suggestions for fixes.

This module is part of the SpecFrame setup wizard system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from itertools import islice
from pathlib import Path

from warden.shared.infrastructure.logging import get_logger
from warden.validation.frames.spec.models import PlatformRole, PlatformType

logger = get_logger(__name__)


class IssueSeverity(str, Enum):
    """Severity levels for validation issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """
    A validation issue found in configuration.

    Attributes:
        severity: Issue severity (error/warning/info)
        message: Human-readable issue description
        field: Configuration field that caused the issue
        suggestion: Suggested fix or action
        platform_name: Platform name (if issue is platform-specific)
    """

    severity: IssueSeverity
    message: str
    field: str
    suggestion: str | None = None
    platform_name: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "severity": self.severity.value,
            "message": self.message,
            "field": self.field,
            "suggestion": self.suggestion,
            "platform_name": self.platform_name,
        }


@dataclass
class ValidationResult:
    """
    Result of configuration validation.

    Attributes:
        is_valid: True if configuration is valid
        issues: List of validation issues found
        metadata: Additional validation metadata
    """

    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        """Check if there are any error-level issues."""
        return any(i.severity == IssueSeverity.ERROR for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warning-level issues."""
        return any(i.severity == IssueSeverity.WARNING for i in self.issues)

    @property
    def error_count(self) -> int:
        """Count of error-level issues."""
        return sum(1 for i in self.issues if i.severity == IssueSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        """Count of warning-level issues."""
        return sum(1 for i in self.issues if i.severity == IssueSeverity.WARNING)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "is_valid": self.is_valid,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [i.to_dict() for i in self.issues],
            "metadata": self.metadata,
        }


class SpecConfigValidator:
    """
    Validates SpecFrame platform configurations.

    Performs comprehensive validation including:
    - Required field checks
    - Path existence and accessibility
    - Platform type validation
    - Role validation
    - Duplicate detection
    - Consumer/Provider pairing checks

    Usage:
        validator = SpecConfigValidator()
        result = validator.validate_platforms(platforms_config)
        if not result.is_valid:
            for issue in result.issues:
                print(f"{issue.severity}: {issue.message}")
    """

    def __init__(self, project_root: Path | None = None):
        """
        Initialize validator.

        Args:
            project_root: Project root directory (for resolving relative paths)
                         If None, will search for .warden directory
        """
        self.project_root = project_root or self._find_project_root()

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

    def validate_platforms(
        self,
        platforms: list[dict],
    ) -> ValidationResult:
        """
        Validate platform configurations.

        Performs comprehensive validation of all platform configurations
        and returns detailed results with actionable suggestions.

        Args:
            platforms: List of platform configuration dictionaries

        Returns:
            ValidationResult with issues and metadata
        """
        logger.info(
            "validation_started",
            platform_count=len(platforms),
            project_root=str(self.project_root),
        )

        issues: list[ValidationIssue] = []
        metadata: dict = {
            "platforms_checked": len(platforms),
            "consumer_count": 0,
            "provider_count": 0,
        }

        # Check minimum platforms requirement
        if len(platforms) < 2:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    message=f"At least 2 platforms required, found {len(platforms)}",
                    field="platforms",
                    suggestion=(
                        "Add at least one consumer (frontend/mobile) and "
                        "one provider (backend) platform to enable contract comparison"
                    ),
                )
            )

        # Validate each platform
        platform_names: set[str] = set()
        platform_paths: set[str] = set()

        for idx, platform in enumerate(platforms):
            platform_name = platform.get("name", f"platform_{idx}")

            # Validate required fields
            self._validate_required_fields(platform, platform_name, issues)

            # Validate path
            self._validate_path(platform, platform_name, issues)

            # Validate platform type
            self._validate_platform_type(platform, platform_name, issues)

            # Validate role
            role = self._validate_role(platform, platform_name, issues)

            # Track consumer/provider counts
            if role:
                if role == PlatformRole.CONSUMER:
                    metadata["consumer_count"] += 1
                elif role == PlatformRole.PROVIDER:
                    metadata["provider_count"] += 1
                elif role == PlatformRole.BOTH:
                    metadata["consumer_count"] += 1
                    metadata["provider_count"] += 1

            # Check for duplicates
            self._check_duplicates(
                platform,
                platform_name,
                platform_names,
                platform_paths,
                issues,
            )

            # Check project size (warning only)
            self._check_project_size(platform, platform_name, issues)

        # Check for consumer/provider pairing
        if metadata["consumer_count"] == 0:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    message="No consumer platforms configured",
                    field="platforms",
                    suggestion=("Add at least one platform with role: consumer (e.g., Flutter, React, Angular)"),
                )
            )

        if metadata["provider_count"] == 0:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    message="No provider platforms configured",
                    field="platforms",
                    suggestion=("Add at least one platform with role: provider (e.g., Spring Boot, FastAPI, NestJS)"),
                )
            )

        # Determine if valid
        is_valid = not any(i.severity == IssueSeverity.ERROR for i in issues)

        result = ValidationResult(
            is_valid=is_valid,
            issues=issues,
            metadata=metadata,
        )

        logger.info(
            "validation_completed",
            is_valid=is_valid,
            errors=result.error_count,
            warnings=result.warning_count,
        )

        return result

    def _validate_required_fields(
        self,
        platform: dict,
        platform_name: str,
        issues: list[ValidationIssue],
    ) -> None:
        """
        Validate required fields are present.

        Args:
            platform: Platform configuration
            platform_name: Platform name for error messages
            issues: List to append issues to
        """
        required_fields = ["name", "path", "type", "role"]

        for required_field in required_fields:
            if not platform.get(required_field):
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.ERROR,
                        message=f"Missing required field: {required_field}",
                        field=required_field,
                        platform_name=platform_name,
                        suggestion=f"Add '{required_field}' to platform configuration",
                    )
                )

    def _validate_path(
        self,
        platform: dict,
        platform_name: str,
        issues: list[ValidationIssue],
    ) -> None:
        """
        Validate platform path exists and is accessible.

        Args:
            platform: Platform configuration
            platform_name: Platform name for error messages
            issues: List to append issues to
        """
        path_str = platform.get("path")
        if not path_str:
            return  # Already handled by required fields check

        path = Path(path_str)

        # Resolve relative paths
        if not path.is_absolute():
            path = self.project_root / path

        # Check existence
        if not path.exists():
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    message=f"Platform path does not exist: {path_str}",
                    field="path",
                    platform_name=platform_name,
                    suggestion=(f"Verify the path is correct. Resolved to: {path.resolve()}"),
                )
            )
            return

        # Check if it's a directory
        if not path.is_dir():
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    message=f"Platform path is not a directory: {path_str}",
                    field="path",
                    platform_name=platform_name,
                    suggestion="Provide a path to the project root directory",
                )
            )
            return

        # Check readability
        try:
            list(path.iterdir())
        except (PermissionError, OSError) as e:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    message=f"Platform path is not readable: {e!s}",
                    field="path",
                    platform_name=platform_name,
                    suggestion="Check directory permissions",
                )
            )

    def _validate_platform_type(
        self,
        platform: dict,
        platform_name: str,
        issues: list[ValidationIssue],
    ) -> PlatformType | None:
        """
        Validate platform type is a valid enum value.

        Args:
            platform: Platform configuration
            platform_name: Platform name for error messages
            issues: List to append issues to

        Returns:
            PlatformType if valid, None otherwise
        """
        type_str = platform.get("type")
        if not type_str:
            return None  # Already handled by required fields check

        if not self._is_valid_platform_type(type_str):
            valid_types = ", ".join(t.value for t in PlatformType)
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    message=f"Invalid platform type: {type_str}",
                    field="type",
                    platform_name=platform_name,
                    suggestion=f"Valid types: {valid_types}",
                )
            )
            return None

        return PlatformType(type_str)

    def _validate_role(
        self,
        platform: dict,
        platform_name: str,
        issues: list[ValidationIssue],
    ) -> PlatformRole | None:
        """
        Validate platform role is a valid enum value.

        Args:
            platform: Platform configuration
            platform_name: Platform name for error messages
            issues: List to append issues to

        Returns:
            PlatformRole if valid, None otherwise
        """
        role_str = platform.get("role")
        if not role_str:
            return None  # Already handled by required fields check

        try:
            return PlatformRole(role_str)
        except ValueError:
            valid_roles = ", ".join(r.value for r in PlatformRole)
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    message=f"Invalid platform role: {role_str}",
                    field="role",
                    platform_name=platform_name,
                    suggestion=f"Valid roles: {valid_roles}",
                )
            )
            return None

    def _check_duplicates(
        self,
        platform: dict,
        platform_name: str,
        seen_names: set[str],
        seen_paths: set[str],
        issues: list[ValidationIssue],
    ) -> None:
        """
        Check for duplicate platform names and paths.

        Args:
            platform: Platform configuration
            platform_name: Platform name
            seen_names: Set of already seen platform names
            seen_paths: Set of already seen platform paths
            issues: List to append issues to
        """
        # Check duplicate names
        if platform_name in seen_names:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    message=f"Duplicate platform name: {platform_name}",
                    field="name",
                    platform_name=platform_name,
                    suggestion="Each platform must have a unique name",
                )
            )
        else:
            seen_names.add(platform_name)

        # Check duplicate paths
        path_str = platform.get("path")
        if path_str:
            path = Path(path_str)
            if not path.is_absolute():
                path = self.project_root / path

            path_resolved = str(path.resolve())

            if path_resolved in seen_paths:
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.WARNING,
                        message=f"Duplicate platform path: {path_str}",
                        field="path",
                        platform_name=platform_name,
                        suggestion=(
                            "Multiple platforms point to the same directory. "
                            "This may be intentional for different extraction strategies."
                        ),
                    )
                )
            else:
                seen_paths.add(path_resolved)

    def _check_project_size(
        self,
        platform: dict,
        platform_name: str,
        issues: list[ValidationIssue],
    ) -> None:
        """
        Check if project is very large (warning only).

        Args:
            platform: Platform configuration
            platform_name: Platform name
            issues: List to append issues to
        """
        path_str = platform.get("path")
        if not path_str:
            return

        path = Path(path_str)
        if not path.is_absolute():
            path = self.project_root / path

        if not path.exists():
            return

        try:
            max_files_to_count = 10000
            file_count = sum(1 for _ in islice(path.rglob("*"), max_files_to_count))

            if file_count >= max_files_to_count:
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.WARNING,
                        message=(f"Project appears very large (>10,000 files): {platform_name}"),
                        field="path",
                        platform_name=platform_name,
                        suggestion=(
                            "Consider using .gitignore patterns or excluding "
                            "build/vendor directories to speed up analysis"
                        ),
                    )
                )

        except (PermissionError, OSError):
            pass

    def _is_valid_platform_type(self, type_str: str) -> bool:
        """
        Check if platform type string is valid.

        Args:
            type_str: Platform type string

        Returns:
            True if valid PlatformType enum value
        """
        try:
            PlatformType(type_str)
            return True
        except ValueError:
            return False
