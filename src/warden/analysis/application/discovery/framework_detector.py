"""
Framework detection for projects.

Detects frameworks based on file patterns, imports, and dependencies.
"""

import json
from pathlib import Path
from typing import List, Dict, Set, Optional

from warden.analysis.application.discovery.models import Framework, FrameworkDetectionResult


class FrameworkDetector:
    """
    Detects frameworks used in a project.

    Analyzes package.json, requirements.txt, and source files.
    """

    # Python framework detection patterns
    PYTHON_FRAMEWORK_IMPORTS: Dict[Framework, Set[str]] = {
        Framework.DJANGO: {"django", "django.conf", "django.db"},
        Framework.FLASK: {"flask", "flask.app"},
        Framework.FASTAPI: {"fastapi", "fastapi.app"},
        Framework.PYRAMID: {"pyramid", "pyramid.config"},
        Framework.TORNADO: {"tornado", "tornado.web"},
    }

    # JavaScript/TypeScript framework detection in package.json
    JS_FRAMEWORK_PACKAGES: Dict[Framework, Set[str]] = {
        Framework.REACT: {"react", "react-dom"},
        Framework.VUE: {"vue", "@vue/cli"},
        Framework.ANGULAR: {"@angular/core", "@angular/cli"},
        Framework.NEXT: {"next"},
        Framework.NUXT: {"nuxt"},
        Framework.SVELTE: {"svelte"},
        Framework.EXPRESS: {"express"},
        Framework.NEST: {"@nestjs/core", "@nestjs/common"},
    }

    def __init__(self, project_root: Path) -> None:
        """
        Initialize the framework detector.

        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root
        self.detected_frameworks: List[Framework] = []
        self.confidence_scores: Dict[str, float] = {}

    async def detect(self) -> FrameworkDetectionResult:
        """
        Detect frameworks in the project.

        Returns:
            FrameworkDetectionResult with detected frameworks

        Examples:
            >>> detector = FrameworkDetector(Path("/my/project"))
            >>> result = await detector.detect()
            >>> Framework.REACT in result.detected_frameworks
            True
        """
        # Detect Python frameworks
        await self._detect_python_frameworks()

        # Detect JavaScript/TypeScript frameworks
        await self._detect_js_frameworks()

        # Determine primary framework (highest confidence)
        primary = self._get_primary_framework()

        return FrameworkDetectionResult(
            detected_frameworks=self.detected_frameworks,
            primary_framework=primary,
            confidence_scores=self.confidence_scores,
            metadata={"project_root": str(self.project_root)},
        )

    async def _detect_python_frameworks(self) -> None:
        """Detect Python frameworks by analyzing Python files and requirements."""
        # Check requirements.txt
        requirements_path = self.project_root / "requirements.txt"
        if requirements_path.exists():
            await self._analyze_requirements(requirements_path)

        # Check pyproject.toml
        pyproject_path = self.project_root / "pyproject.toml"
        if pyproject_path.exists():
            await self._analyze_pyproject(pyproject_path)

        # Check setup.py
        setup_path = self.project_root / "setup.py"
        if setup_path.exists():
            await self._analyze_setup_py(setup_path)

        # Scan Python files for imports
        await self._scan_python_imports()

    async def _analyze_requirements(self, requirements_path: Path) -> None:
        """
        Analyze requirements.txt for framework dependencies.

        Args:
            requirements_path: Path to requirements.txt
        """
        try:
            content = requirements_path.read_text(encoding="utf-8")
            lines = content.lower().split("\n")

            for framework, imports in self.PYTHON_FRAMEWORK_IMPORTS.items():
                for package in imports:
                    package_name = package.split(".")[0]
                    if any(package_name in line for line in lines):
                        self._add_framework(framework, confidence=0.9)
                        break
        except (IOError, UnicodeDecodeError):
            pass

    async def _analyze_pyproject(self, pyproject_path: Path) -> None:
        """
        Analyze pyproject.toml for framework dependencies.

        Args:
            pyproject_path: Path to pyproject.toml
        """
        try:
            content = pyproject_path.read_text(encoding="utf-8").lower()

            for framework, imports in self.PYTHON_FRAMEWORK_IMPORTS.items():
                for package in imports:
                    package_name = package.split(".")[0]
                    if package_name in content:
                        self._add_framework(framework, confidence=0.9)
                        break
        except (IOError, UnicodeDecodeError):
            pass

    async def _analyze_setup_py(self, setup_path: Path) -> None:
        """
        Analyze setup.py for framework dependencies.

        Args:
            setup_path: Path to setup.py
        """
        try:
            content = setup_path.read_text(encoding="utf-8").lower()

            for framework, imports in self.PYTHON_FRAMEWORK_IMPORTS.items():
                for package in imports:
                    package_name = package.split(".")[0]
                    if package_name in content:
                        self._add_framework(framework, confidence=0.8)
                        break
        except (IOError, UnicodeDecodeError):
            pass

    async def _scan_python_imports(self) -> None:
        """Scan Python files for framework imports."""
        python_files = list(self.project_root.rglob("*.py"))

        # Limit to first 50 files for performance
        for py_file in python_files[:50]:
            try:
                content = py_file.read_text(encoding="utf-8")
                lines = content.split("\n")[:30]  # Check first 30 lines

                for framework, imports in self.PYTHON_FRAMEWORK_IMPORTS.items():
                    for import_pattern in imports:
                        if any(import_pattern in line for line in lines):
                            self._add_framework(framework, confidence=0.7)
                            break
            except (IOError, UnicodeDecodeError):
                continue

    async def _detect_js_frameworks(self) -> None:
        """Detect JavaScript/TypeScript frameworks by analyzing package.json."""
        package_json_path = self.project_root / "package.json"
        if not package_json_path.exists():
            return

        try:
            content = package_json_path.read_text(encoding="utf-8")
            data = json.loads(content)

            # Check dependencies and devDependencies
            dependencies = data.get("dependencies", {})
            dev_dependencies = data.get("devDependencies", {})
            all_deps = {**dependencies, **dev_dependencies}

            for framework, packages in self.JS_FRAMEWORK_PACKAGES.items():
                for package in packages:
                    if package in all_deps:
                        # Higher confidence if in dependencies vs devDependencies
                        confidence = 0.9 if package in dependencies else 0.8
                        self._add_framework(framework, confidence=confidence)
                        break
        except (IOError, json.JSONDecodeError, UnicodeDecodeError):
            pass

    def _add_framework(self, framework: Framework, confidence: float) -> None:
        """
        Add a detected framework with confidence score.

        Args:
            framework: Detected framework
            confidence: Confidence score (0.0 to 1.0)
        """
        if framework not in self.detected_frameworks:
            self.detected_frameworks.append(framework)

        # Update confidence score (take maximum if multiple detections)
        framework_key = framework.value
        current_confidence = self.confidence_scores.get(framework_key, 0.0)
        self.confidence_scores[framework_key] = max(current_confidence, confidence)

    def _get_primary_framework(self) -> Optional[Framework]:
        """
        Get the primary framework (highest confidence).

        Returns:
            Primary framework or None if no frameworks detected
        """
        if not self.detected_frameworks:
            return None

        # Sort by confidence score
        sorted_frameworks = sorted(
            self.detected_frameworks,
            key=lambda f: self.confidence_scores.get(f.value, 0.0),
            reverse=True,
        )

        return sorted_frameworks[0]


async def detect_frameworks(project_root: Path) -> FrameworkDetectionResult:
    """
    Detect frameworks in a project.

    Args:
        project_root: Root directory of the project

    Returns:
        FrameworkDetectionResult with detected frameworks

    Examples:
        >>> result = await detect_frameworks(Path("/my/project"))
        >>> print(f"Detected: {result.primary_framework}")
        Detected: Framework.REACT
    """
    detector = FrameworkDetector(project_root)
    return await detector.detect()
