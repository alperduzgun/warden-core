"""
Intelligence Loader Service.

Provides read-only access to pre-computed project intelligence.
Designed for CI environments where LLM is not available.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from warden.analysis.domain.intelligence import (
    FileException,
    ModuleInfo,
    ProjectIntelligence,
    RiskLevel,
    SecurityPosture,
)

logger = structlog.get_logger(__name__)


class IntelligenceLoader:
    """
    Loads and provides access to pre-computed project intelligence.

    This service reads intelligence data from `.warden/intelligence/`
    and provides a simple API for querying module risk levels,
    security posture, and file exceptions.

    Designed to work WITHOUT LLM dependency for CI performance.
    """

    INTELLIGENCE_DIR = ".warden/intelligence"
    INTELLIGENCE_FILE = "project.json"

    def __init__(self, project_root: Path):
        """
        Initialize the loader.

        Args:
            project_root: Root directory of the project.
        """
        self.project_root = Path(project_root).resolve()
        self.intelligence_path = self.project_root / self.INTELLIGENCE_DIR / self.INTELLIGENCE_FILE
        self._intelligence: ProjectIntelligence | None = None
        self._loaded = False

    @property
    def is_available(self) -> bool:
        """Check if intelligence file exists."""
        return self.intelligence_path.exists()

    @property
    def is_loaded(self) -> bool:
        """Check if intelligence has been loaded."""
        return self._loaded and self._intelligence is not None

    def load(self) -> bool:
        """
        Load intelligence from disk.

        Returns:
            True if loaded successfully, False otherwise.
        """
        if not self.is_available:
            logger.debug("intelligence_not_available", path=str(self.intelligence_path))
            return False

        try:
            with open(self.intelligence_path, encoding="utf-8") as f:
                data = json.load(f)

            self._intelligence = ProjectIntelligence.from_json(data)
            self._loaded = True

            logger.info(
                "intelligence_loaded",
                modules=len(self._intelligence.modules),
                exceptions=len(self._intelligence.exceptions),
                quality_score=self._intelligence.quality_score,
            )
            return True

        except json.JSONDecodeError as e:
            logger.error("intelligence_json_parse_error", error=str(e))
            return False
        except Exception as e:
            logger.error("intelligence_load_error", error=str(e))
            return False

    def get_risk_for_file(self, file_path: str) -> RiskLevel:
        """
        Get risk level for a specific file.

        Checks exceptions first, then module membership,
        falls back to P1_HIGH for unknown files.

        Args:
            file_path: Relative path from project root.

        Returns:
            RiskLevel for the file.
        """
        if not self.is_loaded or self._intelligence is None:
            # Conservative default when no intelligence
            return RiskLevel.P1_HIGH

        return self._intelligence.get_risk_for_file(file_path)

    def get_module_for_file(self, file_path: str) -> ModuleInfo | None:
        """
        Get the module that contains a file.

        Args:
            file_path: Relative path from project root.

        Returns:
            ModuleInfo if found, None otherwise.
        """
        if not self.is_loaded or self._intelligence is None:
            return None

        return self._intelligence.get_module_for_file(file_path)

    def get_security_posture(self) -> SecurityPosture:
        """
        Get the project's security posture.

        Returns:
            SecurityPosture, defaults to STANDARD if not loaded.
        """
        if not self.is_loaded or self._intelligence is None:
            return SecurityPosture.STANDARD

        return self._intelligence.security_posture

    def get_security_focus_for_file(self, file_path: str) -> list[str]:
        """
        Get security focus areas for a file.

        Args:
            file_path: Relative path from project root.

        Returns:
            List of security focus areas (e.g., ["injection", "auth_bypass"]).
        """
        if not self.is_loaded or self._intelligence is None:
            return []

        # Check exceptions first
        normalized = file_path.replace("\\", "/").lstrip("./")
        if normalized in self._intelligence.exceptions:
            return self._intelligence.exceptions[normalized].security_focus

        # Check module
        module = self._intelligence.get_module_for_file(file_path)
        if module:
            return module.security_focus

        return []

    def get_purpose(self) -> str:
        """
        Get the project purpose description.

        Returns:
            Purpose string or empty string if not loaded.
        """
        if not self.is_loaded or self._intelligence is None:
            return ""

        return self._intelligence.purpose

    def get_architecture(self) -> str:
        """
        Get the architecture description.

        Returns:
            Architecture string or empty string if not loaded.
        """
        if not self.is_loaded or self._intelligence is None:
            return ""

        return self._intelligence.architecture

    def get_quality_score(self) -> int:
        """
        Get the intelligence quality score.

        Returns:
            Score from 0-100, or 0 if not loaded.
        """
        if not self.is_loaded or self._intelligence is None:
            return 0

        return self._intelligence.quality_score

    def get_module_map(self) -> dict[str, ModuleInfo]:
        """
        Get the full module map.

        Returns:
            Dictionary mapping module names to ModuleInfo.
        """
        if not self.is_loaded or self._intelligence is None:
            return {}

        return self._intelligence.modules

    def get_file_exceptions(self) -> dict[str, FileException]:
        """
        Get all file exceptions.

        Returns:
            Dictionary mapping file paths to FileException.
        """
        if not self.is_loaded or self._intelligence is None:
            return {}

        return self._intelligence.exceptions

    def to_context_dict(self) -> dict[str, Any]:
        """
        Export intelligence as a dictionary for context injection.

        Useful for passing to analysis phases or LLM prompts.

        Returns:
            Dictionary with key intelligence fields.
        """
        if not self.is_loaded or self._intelligence is None:
            return {
                "available": False,
                "purpose": "",
                "architecture": "",
                "security_posture": "standard",
                "modules": {},
                "quality_score": 0,
            }

        return {
            "available": True,
            "purpose": self._intelligence.purpose,
            "architecture": self._intelligence.architecture,
            "security_posture": self._intelligence.security_posture.value,
            "modules": {name: info.to_json() for name, info in self._intelligence.modules.items()},
            "quality_score": self._intelligence.quality_score,
        }
