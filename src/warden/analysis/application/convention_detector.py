"""
Project Convention Detection Module.

Detects project conventions and patterns during PRE-ANALYSIS phase.
"""

from pathlib import Path
from typing import Dict, List, Set
import structlog

from warden.analysis.domain.project_context import ProjectConventions

logger = structlog.get_logger()


class ConventionDetector:
    """
    Detects project conventions and patterns.

    Part of the PRE-ANALYSIS phase for context detection.
    """

    def __init__(
        self,
        project_root: Path,
        config_files: Dict[str, str],
        special_dirs: Dict[str, List[str]],
        file_extensions: Set[str],
    ):
        """
        Initialize convention detector.

        Args:
            project_root: Root directory of the project
            config_files: Detected configuration files
            special_dirs: Special directories found
            file_extensions: File extensions in project
        """
        self.project_root = project_root
        self.config_files = config_files
        self.special_dirs = special_dirs
        self.file_extensions = file_extensions

    def detect(self) -> ProjectConventions:
        """
        Detect project conventions and patterns.

        Returns:
            ProjectConventions with detected patterns
        """
        logger.debug("convention_detection_started")

        conv = ProjectConventions()

        # Detect file naming convention
        conv.file_naming = self._detect_file_naming()

        # Detect test location
        if "test" in self.special_dirs:
            conv.test_location = self.special_dirs["test"][0]

        # Detect source location
        if "source" in self.special_dirs:
            conv.source_location = self.special_dirs["source"][0]

        # Detect docs location
        if "docs" in self.special_dirs:
            conv.docs_location = self.special_dirs["docs"][0]

        # Check for type hints (Python)
        if ".py" in self.file_extensions:
            conv.uses_type_hints = self._detect_type_hints()

        # Check for linter/formatter configs
        conv.uses_linter = self._detect_linter()
        conv.uses_formatter = self._detect_formatter()

        logger.debug(
            "convention_detection_completed",
            file_naming=conv.file_naming,
            uses_type_hints=conv.uses_type_hints,
            uses_linter=conv.uses_linter,
        )

        return conv

    def _detect_file_naming(self) -> str:
        """Detect file naming convention."""
        # Sample Python files for naming convention
        py_files = list(self.project_root.rglob("*.py"))[:100]

        if not py_files:
            return ""

        file_names = [f.stem for f in py_files if f.is_file()]

        if not file_names:
            return ""

        # Count naming styles
        snake_count = sum(1 for name in file_names if "_" in name or name.islower())
        kebab_count = sum(1 for name in file_names if "-" in name)
        pascal_count = sum(1 for name in file_names if name and name[0].isupper())

        # Determine predominant style
        if snake_count > max(kebab_count, pascal_count):
            return "snake_case"
        elif kebab_count > pascal_count:
            return "kebab-case"
        elif pascal_count > 0:
            return "PascalCase"

        return "snake_case"  # Default for Python

    def _detect_type_hints(self) -> bool:
        """Detect if Python type hints are used."""
        # Sample a few Python files
        py_files = list(self.project_root.rglob("*.py"))[:10]

        if not py_files:
            return False

        type_hint_count = 0
        for py_file in py_files:
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(5000)  # Read first 5000 chars
                    # Look for type hints patterns
                    if "-> " in content or ": " in content:
                        if any(pattern in content for pattern in [
                            ": str", ": int", ": bool", ": float",
                            ": Dict", ": List", ": Optional", ": Any",
                            "-> str", "-> int", "-> bool", "-> None",
                            "-> Dict", "-> List", "-> Optional",
                        ]):
                            type_hint_count += 1
            except Exception as e:
                logger.debug("type_hint_detection_error", file=str(py_file), error=str(e))
                continue

        # If more than half of sampled files have type hints
        return type_hint_count > len(py_files) / 2

    def _detect_linter(self) -> bool:
        """Detect if linter configuration exists."""
        linter_configs = [
            ".flake8", ".eslintrc.json", "ruff.toml", ".ruff.toml",
            ".pylintrc", "tslint.json", ".eslintrc.js", ".eslintrc.yml",
        ]

        return any(config in self.config_files for config in linter_configs)

    def _detect_formatter(self) -> bool:
        """Detect if formatter configuration exists."""
        formatter_configs = [
            ".prettierrc", "pyproject.toml", ".style.yapf",
            ".prettierrc.json", ".prettierrc.js", ".prettierrc.yml",
            ".editorconfig", "black", ".blackrc",
        ]

        # Check direct config files
        if any(config in self.config_files for config in formatter_configs):
            return True

        # Check pyproject.toml for black/ruff configuration
        pyproject_path = self.project_root / "pyproject.toml"
        if pyproject_path.exists():
            try:
                with open(pyproject_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if "[tool.black]" in content or "[tool.ruff]" in content:
                        return True
            except Exception:
                pass

        return False