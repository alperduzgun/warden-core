"""
Project Structure Analyzer Service.

Analyzes project structure to detect project type, framework, architecture,
and other characteristics for the PRE-ANALYSIS phase.
"""

import asyncio
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
import json
import structlog
try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Fallback for older versions

from warden.analysis.domain.project_context import (
    ProjectContext,
    ProjectType,
    Framework,
    Architecture,
    TestFramework,
    BuildTool,
    ProjectStatistics,
    ProjectConventions,
)
from warden.llm.config import LlmConfiguration
from warden.analysis.application.discovery.gitignore_filter import create_gitignore_filter

logger = structlog.get_logger()


class ProjectStructureAnalyzer:
    """
    Analyzes project structure to understand project characteristics.

    Part of the PRE-ANALYSIS phase for context detection.
    """

    def __init__(
        self, 
        project_root: Path, 
        llm_config: Optional[LlmConfiguration] = None,
        analysis_level: Optional[Any] = None,
        llm_service: Optional[Any] = None
    ) -> None:
        """
        Initialize analyzer with project root.
        
        Args:
            project_root: Root directory of the project to analyze
            llm_config: Optional LLM configuration
            llm_service: Optional shared LLM service
        """
        self.project_root = Path(project_root)
        self.llm_config = llm_config
        self.llm_service = llm_service
        self.config_files: Dict[str, str] = {}
        self.special_dirs: Dict[str, List[str]] = {}
        self.file_extensions: Set[str] = set()
        self.directory_structure: Dict[str, int] = {}  # dir -> file count
        self.framework = None  # Will be set during analysis
        self.analysis_level = analysis_level
        self._injected_files: Optional[List[Path]] = None
        
        # Initialize Gitignore Filter
        self.gitignore_filter = create_gitignore_filter(self.project_root)

    async def analyze_async(
        self, 
        initial_context: Optional[ProjectContext] = None,
        all_files: Optional[List[Path]] = None
    ) -> ProjectContext:
        """
        Analyze project structure and detect characteristics.

        Args:
            initial_context: Optional pre-initialized context (e.g. from memory)
            all_files: Optional list of pre-discovered files to avoid redundant disk walk
            
        Returns:
            ProjectContext with detected information
        """
        self._injected_files = all_files
        start_time = time.perf_counter()

        logger.info(
            "project_structure_analysis_started",
            project_root=str(self.project_root),
        )

        # Initialize context
        context = initial_context or ProjectContext(
            project_root=str(self.project_root),
            project_name=self.project_root.name,
        )

        # Ensure we have a filtered list of files to process (Respects .gitignore)
        if self._injected_files is None:
            self._injected_files = self.get_all_files()

        try:
            # Run all detection tasks in parallel
            detection_tasks = [
                self._detect_config_files_async(),
                self._analyze_directory_structure_async(),
                self._collect_statistics_async(),
            ]

            results = await asyncio.gather(*detection_tasks, return_exceptions=True)

            # Process results
            for result in results:
                if isinstance(result, Exception):
                    logger.warning(
                        "detection_task_failed",
                        error=str(result),
                    )
                    context.detection_warnings.append(str(result))

            # Assign results to context/self early so detectors can use them
            # results[0] -> _detect_config_files_async (None, updates self.config_files)
            # results[1] -> _analyze_directory_structure_async (None, updates self.special_dirs)
            # results[2] -> _collect_statistics_async (ProjectStatistics)
            if len(results) > 2 and not isinstance(results[2], Exception):
                context.statistics = results[2]
            
            context.config_files = self.config_files
            context.special_dirs = self.special_dirs

            # Sequential detection based on collected data
            context.project_type = self._detect_project_type()
            context.framework = self._detect_framework()
            context.architecture = self._detect_architecture()
            context.test_framework = self._detect_test_framework()
            context.build_tools = self._detect_build_tools()
            context.conventions = self._detect_conventions()
            
            # Detect language and SDKs
            context.primary_language, context.detected_languages, context.language_breakdown = self._detect_languages(context.statistics)
            context.sdk_versions = self._detect_sdk_versions()
            
            # Detect service abstractions
            context.service_abstractions = await self._detect_service_abstractions_async(context)

            # Calculate confidence
            context.confidence = self._calculate_confidence(context)

            # Set timing
            context.detection_time = time.perf_counter() - start_time

            logger.info(
                "project_structure_analysis_completed",
                project_type=context.project_type.value,
                framework=context.framework.value,
                confidence=context.confidence,
                duration=context.detection_time,
            )

            return context

        except Exception as e:
            logger.error(
                "project_structure_analysis_failed",
                error=str(e),
            )
            context.detection_warnings.append(f"Analysis failed: {str(e)}")
            context.detection_time = time.perf_counter() - start_time
            return context

    def get_all_files(self) -> List[Path]:
        """
        Get all files in the project, respecting gitignore rules.
        
        Returns:
            List of Path objects for all valid files.
        """
        if self._injected_files is not None:
            return self._injected_files

        logger.warning("project_structure_analyzer_fallback_to_sync_rglob", reason="no_injected_files")
        files = []
        for file_path in self.project_root.rglob("*"):
            if file_path.is_file() and not self.gitignore_filter.should_ignore(file_path):
                files.append(file_path)
        return files

    async def _detect_config_files_async(self) -> None:
        """Detect and categorize configuration files."""
        config_patterns = {
            # Python
            "pyproject.toml": "python-poetry",
            "setup.py": "python-setuptools",
            "setup.cfg": "python-setuptools",
            "requirements.txt": "python-pip",
            "Pipfile": "python-pipenv",
            "environment.yml": "python-conda",
            "tox.ini": "python-tox",
            ".python-version": "python-version",
            "pyrightconfig.json": "python-pyright",
            "mypy.ini": "python-mypy",
            ".flake8": "python-flake8",
            "ruff.toml": "python-ruff",
            ".ruff.toml": "python-ruff",
            "pytest.ini": "python-pytest",

            # JavaScript/TypeScript
            "package.json": "javascript-npm",
            "package-lock.json": "javascript-npm-lock",
            "yarn.lock": "javascript-yarn-lock",
            "pnpm-lock.yaml": "javascript-pnpm-lock",
            "tsconfig.json": "typescript",
            "jsconfig.json": "javascript-config",
            ".eslintrc.json": "javascript-eslint",
            ".prettierrc": "javascript-prettier",
            "vite.config.js": "javascript-vite",
            "webpack.config.js": "javascript-webpack",
            "next.config.js": "javascript-nextjs",
            "nuxt.config.js": "javascript-nuxt",
            "angular.json": "javascript-angular",
            "vue.config.js": "javascript-vue",
            
            # Dart/Flutter
            "pubspec.yaml": "dart-pub",
            "pubspec.lock": "dart-pub-lock",
            "analysis_options.yaml": "dart-analysis",

            # Build tools
            "Dockerfile": "docker",
            "docker-compose.yml": "docker-compose",
            "docker-compose.yaml": "docker-compose",
            "Makefile": "make",
            "CMakeLists.txt": "cmake",
            "build.gradle": "gradle",
            "pom.xml": "maven",

            # CI/CD
            ".gitlab-ci.yml": "gitlab-ci",
            ".github/workflows": "github-actions",
            ".travis.yml": "travis-ci",
            "Jenkinsfile": "jenkins",
            ".circleci/config.yml": "circleci",
            "azure-pipelines.yml": "azure-devops",

            # Other
            ".gitignore": "git",
            ".env": "environment",
            ".env.example": "environment-example",
            "README.md": "documentation",
            "LICENSE": "license",
            ".editorconfig": "editor-config",
        }

        for pattern, file_type in config_patterns.items():
            file_path = self.project_root / pattern
            if file_path.exists() and file_path.is_file():
                self.config_files[pattern] = file_type
            elif file_path.exists() and file_path.is_dir():
                # For directories like .github/workflows
                self.config_files[pattern] = file_type

    async def _analyze_directory_structure_async(self) -> None:
        """Analyze directory structure and identify special directories."""
        special_patterns = {
            "vendor": ["vendor", "node_modules", "bower_components", ".vendor"],
            "generated": ["generated", "gen", "build", "dist", "out", "_build", "target"],
            "test": ["test", "tests", "__tests__", "spec", "specs", "test_", "_test"],
            "docs": ["docs", "documentation", "doc"],
            "config": ["config", "configs", ".config", "configuration"],
            "scripts": ["scripts", "bin", "tools"],
            "source": ["src", "source", "lib", "app", "core"],
            "migrations": ["migrations", "migrate", "alembic", "db_migrations"],
            "fixtures": ["fixtures", "mocks", "stubs", "fakes"],
        }

        # Walk through directories (limited depth for performance)
        for special_type, patterns in special_patterns.items():
            found_dirs = []
            for pattern in patterns:
                # Check root level
                dir_path = self.project_root / pattern
                if dir_path.exists() and dir_path.is_dir():
                    found_dirs.append(f"{pattern}/")

                # Check one level deep
                for subdir in self.project_root.iterdir():
                    if subdir.is_dir() and not subdir.name.startswith('.'):
                        sub_path = subdir / pattern
                        if sub_path.exists() and sub_path.is_dir():
                            found_dirs.append(f"{subdir.name}/{pattern}/")

            if found_dirs:
                self.special_dirs[special_type] = found_dirs

        # Collect file extensions (using filtered list)
        for file_path in self.get_all_files():
            # Files are already filtered by get_all_files()
            ext = file_path.suffix
            if ext:
                self.file_extensions.add(ext)

            # Count files per directory
            parent_dir = file_path.parent.relative_to(self.project_root)
            dir_str = str(parent_dir) if str(parent_dir) != "." else "root"
            self.directory_structure[dir_str] = self.directory_structure.get(dir_str, 0) + 1

    async def _collect_statistics_async(self) -> ProjectStatistics:
        """Collect statistical information about the project."""
        from warden.analysis.application.statistics_collector import StatisticsCollector

        collector = StatisticsCollector(self.project_root, self.special_dirs)
        return await collector.collect_async(all_files=self._injected_files)

    def _detect_languages(self, stats: ProjectStatistics) -> tuple[str, List[str], Dict[str, float]]:
        """
        Detect all languages using pre-calculated statistics (DRY).
        """
        detected_languages_set = set()
        config_detected_languages = set()
        
        # 1. Config Files (Intent) - Unchanged
        if "go.mod" in self.config_files: config_detected_languages.add("go")
        if "Cargo.toml" in self.config_files: config_detected_languages.add("rust")
        if "pubspec.yaml" in self.config_files: config_detected_languages.add("dart")
        if "pom.xml" in self.config_files or "build.gradle" in self.config_files: config_detected_languages.add("java")
        if "package.json" in self.config_files:
            if "tsconfig.json" in self.config_files: config_detected_languages.add("typescript")
            else: config_detected_languages.add("javascript")
        if "pyproject.toml" in self.config_files or "setup.py" in self.config_files:
            config_detected_languages.add("python")

        # 2. Percentage Calculation (Reuse StatisticsCollector data)
        # Use Byte Counts (GitHub Style) if available, else File Counts
        breakdown = {}
        counts = {}
        
        use_bytes = bool(stats.language_bytes) # Check if we have byte data
        source_data = stats.language_bytes if use_bytes else stats.language_distribution
        
        total_value = sum(source_data.values()) if source_data else 1
        
        for lang_enum, value in source_data.items():
            lang_id = lang_enum.value
            
            # Skip if value is 0
            if value == 0: continue
            
            counts[lang_id] = value
            percent = (value / total_value) * 100
            breakdown[lang_id] = round(percent, 1)

        threshold_percent = 2.0
        dominant_lang = max(counts, key=counts.get) if counts else None

        for lang, percent in breakdown.items():
            if percent >= threshold_percent or lang == dominant_lang:
                detected_languages_set.add(lang)
        
        # Always include config-based
        detected_languages_set.update(config_detected_languages)

        # Determine Primary
        primary_lang = "unknown"
        if dominant_lang and dominant_lang in config_detected_languages:
            primary_lang = dominant_lang
        elif config_detected_languages:
            # First valid config lang
            order = ["dart", "go", "rust", "python", "typescript", "javascript", "java"]
            for l in order:
                if l in config_detected_languages:
                    primary_lang = l
                    break
            if primary_lang == "unknown": primary_lang = sorted(list(config_detected_languages))[0]
        elif dominant_lang:
            primary_lang = dominant_lang

        return primary_lang, list(detected_languages_set), breakdown

    def _detect_sdk_versions(self) -> Dict[str, str]:
        """Detect SDK versions from configuration files."""
        versions = {}

        # Python version
        if "pyproject.toml" in self.config_files:
            try:
                with open(self.project_root / "pyproject.toml", "rb") as f:
                    data = tomllib.load(f)
                    # Support both [tool.poetry] and [project] (PEP 621)
                    python_req = (data.get("tool", {}).get("poetry", {}).get("dependencies", {}).get("python") or
                                 data.get("project", {}).get("requires-python"))
                    if python_req:
                        versions["python"] = python_req
            except (FileNotFoundError, PermissionError, tomllib.TOMLDecodeError, KeyError):
                pass  # Graceful degradation - version detection is optional

        if ".python-version" in self.config_files:
            try:
                with open(self.project_root / ".python-version") as f:
                    versions["python"] = f.read().strip()
            except (FileNotFoundError, PermissionError, IOError):
                pass  # Graceful degradation

        # Node.js version
        if "package.json" in self.config_files:
            try:
                with open(self.project_root / "package.json") as f:
                    data = json.load(f)
                    if "engines" in data and "node" in data["engines"]:
                        versions["node"] = data["engines"]["node"]
            except (FileNotFoundError, PermissionError, json.JSONDecodeError, KeyError):
                pass  # Graceful degradation

        if ".nvmrc" in self.config_files:
            try:
                with open(self.project_root / ".nvmrc") as f:
                    versions["node"] = f.read().strip()
            except (FileNotFoundError, PermissionError, IOError):
                pass  # Graceful degradation
                
        # TODO: Add more SDKs (Java, Go, etc.) as needed

        return versions

    def _detect_project_type(self) -> ProjectType:
        """Detect the type of project."""
        # Check for specific indicators
        if "package.json" in self.config_files:
            package_json = self.project_root / "package.json"
            try:
                with open(package_json) as f:
                    data = json.load(f)
                    if "bin" in data:
                        return ProjectType.CLI_TOOL
                    if not data.get("private"):
                        return ProjectType.LIBRARY
            except (FileNotFoundError, PermissionError, json.JSONDecodeError, KeyError):
                pass  # Fall through to other detection methods

        if "setup.py" in self.config_files or "pyproject.toml" in self.config_files:
            # Check if it's a library
            if "src" in self.special_dirs.get("source", []) or "lib" in self.special_dirs.get("source", []):
                return ProjectType.LIBRARY

        # API indicators (detect framework inline since it's not set yet)
        framework = self._detect_framework()
        if framework in [Framework.FASTAPI, Framework.FLASK, Framework.EXPRESS]:
            return ProjectType.API

        # Frontend indicators
        if any(f in self.config_files for f in ["vite.config.js", "webpack.config.js", "angular.json"]):
            return ProjectType.FRONTEND

        # Microservice indicators
        if "Dockerfile" in self.config_files and "docker-compose.yml" not in self.config_files:
            if self.directory_structure.get("root", 0) < 50:  # Small project
                return ProjectType.MICROSERVICE

        # Monorepo indicators
        if any(d in self.special_dirs.get("source", []) for d in ["packages/", "apps/", "services/"]):
            return ProjectType.MONOREPO

        # Full-stack indicators
        if ("frontend" in self.special_dirs.get("source", []) or "client" in self.special_dirs.get("source", [])) and \
           ("backend" in self.special_dirs.get("source", []) or "server" in self.special_dirs.get("source", [])):
            return ProjectType.FULLSTACK

        # Default to application
        if self.directory_structure:
            return ProjectType.APPLICATION

        return ProjectType.UNKNOWN

    def _detect_framework(self) -> Framework:
        """Detect the main framework used."""
        from warden.analysis.application.framework_detector import FrameworkDetector

        detector = FrameworkDetector(self.project_root, self.config_files)
        return detector.detect()

    def _detect_architecture(self) -> Architecture:
        """Detect the architecture pattern."""
        # Check directory structure
        dirs = set(self.directory_structure.keys())

        # MVC pattern
        if {"models", "views", "controllers"}.issubset(dirs) or \
           {"model", "view", "controller"}.issubset(dirs):
            return Architecture.MVC

        # Layered architecture
        if {"presentation", "business", "data"}.issubset(dirs) or \
           {"ui", "service", "repository"}.issubset(dirs) or \
           {"api", "core", "infrastructure"}.issubset(dirs):
            return Architecture.LAYERED

        # Hexagonal/Clean architecture
        if {"domain", "application", "infrastructure"}.issubset(dirs) or \
           {"entities", "use_cases", "adapters"}.issubset(dirs):
            return Architecture.HEXAGONAL

        # DDD
        if {"domain", "application", "infrastructure", "presentation"}.issubset(dirs):
            return Architecture.DDD

        # Microservices
        if "services" in dirs or "microservices" in dirs:
            return Architecture.MICROSERVICES

        # Event-driven
        if any(d in dirs for d in ["events", "handlers", "listeners", "publishers"]):
            return Architecture.EVENT_DRIVEN

        # Serverless
        if "functions" in dirs or "lambdas" in dirs:
            return Architecture.SERVERLESS

        # Default to monolithic for simple structures
        if len(dirs) < 10:
            return Architecture.MONOLITHIC

        return Architecture.UNKNOWN

    def _detect_test_framework(self) -> TestFramework:
        """Detect the test framework used."""
        # Python test frameworks
        if "pytest.ini" in self.config_files or "pytest.toml" in self.config_files:
            return TestFramework.PYTEST

        if any("pytest" in str(p).lower() for p in self.project_root.rglob("*requirements*.txt")):
            return TestFramework.PYTEST

        if any("unittest" in str(p).lower() for p in self.project_root.rglob("test_*.py")):
            return TestFramework.UNITTEST

        # JavaScript test frameworks
        if "package.json" in self.config_files:
            package_json = self.project_root / "package.json"
            try:
                with open(package_json) as f:
                    data = json.load(f)
                    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}

                    if "jest" in deps:
                        return TestFramework.JEST
                    if "mocha" in deps:
                        return TestFramework.MOCHA
                    if "jasmine" in deps:
                        return TestFramework.JASMINE
                    if "vitest" in deps:
                        return TestFramework.VITEST
            except (FileNotFoundError, PermissionError, json.JSONDecodeError, KeyError):
                pass  # Fall through to other detection methods

        # Check for test directories
        if "test" in self.special_dirs or "tests" in self.special_dirs:
            # Default based on language
            if ".py" in self.file_extensions:
                return TestFramework.PYTEST
            if ".js" in self.file_extensions or ".ts" in self.file_extensions:
                return TestFramework.JEST

        return TestFramework.NONE

    def _detect_build_tools(self) -> List[BuildTool]:
        """Detect build and dependency management tools."""
        tools = []

        # Python tools
        if "pyproject.toml" in self.config_files:
            pyproject = self.project_root / "pyproject.toml"
            try:
                with open(pyproject, 'rb') as f:
                    data = tomllib.load(f)
                    if "tool" in data and "poetry" in data["tool"]:
                        tools.append(BuildTool.POETRY)
                    elif "project" in data:
                        tools.append(BuildTool.PIP)
            except (FileNotFoundError, PermissionError, tomllib.TOMLDecodeError, KeyError):
                pass  # Graceful degradation - continue with other tool detection

        if "requirements.txt" in self.config_files:
            tools.append(BuildTool.PIP)
        if "Pipfile" in self.config_files:
            tools.append(BuildTool.PIPENV)
        if "environment.yml" in self.config_files:
            tools.append(BuildTool.CONDA)

        # JavaScript tools
        if "package-lock.json" in self.config_files:
            tools.append(BuildTool.NPM)
        elif "yarn.lock" in self.config_files:
            tools.append(BuildTool.YARN)
        elif "pnpm-lock.yaml" in self.config_files:
            tools.append(BuildTool.PNPM)

        # Java tools
        if "pom.xml" in self.config_files:
            tools.append(BuildTool.MAVEN)
        if "build.gradle" in self.config_files:
            tools.append(BuildTool.GRADLE)

        # General tools
        if "Dockerfile" in self.config_files:
            tools.append(BuildTool.DOCKER)
        if "Makefile" in self.config_files:
            tools.append(BuildTool.MAKE)

        return tools if tools else [BuildTool.NONE]

    def _detect_conventions(self) -> ProjectConventions:
        """Detect project conventions and patterns."""
        from warden.analysis.application.convention_detector import ConventionDetector

        detector = ConventionDetector(
            self.project_root,
            self.config_files,
            self.special_dirs,
            self.file_extensions,
        )
        return detector.detect()

    def _calculate_confidence(self, context: ProjectContext) -> float:
        """
        Calculate confidence score for detection results.

        Args:
            context: Detected project context

        Returns:
            Confidence score between 0.0 and 1.0
        """
        confidence = 0.0
        factors = 0

        # Project type detection confidence
        if context.project_type != ProjectType.UNKNOWN:
            confidence += 0.2
            factors += 1

        # Framework detection confidence
        if context.framework != Framework.NONE:
            confidence += 0.2
            factors += 1

        # Architecture detection confidence
        if context.architecture != Architecture.UNKNOWN:
            confidence += 0.15
            factors += 1

        # Test framework detection confidence
        if context.test_framework != TestFramework.NONE:
            confidence += 0.15
            factors += 1

        # Build tools detection confidence
        if context.build_tools and BuildTool.NONE not in context.build_tools:
            confidence += 0.15
            factors += 1

        # Config files detected
        if len(context.config_files) > 3:
            confidence += 0.1
            factors += 1

        # Statistics collected
        if context.statistics.total_files > 0:
            confidence += 0.05
            factors += 1

        # Normalize confidence
        return min(1.0, confidence) if factors > 0 else 0.0

    async def _detect_service_abstractions_async(self, context: ProjectContext) -> Dict[str, Any]:
        """
        Detect service abstractions in the project.
        
        Args:
            context: Current project context
            
        Returns:
            Dictionary mapping class name to ServiceAbstraction data
        """
        from warden.analysis.application.service_abstraction_detector import ServiceAbstractionDetector
        
        try:
            detector = ServiceAbstractionDetector(
                self.project_root, 
                project_context=context,
                llm_config=self.llm_config,
                analysis_level=self.analysis_level,
                llm_service=self.llm_service
            )
            abstractions = await detector.detect_async(all_files=self._injected_files)
            
            # Convert to serializable dict
            result = {}
            for name, abstraction in abstractions.items():
                result[name] = abstraction.to_dict()
            
            if result:
                logger.info(
                    "service_abstractions_detected",
                    count=len(result),
                    services=list(result.keys()),
                )
            
            return result
            
        except Exception as e:
            logger.warning(
                "service_abstraction_detection_failed",
                error=str(e),
            )
            return {}