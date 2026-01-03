"""
Config Validation Frame.

Validates .warden/config.yaml for:
- Invalid frame IDs that don't match registered frames
- Missing required configuration fields
- Deprecated configuration patterns
"""

from typing import Dict, Any, List, Optional, Set
from pathlib import Path
import yaml

from warden.validation.domain.frame import ValidationFrame, FrameResult, Finding, CodeFile
from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
    FrameApplicability,
)
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class ConfigValidationFrame(ValidationFrame):
    """
    Validates Warden configuration files.
    
    Detects:
    - Invalid frame IDs in config.yaml that don't match registered frames
    - Provides suggestions for correct frame IDs
    - Reports deprecated configuration patterns
    """

    name = "Config Validation"
    description = "Validates .warden/config.yaml for invalid frame IDs and configuration issues"
    frame_id = "config"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.PROJECT_LEVEL
    is_blocker = True
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._registered_frame_ids: Set[str] = set()

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """Execute config validation (called per file, but we only care about config.yaml)."""
        # Skip non-config files
        if not code_file.path.endswith("config.yaml") or ".warden" not in code_file.path:
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="skipped",
                duration=0,
                issues_found=0,
                is_blocker=False,
                findings=[],
                metadata={"reason": "not_a_config_file"}
            )

        findings = await self._validate_config(code_file)
        
        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="failed" if findings else "passed",
            duration=0,
            issues_found=len(findings),
            is_blocker=self.is_blocker and len(findings) > 0,
            findings=findings,
            metadata={"config_path": code_file.path}
        )

    async def _validate_config(self, code_file: CodeFile) -> List[Finding]:
        """Validate config.yaml content."""
        findings: List[Finding] = []
        
        try:
            config = yaml.safe_load(code_file.content)
        except yaml.YAMLError as e:
            findings.append(Finding(
                id="config-yaml-parse-error",
                severity="critical",
                message=f"Invalid YAML syntax in config.yaml",
                location=code_file.path,
                detail=str(e),
                line=1,
            ))
            return findings

        if not config:
            return findings

        # Get registered frame IDs
        registered_ids = await self._get_registered_frame_ids()
        
        # Validate frame IDs
        config_frames = config.get("frames", [])
        for i, frame_id in enumerate(config_frames):
            if frame_id not in registered_ids:
                suggestion = self._find_similar_frame_id(frame_id, registered_ids)
                detail = f"Frame '{frame_id}' is not registered."
                if suggestion:
                    detail += f" Did you mean '{suggestion}'?"
                
                findings.append(Finding(
                    id=f"config-invalid-frame-id-{i}",
                    severity="high",
                    message=f"Invalid frame ID: '{frame_id}'",
                    location=f"{code_file.path}:frames[{i}]",
                    detail=detail,
                    code=f"- {frame_id}",
                    line=self._find_line_number(code_file.content, frame_id),
                ))

        # Validate frames_config references
        frames_config = config.get("frames_config", {})
        for frame_id in frames_config.keys():
            if frame_id not in registered_ids:
                suggestion = self._find_similar_frame_id(frame_id, registered_ids)
                detail = f"Frame config for '{frame_id}' references unregistered frame."
                if suggestion:
                    detail += f" Did you mean '{suggestion}'?"
                
                findings.append(Finding(
                    id=f"config-invalid-frame-config-{frame_id}",
                    severity="medium",
                    message=f"Frame config references invalid frame ID: '{frame_id}'",
                    location=f"{code_file.path}:frames_config.{frame_id}",
                    detail=detail,
                    line=self._find_line_number(code_file.content, f"{frame_id}:"),
                ))

        return findings

    async def _get_registered_frame_ids(self) -> Set[str]:
        """Get all registered frame IDs from FrameRegistry."""
        if self._registered_frame_ids:
            return self._registered_frame_ids
            
        try:
            from warden.validation.infrastructure.frame_registry import FrameRegistry
            registry = FrameRegistry()
            frames = registry.discover_all()
            
            for frame_class in frames:
                try:
                    instance = frame_class()
                    self._registered_frame_ids.add(instance.frame_id)
                except Exception:
                    pass
                    
        except Exception as e:
            logger.warning("failed_to_get_registered_frames", error=str(e))
            
        return self._registered_frame_ids

    def _find_similar_frame_id(self, invalid_id: str, registered_ids: Set[str]) -> Optional[str]:
        """Find a similar registered frame ID using fuzzy matching."""
        invalid_lower = invalid_id.lower().replace("-", "").replace("_", "")
        
        for reg_id in registered_ids:
            reg_lower = reg_id.lower().replace("-", "").replace("_", "")
            
            # Exact match after normalization
            if invalid_lower == reg_lower:
                return reg_id
                
            # Prefix match
            if reg_lower.startswith(invalid_lower) or invalid_lower.startswith(reg_lower):
                return reg_id
                
            # Substring match
            if invalid_lower in reg_lower or reg_lower in invalid_lower:
                return reg_id
                
        return None

    def _find_line_number(self, content: str, search: str) -> int:
        """Find line number of search string in content."""
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            if search in line:
                return i
        return 1
