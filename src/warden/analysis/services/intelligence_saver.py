"""
Intelligence Saver Service.

Saves project intelligence to disk for CI consumption.
Used during `warden init` and `warden refresh` commands.
"""

import json
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime, timezone
import structlog

from warden.analysis.domain.intelligence import (
    ProjectIntelligence,
    ModuleInfo,
    FileException,
    SecurityPosture,
)

logger = structlog.get_logger(__name__)


class IntelligenceSaver:
    """
    Saves project intelligence to the `.warden/intelligence/` directory.

    Creates versioned JSON files that can be loaded by IntelligenceLoader
    in CI environments without LLM dependency.
    """

    INTELLIGENCE_DIR = ".warden/intelligence"
    INTELLIGENCE_FILE = "project.json"

    def __init__(self, project_root: Path):
        """
        Initialize the saver.

        Args:
            project_root: Root directory of the project.
        """
        self.project_root = Path(project_root).resolve()
        self.intelligence_dir = self.project_root / self.INTELLIGENCE_DIR
        self.intelligence_path = self.intelligence_dir / self.INTELLIGENCE_FILE

    def ensure_directory(self) -> bool:
        """
        Ensure the intelligence directory exists.

        Returns:
            True if directory exists or was created, False on error.
        """
        try:
            self.intelligence_dir.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            logger.error("intelligence_dir_creation_failed", error=str(e))
            return False

    def save(
        self,
        purpose: str,
        architecture: str,
        security_posture: SecurityPosture,
        module_map: Dict[str, ModuleInfo],
        file_exceptions: Optional[Dict[str, FileException]] = None,
        project_name: Optional[str] = None,
    ) -> bool:
        """
        Save project intelligence to disk.

        Args:
            purpose: Project purpose description.
            architecture: Architecture description.
            security_posture: Security posture classification.
            module_map: Dictionary mapping module names to ModuleInfo.
            file_exceptions: Optional dictionary of file exceptions.
            project_name: Optional project name (defaults to directory name).

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self.ensure_directory():
            return False

        try:
            # Build ProjectIntelligence object
            intelligence = ProjectIntelligence(
                schema_version="1.0.0",
                generated_at=datetime.now(timezone.utc).isoformat(),
                generated_by="warden",
                project_name=project_name or self.project_root.name,
                purpose=purpose,
                architecture=architecture,
                security_posture=security_posture,
                modules=module_map,
                exceptions=file_exceptions or {},
                llm_claims_count=len(module_map),
                verified_claims_count=0,  # Will be updated by verification step
            )

            # Serialize and save
            data = intelligence.to_json()
            content = json.dumps(data, indent=2, ensure_ascii=False)

            with open(self.intelligence_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(
                "intelligence_saved",
                path=str(self.intelligence_path),
                modules=len(module_map),
                exceptions=len(file_exceptions or {})
            )
            return True

        except Exception as e:
            logger.error("intelligence_save_failed", error=str(e))
            return False

    def save_intelligence(self, intelligence: ProjectIntelligence) -> bool:
        """
        Save a complete ProjectIntelligence object to disk.

        Args:
            intelligence: Complete ProjectIntelligence object.

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self.ensure_directory():
            return False

        try:
            # Update generation timestamp
            intelligence.generated_at = datetime.now(timezone.utc).isoformat()

            data = intelligence.to_json()
            content = json.dumps(data, indent=2, ensure_ascii=False)

            with open(self.intelligence_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(
                "intelligence_saved",
                path=str(self.intelligence_path),
                modules=len(intelligence.modules),
                quality_score=intelligence.quality_score
            )
            return True

        except Exception as e:
            logger.error("intelligence_save_failed", error=str(e))
            return False

    def update_verification_counts(
        self,
        verified_count: int,
        total_claims: Optional[int] = None
    ) -> bool:
        """
        Update verification counts in existing intelligence file.

        Called after AST verification pass.

        Args:
            verified_count: Number of claims verified by AST.
            total_claims: Optional total claims count (uses existing if None).

        Returns:
            True if updated successfully, False otherwise.
        """
        if not self.intelligence_path.exists():
            logger.warning("intelligence_file_not_found_for_update")
            return False

        try:
            with open(self.intelligence_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            data["verifiedClaimsCount"] = verified_count
            if total_claims is not None:
                data["llmClaimsCount"] = total_claims

            # Update timestamp
            data["generatedAt"] = datetime.now(timezone.utc).isoformat()

            content = json.dumps(data, indent=2, ensure_ascii=False)

            with open(self.intelligence_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.debug(
                "verification_counts_updated",
                verified=verified_count,
                total=total_claims or data.get("llmClaimsCount", 0)
            )
            return True

        except Exception as e:
            logger.error("verification_update_failed", error=str(e))
            return False

    def exists(self) -> bool:
        """Check if intelligence file exists."""
        return self.intelligence_path.exists()

    def get_last_modified(self) -> Optional[datetime]:
        """
        Get last modification time of intelligence file.

        Returns:
            datetime of last modification, or None if file doesn't exist.
        """
        if not self.intelligence_path.exists():
            return None

        try:
            stat = self.intelligence_path.stat()
            return datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        except Exception:
            return None
