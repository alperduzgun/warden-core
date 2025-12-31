"""
Framework Detection Module.

Detects the main framework used in the project during PRE-ANALYSIS phase.
"""

import json
from pathlib import Path
from typing import Dict, List, Set
import structlog

from warden.analysis.domain.project_context import Framework

logger = structlog.get_logger()


class FrameworkDetector:
    """
    Detects the main framework used in the project.

    Part of the PRE-ANALYSIS phase for context detection.
    """

    def __init__(self, project_root: Path, config_files: Dict[str, str]):
        """
        Initialize framework detector.

        Args:
            project_root: Root directory of the project
            config_files: Detected configuration files
        """
        self.project_root = project_root
        self.config_files = config_files

    def detect(self) -> Framework:
        """
        Detect the main framework used.

        Returns:
            Detected framework enum value
        """
        logger.debug("framework_detection_started")

        # Python frameworks
        if self._detect_django():
            return Framework.DJANGO

        if self._detect_fastapi():
            return Framework.FASTAPI

        if self._detect_flask():
            return Framework.FLASK

        # JavaScript frameworks
        framework = self._detect_js_framework()
        if framework != Framework.NONE:
            return framework

        # Config file indicators
        if "angular.json" in self.config_files:
            return Framework.ANGULAR
        if "next.config.js" in self.config_files:
            return Framework.NEXTJS
        if "vue.config.js" in self.config_files:
            return Framework.VUE

        return Framework.NONE

    def _detect_django(self) -> bool:
        """Check if Django framework is used."""
        if "django" in str(self.config_files.values()):
            return True

        # Check for Django settings files
        try:
            settings_files = list(self.project_root.rglob("*settings.py"))
            for file in settings_files[:5]:  # Check first 5 matches
                with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(1000)  # Read first 1000 chars
                    if "django" in content.lower():
                        return True
        except Exception as e:
            logger.debug("django_detection_error", error=str(e))

        return False

    def _detect_fastapi(self) -> bool:
        """Check if FastAPI framework is used."""
        req_files = list(self.project_root.glob("*requirements*.txt"))
        for req_file in req_files[:3]:  # Check first 3 requirements files
            try:
                with open(req_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if "fastapi" in content.lower():
                        return True
            except Exception as e:
                logger.debug("fastapi_detection_error", error=str(e))

        return False

    def _detect_flask(self) -> bool:
        """Check if Flask framework is used."""
        req_files = list(self.project_root.glob("*requirements*.txt"))
        for req_file in req_files[:3]:  # Check first 3 requirements files
            try:
                with open(req_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if "flask" in content.lower():
                        return True
            except Exception as e:
                logger.debug("flask_detection_error", error=str(e))

        return False

    def _detect_js_framework(self) -> Framework:
        """Detect JavaScript/TypeScript frameworks from package.json."""
        if "package.json" not in self.config_files:
            return Framework.NONE

        package_json_path = self.project_root / "package.json"
        if not package_json_path.exists():
            return Framework.NONE

        try:
            with open(package_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}

                # Check frameworks in priority order
                framework_map = {
                    "react": Framework.REACT,
                    "vue": Framework.VUE,
                    "@angular/core": Framework.ANGULAR,
                    "svelte": Framework.SVELTE,
                    "next": Framework.NEXTJS,
                    "express": Framework.EXPRESS,
                }

                for dep_name, framework in framework_map.items():
                    if dep_name in deps:
                        return framework

        except Exception as e:
            logger.debug("js_framework_detection_error", error=str(e))

        return Framework.NONE