"""
Platform Detector - Automatic detection of projects and platforms.

Scans the filesystem to detect projects and suggest platform types based on
file signatures (package.json, pubspec.yaml, pom.xml, requirements.txt, etc.).

This module is part of the SpecFrame setup wizard system.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from warden.shared.infrastructure.logging import get_logger
from warden.validation.frames.spec.models import PlatformRole, PlatformType

logger = get_logger(__name__)


@dataclass
class DetectedProject:
    """
    A detected project with suggested platform type and role.

    Attributes:
        name: Project name (derived from directory name)
        path: Absolute path to project root
        platform_type: Suggested platform type (flutter, spring, react, etc.)
        confidence: Confidence score (0.0 to 1.0)
        role: Suggested role (consumer/provider/both)
        evidence: List of files/patterns that led to detection
        metadata: Additional detection metadata (version, framework info, etc.)
    """
    name: str
    path: str
    platform_type: PlatformType
    confidence: float
    role: PlatformRole
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "path": self.path,
            "type": self.platform_type.value,
            "role": self.role.value,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
            "metadata": self.metadata,
        }


class PlatformDetector:
    """
    Detects projects and suggests platform configurations.

    Scans directories for common project signatures and provides
    confidence-scored suggestions for platform type and role.

    Usage:
        detector = PlatformDetector()
        projects = await detector.detect_projects_async(search_path)
        for project in projects:
            print(f"Found {project.platform_type} at {project.path}")
    """

    # Platform signature patterns
    # Each signature has: files to check, content patterns, and weight
    PLATFORM_SIGNATURES: dict[PlatformType, dict[str, Any]] = {
        PlatformType.FLUTTER: {
            "files": ["pubspec.yaml"],
            "patterns": {
                "pubspec.yaml": ["flutter:", "sdk: flutter"],
            },
            "exclude_patterns": {},
            "weight": 1.0,
            "typical_role": PlatformRole.CONSUMER,
        },
        PlatformType.SPRING: {
            "files": ["pom.xml", "build.gradle"],
            "patterns": {
                "pom.xml": ["<groupId>org.springframework", "<spring-boot"],
                "build.gradle": ["org.springframework.boot"],
            },
            "exclude_patterns": {},
            "weight": 1.0,
            "typical_role": PlatformRole.PROVIDER,
        },
        PlatformType.SPRING_BOOT: {
            "files": ["pom.xml", "build.gradle"],
            "patterns": {
                "pom.xml": ["<spring-boot", "spring-boot-starter"],
                "build.gradle": ["spring-boot-starter"],
            },
            "exclude_patterns": {},
            "weight": 1.0,
            "typical_role": PlatformRole.PROVIDER,
        },
        PlatformType.REACT: {
            "files": ["package.json"],
            "patterns": {
                "package.json": ['"react":', '"dependencies"'],
            },
            "exclude_patterns": {
                "package.json": ['"react-native":', '"expo"'],
            },
            "weight": 0.9,
            "typical_role": PlatformRole.CONSUMER,
        },
        PlatformType.REACT_NATIVE: {
            "files": ["package.json"],
            "patterns": {
                "package.json": ['"react-native":', '"dependencies"'],
            },
            "exclude_patterns": {
                "package.json": ['"expo"'],
            },
            "weight": 0.95,
            "typical_role": PlatformRole.CONSUMER,
        },
        PlatformType.FASTAPI: {
            "files": ["requirements.txt", "pyproject.toml"],
            "patterns": {
                "requirements.txt": ["fastapi", "uvicorn"],
                "pyproject.toml": ["fastapi", "uvicorn"],
            },
            "exclude_patterns": {},
            "weight": 0.95,
            "typical_role": PlatformRole.PROVIDER,
        },
        PlatformType.EXPRESS: {
            "files": ["package.json"],
            "patterns": {
                "package.json": ['"express":', '"dependencies"'],
            },
            "exclude_patterns": {
                "package.json": ['"@nestjs/'],
            },
            "weight": 0.9,
            "typical_role": PlatformRole.PROVIDER,
        },
        PlatformType.NESTJS: {
            "files": ["package.json"],
            "patterns": {
                "package.json": ['"@nestjs/core":', '"@nestjs/common"'],
            },
            "exclude_patterns": {},
            "weight": 1.0,
            "typical_role": PlatformRole.PROVIDER,
        },
        PlatformType.ANGULAR: {
            "files": ["package.json", "angular.json"],
            "patterns": {
                "package.json": ['"@angular/core":', '"@angular/common"'],
                "angular.json": ['"projects":', '"architect"'],
            },
            "exclude_patterns": {},
            "weight": 1.0,
            "typical_role": PlatformRole.CONSUMER,
        },
        PlatformType.VUE: {
            "files": ["package.json"],
            "patterns": {
                "package.json": ['"vue":', '"dependencies"'],
            },
            "exclude_patterns": {},
            "weight": 0.9,
            "typical_role": PlatformRole.CONSUMER,
        },
        PlatformType.DJANGO: {
            "files": ["requirements.txt", "manage.py", "pyproject.toml"],
            "patterns": {
                "requirements.txt": ["Django", "django"],
                "manage.py": ["django.core.management"],
                "pyproject.toml": ["Django", "django"],
            },
            "exclude_patterns": {},
            "weight": 1.0,
            "typical_role": PlatformRole.PROVIDER,
        },
        PlatformType.DOTNET: {
            "files": [".csproj", ".sln"],
            "patterns": {
                ".csproj": ["<Project Sdk=", "Microsoft.NET.Sdk"],
                ".sln": ["Microsoft Visual Studio Solution"],
            },
            "exclude_patterns": {},
            "weight": 0.95,
            "typical_role": PlatformRole.PROVIDER,
        },
        PlatformType.ASP_NET_CORE: {
            "files": [".csproj"],
            "patterns": {
                ".csproj": ["Microsoft.AspNetCore", "Microsoft.NET.Sdk.Web"],
            },
            "exclude_patterns": {},
            "weight": 1.0,
            "typical_role": PlatformRole.PROVIDER,
        },
        PlatformType.GO: {
            "files": ["go.mod", "go.sum"],
            "patterns": {
                "go.mod": ["module ", "go "],
            },
            "exclude_patterns": {},
            "weight": 0.9,
            "typical_role": PlatformRole.PROVIDER,
        },
        PlatformType.GIN: {
            "files": ["go.mod"],
            "patterns": {
                "go.mod": ["github.com/gin-gonic/gin"],
            },
            "exclude_patterns": {},
            "weight": 1.0,
            "typical_role": PlatformRole.PROVIDER,
        },
        PlatformType.ECHO: {
            "files": ["go.mod"],
            "patterns": {
                "go.mod": ["github.com/labstack/echo"],
            },
            "exclude_patterns": {},
            "weight": 1.0,
            "typical_role": PlatformRole.PROVIDER,
        },
    }

    def __init__(
        self,
        max_depth: int = 3,
        min_confidence: float = 0.5,
        exclude_dirs: set[str] | None = None,
    ):
        """
        Initialize platform detector.

        Args:
            max_depth: Maximum directory depth to search
            min_confidence: Minimum confidence threshold for detection (0.0-1.0)
            exclude_dirs: Directories to skip (node_modules, .git, etc.)
        """
        self.max_depth = max_depth
        self.min_confidence = min_confidence
        self.exclude_dirs = exclude_dirs or {
            "node_modules",
            ".git",
            ".svn",
            ".hg",
            "venv",
            ".venv",
            "env",
            ".env",
            "build",
            "dist",
            "target",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".tox",
            "vendor",
            "bower_components",
        }

    async def detect_projects_async(
        self,
        search_path: str | Path,
    ) -> list[DetectedProject]:
        """
        Detect projects in a directory tree asynchronously.

        Scans the directory tree up to max_depth and identifies projects
        based on signature files and patterns.

        Args:
            search_path: Root directory to search

        Returns:
            List of detected projects with confidence scores

        Raises:
            ValueError: If search_path doesn't exist or isn't readable
        """
        search_path = Path(search_path).resolve()

        if not search_path.exists():
            raise ValueError(f"Search path does not exist: {search_path}")

        if not search_path.is_dir():
            raise ValueError(f"Search path is not a directory: {search_path}")

        logger.info(
            "platform_detection_started",
            search_path=str(search_path),
            max_depth=self.max_depth,
            min_confidence=self.min_confidence,
        )

        detected_projects: list[DetectedProject] = []
        visited: set[str] = set()

        # Scan directory tree
        await self._scan_directory(
            search_path,
            current_depth=0,
            detected_projects=detected_projects,
            visited=visited,
        )

        # Filter by confidence threshold
        filtered_projects = [
            p for p in detected_projects
            if p.confidence >= self.min_confidence
        ]

        # Sort by confidence (highest first)
        filtered_projects.sort(key=lambda p: p.confidence, reverse=True)

        logger.info(
            "platform_detection_completed",
            projects_found=len(filtered_projects),
            projects_scanned=len(detected_projects),
            min_confidence=self.min_confidence,
        )

        return filtered_projects

    async def _scan_directory(
        self,
        directory: Path,
        current_depth: int,
        detected_projects: list[DetectedProject],
        visited: set[str] | None = None,
    ) -> None:
        """
        Recursively scan directory for projects.

        Args:
            directory: Current directory to scan
            current_depth: Current recursion depth
            detected_projects: List to append detected projects to
            visited: Set of resolved paths to detect symlink cycles
        """
        if current_depth > self.max_depth:
            return

        # Check if this directory should be excluded
        if directory.name in self.exclude_dirs:
            return

        # Symlink cycle detection
        if visited is None:
            visited = set()
        resolved = str(directory.resolve())
        if resolved in visited:
            return
        visited.add(resolved)

        # Try to detect platform in current directory
        detection = await self._detect_platform_type(directory)
        if detection:
            detected_projects.append(detection)
            logger.debug(
                "project_detected",
                path=str(directory),
                platform=detection.platform_type.value,
                confidence=detection.confidence,
            )

        # Scan subdirectories
        try:
            for item in directory.iterdir():
                if item.is_dir() and item.name not in self.exclude_dirs:
                    await self._scan_directory(
                        item,
                        current_depth + 1,
                        detected_projects,
                        visited,
                    )
        except (PermissionError, OSError) as e:
            logger.warning(
                "directory_scan_error",
                directory=str(directory),
                error=str(e),
            )

    async def _detect_platform_type(
        self,
        directory: Path,
    ) -> DetectedProject | None:
        """
        Detect platform type for a specific directory.

        Args:
            directory: Directory to analyze

        Returns:
            DetectedProject if platform detected, None otherwise
        """
        best_match: tuple[PlatformType, float, list[str], dict] | None = None

        for platform_type, signature in self.PLATFORM_SIGNATURES.items():
            score, evidence, metadata = await self._calculate_confidence(
                directory,
                signature,
            )

            if score > 0 and (best_match is None or score > best_match[1]):
                best_match = (platform_type, score, evidence, metadata)

        if best_match is None:
            return None

        platform_type, confidence, evidence, metadata = best_match

        # Suggest role based on platform type
        role = self._suggest_role(platform_type, directory, metadata)

        return DetectedProject(
            name=directory.name,
            path=str(directory.resolve()),
            platform_type=platform_type,
            confidence=confidence,
            role=role,
            evidence=evidence,
            metadata=metadata,
        )

    async def _calculate_confidence(
        self,
        directory: Path,
        signature: dict,
    ) -> tuple[float, list[str], dict[str, str]]:
        """
        Calculate confidence score for a platform signature.

        Uses weighted scoring based on:
        - Required file existence
        - Pattern matches in files
        - Exclusion pattern checks

        Args:
            directory: Directory to check
            signature: Platform signature configuration

        Returns:
            Tuple of (confidence_score, evidence_list, metadata_dict)
        """
        score = 0.0
        evidence: list[str] = []
        metadata: dict[str, str] = {}

        required_files = signature["files"]
        patterns = signature.get("patterns", {})
        exclude_patterns = signature.get("exclude_patterns", {})
        weight = signature.get("weight", 1.0)

        # Check for required files
        files_found = 0
        for file_pattern in required_files:
            # Handle glob patterns (*.csproj, *.sln)
            if "*" in file_pattern:
                matching_files = list(directory.glob(file_pattern))
                if matching_files:
                    files_found += 1
                    evidence.append(f"Found {file_pattern}: {matching_files[0].name}")
            else:
                file_path = directory / file_pattern
                if file_path.exists():
                    files_found += 1
                    evidence.append(f"Found {file_pattern}")

        if files_found == 0:
            return (0.0, [], {})

        # Base score from file presence
        file_score = files_found / len(required_files)

        # Check content patterns
        pattern_score = 0.0
        pattern_checks = 0

        for file_pattern, content_patterns in patterns.items():
            # Handle glob patterns
            if "*" in file_pattern:
                matching_files = list(directory.glob(file_pattern))
                file_path = matching_files[0] if matching_files else None
            else:
                file_path = directory / file_pattern

            if file_path and file_path.exists():
                matches = await self._check_file_patterns(
                    file_path,
                    content_patterns,
                    metadata,
                )
                pattern_checks += len(content_patterns)
                pattern_score += matches

        # Check exclusion patterns (reduce score if found)
        exclusion_penalty = 0.0
        for file_pattern, exclude_content in exclude_patterns.items():
            if "*" in file_pattern:
                matching_files = list(directory.glob(file_pattern))
                file_path = matching_files[0] if matching_files else None
            else:
                file_path = directory / file_pattern

            if file_path and file_path.exists():
                matches = await self._check_file_patterns(
                    file_path,
                    exclude_content,
                    {},
                )
                if matches > 0:
                    exclusion_penalty = 0.5  # Reduce confidence by 50%
                    evidence.append(f"Exclusion pattern found in {file_pattern}")

        # Calculate final score
        if pattern_checks > 0:
            pattern_ratio = pattern_score / pattern_checks
        else:
            pattern_ratio = 1.0  # No patterns to check — file presence already passed

        # Weighted average of file presence and pattern matches
        confidence = (file_score * 0.4 + pattern_ratio * 0.6) * weight

        # Apply exclusion penalty
        confidence *= (1.0 - exclusion_penalty)

        return (confidence, evidence, metadata)

    async def _check_file_patterns(
        self,
        file_path: Path,
        patterns: list[str],
        metadata: dict[str, str],
    ) -> int:
        """
        Check if patterns exist in file content.

        Args:
            file_path: File to check
            patterns: List of string patterns to search for
            metadata: Dictionary to store extracted metadata

        Returns:
            Number of patterns found
        """
        try:
            # Read file content (with size limit for safety)
            max_size = 10 * 1024 * 1024  # 10 MB
            if file_path.stat().st_size > max_size:
                logger.warning(
                    "file_too_large_for_pattern_check",
                    file=str(file_path),
                    size=file_path.stat().st_size,
                )
                return 0

            content = file_path.read_text(encoding="utf-8", errors="ignore")

            matches = 0
            for pattern in patterns:
                if pattern in content:
                    matches += 1

                    # Extract version info from package.json
                    if file_path.name == "package.json":
                        await self._extract_package_json_metadata(
                            content,
                            metadata,
                        )

            return matches

        except (OSError, UnicodeDecodeError) as e:
            logger.debug(
                "file_read_error",
                file=str(file_path),
                error=str(e),
            )
            return 0

    async def _extract_package_json_metadata(
        self,
        content: str,
        metadata: dict[str, str],
    ) -> None:
        """
        Extract metadata from package.json content.

        Args:
            content: package.json file content
            metadata: Dictionary to store extracted data
        """
        try:
            data = json.loads(content)

            if "version" in data:
                metadata["version"] = data["version"]

            if "name" in data:
                metadata["package_name"] = data["name"]

            # Extract framework versions
            deps = data.get("dependencies", {})

            if "react" in deps:
                metadata["react_version"] = deps["react"]
            if "react-native" in deps:
                metadata["react_native_version"] = deps["react-native"]
            if "@angular/core" in deps:
                metadata["angular_version"] = deps["@angular/core"]
            if "vue" in deps:
                metadata["vue_version"] = deps["vue"]
            if "express" in deps:
                metadata["express_version"] = deps["express"]
            if "@nestjs/core" in deps:
                metadata["nestjs_version"] = deps["@nestjs/core"]

        except json.JSONDecodeError as e:
            logger.debug("package_json_parse_error", file="package.json", error=str(e))

    def _suggest_role(
        self,
        platform_type: PlatformType,
        directory: Path,
        metadata: dict[str, str],
    ) -> PlatformRole:
        """
        Suggest role (consumer/provider) based on platform type and context.

        Uses heuristics:
        - Mobile/Frontend platforms: consumer
        - Backend frameworks: provider
        - BFF patterns: both

        Args:
            platform_type: Detected platform type
            directory: Project directory
            metadata: Extracted metadata

        Returns:
            Suggested role
        """
        # Get typical role from signature
        signature = self.PLATFORM_SIGNATURES.get(platform_type, {})
        typical_role = signature.get("typical_role", PlatformRole.PROVIDER)

        # Check for BFF patterns (Backend for Frontend)
        # Next.js, Nuxt.js with API routes should be BOTH
        if platform_type in [PlatformType.REACT, PlatformType.VUE]:
            # Check for API directory or server code
            api_dir = directory / "api"
            pages_api = directory / "pages" / "api"
            server_dir = directory / "server"

            if api_dir.exists() or pages_api.exists() or server_dir.exists():
                logger.debug(
                    "bff_pattern_detected",
                    directory=str(directory),
                    platform=platform_type.value,
                )
                return PlatformRole.BOTH

        return typical_role
