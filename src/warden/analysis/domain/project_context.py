"""
Project Context Model for PRE-ANALYSIS Phase.

Provides comprehensive project structure understanding and context detection
for the context-aware analysis system.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
from pathlib import Path

from warden.shared.domain.base_model import BaseDomainModel


class ProjectType(Enum):
    """
    Type of project being analyzed.

    Determines high-level analysis strategies.
    """

    MONOREPO = "monorepo"  # Multiple projects in one repo
    LIBRARY = "library"  # Reusable library/package
    APPLICATION = "application"  # Standalone application
    CLI_TOOL = "cli"  # Command-line interface tool
    MICROSERVICE = "microservice"  # Single microservice
    API = "api"  # API-only project
    FRONTEND = "frontend"  # Frontend application
    FULLSTACK = "fullstack"  # Full-stack application
    UNKNOWN = "unknown"  # Cannot determine


class Framework(Enum):
    """
    Detected framework for the project.

    Used to apply framework-specific rules.
    """

    # Python frameworks
    DJANGO = "django"
    FASTAPI = "fastapi"
    FLASK = "flask"
    PYRAMID = "pyramid"

    # Frontend frameworks
    REACT = "react"
    VUE = "vue"
    ANGULAR = "angular"
    SVELTE = "svelte"
    NEXTJS = "nextjs"

    # Other
    EXPRESS = "express"
    SPRING = "spring"
    RAILS = "rails"
    LARAVEL = "laravel"

    NONE = "none"  # No framework detected
    CUSTOM = "custom"  # Custom framework


class Architecture(Enum):
    """
    Detected architecture pattern.

    Helps understand code organization.
    """

    MVC = "mvc"  # Model-View-Controller
    MVP = "mvp"  # Model-View-Presenter
    MVVM = "mvvm"  # Model-View-ViewModel
    MICROSERVICES = "microservices"  # Microservices architecture
    LAYERED = "layered"  # Layered/N-tier architecture
    HEXAGONAL = "hexagonal"  # Hexagonal/Ports&Adapters
    CLEAN = "clean"  # Clean architecture
    DDD = "ddd"  # Domain-Driven Design
    EVENT_DRIVEN = "event_driven"  # Event-driven architecture
    SERVERLESS = "serverless"  # Serverless/FaaS
    MONOLITHIC = "monolithic"  # Traditional monolithic
    UNKNOWN = "unknown"  # Cannot determine


class TestFramework(Enum):
    """
    Detected test framework.

    Used for test file identification.
    """

    # Python
    PYTEST = "pytest"
    UNITTEST = "unittest"
    NOSE = "nose"
    HYPOTHESIS = "hypothesis"

    # JavaScript
    JEST = "jest"
    MOCHA = "mocha"
    JASMINE = "jasmine"
    VITEST = "vitest"

    # Other
    JUNIT = "junit"
    RSPEC = "rspec"
    PHPUNIT = "phpunit"

    NONE = "none"  # No test framework
    UNKNOWN = "unknown"  # Cannot determine


class BuildTool(Enum):
    """
    Detected build/dependency tool.

    Helps understand project setup.
    """

    # Python
    POETRY = "poetry"
    PIP = "pip"
    PIPENV = "pipenv"
    CONDA = "conda"
    PDM = "pdm"

    # JavaScript
    NPM = "npm"
    YARN = "yarn"
    PNPM = "pnpm"
    BUN = "bun"

    # Java
    MAVEN = "maven"
    GRADLE = "gradle"

    # Other
    DOCKER = "docker"
    MAKE = "make"

    NONE = "none"
    UNKNOWN = "unknown"


@dataclass
class ProjectStatistics(BaseDomainModel):
    """
    Statistical information about the project.

    Provides quantitative metrics for context.
    """

    total_files: int = 0
    total_lines: int = 0
    code_files: int = 0
    test_files: int = 0
    config_files: int = 0
    documentation_files: int = 0

    # Language distribution (language -> file count)
    language_distribution: Dict[str, int] = field(default_factory=dict)

    # Directory statistics
    max_depth: int = 0  # Maximum directory depth
    average_file_size: float = 0.0  # Average file size in lines

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            "totalFiles": self.total_files,
            "totalLines": self.total_lines,
            "codeFiles": self.code_files,
            "testFiles": self.test_files,
            "configFiles": self.config_files,
            "documentationFiles": self.documentation_files,
            "languageDistribution": self.language_distribution,
            "maxDepth": self.max_depth,
            "averageFileSize": round(self.average_file_size, 2),
        }


@dataclass
class ProjectConventions(BaseDomainModel):
    """
    Detected project conventions and patterns.

    Used to apply appropriate analysis rules.
    """

    # Naming conventions
    file_naming: str = ""  # e.g., "snake_case", "kebab-case", "PascalCase"
    class_naming: str = ""  # e.g., "PascalCase"
    function_naming: str = ""  # e.g., "snake_case", "camelCase"
    variable_naming: str = ""  # e.g., "snake_case", "camelCase"

    # File organization
    test_location: str = ""  # e.g., "tests/", "test/", "__tests__/"
    source_location: str = ""  # e.g., "src/", "lib/", "app/"
    docs_location: str = ""  # e.g., "docs/", "documentation/"

    # Code style
    indent_style: str = ""  # e.g., "spaces", "tabs"
    indent_size: int = 4  # Number of spaces/tabs
    max_line_length: int = 0  # 0 means not detected

    # Special patterns
    uses_type_hints: bool = False  # Python type hints
    uses_docstrings: bool = False  # Documentation strings
    uses_linter: bool = False  # Linter configuration detected
    uses_formatter: bool = False  # Formatter configuration detected

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            "naming": {
                "files": self.file_naming,
                "classes": self.class_naming,
                "functions": self.function_naming,
                "variables": self.variable_naming,
            },
            "organization": {
                "testLocation": self.test_location,
                "sourceLocation": self.source_location,
                "docsLocation": self.docs_location,
            },
            "codeStyle": {
                "indentStyle": self.indent_style,
                "indentSize": self.indent_size,
                "maxLineLength": self.max_line_length,
            },
            "features": {
                "usesTypeHints": self.uses_type_hints,
                "usesDocstrings": self.uses_docstrings,
                "usesLinter": self.uses_linter,
                "usesFormatter": self.uses_formatter,
            }
        }


@dataclass
class ProjectContext(BaseDomainModel):
    """
    Complete project context for PRE-ANALYSIS phase.

    Provides comprehensive understanding of the project structure
    and characteristics for context-aware analysis.
    """

    # Basic information
    project_root: str = ""
    project_name: str = ""

    # Project characteristics
    project_type: ProjectType = ProjectType.UNKNOWN
    framework: Framework = Framework.NONE
    architecture: Architecture = Architecture.UNKNOWN

    # Development tools
    test_framework: TestFramework = TestFramework.NONE
    build_tools: List[BuildTool] = field(default_factory=list)

    # Detected conventions
    conventions: ProjectConventions = field(default_factory=ProjectConventions)

    # Statistics
    statistics: ProjectStatistics = field(default_factory=ProjectStatistics)

    # Configuration files detected
    config_files: Dict[str, str] = field(default_factory=dict)  # filename -> type

    # Special directories
    special_dirs: Dict[str, List[str]] = field(default_factory=dict)
    # e.g., {"vendor": ["node_modules/", "vendor/"], "generated": ["gen/", "build/"]}

    # Context confidence (0.0 to 1.0)
    confidence: float = 0.0

    # Detection metadata
    detection_time: float = 0.0  # Time taken for detection in seconds
    detection_warnings: List[str] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            "projectRoot": self.project_root,
            "projectName": self.project_name,
            "projectType": self.project_type.value,
            "framework": self.framework.value,
            "architecture": self.architecture.value,
            "testFramework": self.test_framework.value,
            "buildTools": [tool.value for tool in self.build_tools],
            "conventions": self.conventions.to_json(),
            "statistics": self.statistics.to_json(),
            "configFiles": self.config_files,
            "specialDirs": self.special_dirs,
            "confidence": round(self.confidence, 2),
            "detectionTime": round(self.detection_time, 3),
            "detectionWarnings": self.detection_warnings,
        }

    def get_context_summary(self) -> str:
        """
        Get human-readable context summary.

        Returns:
            Formatted string with key context information
        """
        summary_parts = [
            f"Project: {self.project_name}",
            f"Type: {self.project_type.value}",
            f"Framework: {self.framework.value}",
            f"Architecture: {self.architecture.value}",
            f"Test Framework: {self.test_framework.value}",
            f"Build Tools: {', '.join(t.value for t in self.build_tools)}",
            f"Total Files: {self.statistics.total_files}",
            f"Confidence: {self.confidence:.1%}",
        ]

        return " | ".join(summary_parts)

    @property
    def name(self) -> str:
        """
        Get the context name based on project_type.

        Returns:
            The project type value as a string
        """
        return self.project_type.value

    def should_apply_strict_rules(self) -> bool:
        """
        Determine if strict analysis rules should be applied.

        Returns:
            True if this is production code requiring strict analysis
        """
        # Libraries and APIs typically need stricter rules
        strict_types = {
            ProjectType.LIBRARY,
            ProjectType.API,
            ProjectType.MICROSERVICE,
        }

        return self.project_type in strict_types

    def get_ignored_paths(self) -> List[str]:
        """
        Get list of paths that should be ignored in analysis.

        Returns:
            List of path patterns to ignore
        """
        ignored = []

        # Add vendor directories
        if "vendor" in self.special_dirs:
            ignored.extend(self.special_dirs["vendor"])

        # Add generated directories
        if "generated" in self.special_dirs:
            ignored.extend(self.special_dirs["generated"])

        # Add build directories
        if "build" in self.special_dirs:
            ignored.extend(self.special_dirs["build"])

        # Common patterns to ignore
        common_ignored = [
            "__pycache__/",
            "*.pyc",
            ".git/",
            ".venv/",
            "venv/",
            "env/",
            "node_modules/",
            "dist/",
            "build/",
            ".pytest_cache/",
            ".mypy_cache/",
            ".ruff_cache/",
            ".coverage",
            "*.egg-info/",
        ]

        ignored.extend(common_ignored)

        return list(set(ignored))  # Remove duplicates