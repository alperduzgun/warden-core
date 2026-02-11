"""
Intelligence Models for Static Project Analysis.

Provides domain models for storing pre-computed project intelligence
that enables context-aware analysis without repeated LLM calls.

These models are designed to be:
- Serializable to JSON for repo storage (.warden/intelligence/)
- Loadable in CI without LLM dependency
- Updatable incrementally via 'warden refresh'
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field

from warden.shared.domain.base_model import BaseDomainModel


class RiskLevel(Enum):
    """
    Risk classification for modules and files.

    Determines scan depth and LLM usage priority.
    """
    P0_CRITICAL = "P0"  # Always deep scan with LLM (auth, payment, crypto)
    P1_HIGH = "P1"      # Deep scan, LLM priority (user data, admin)
    P2_MEDIUM = "P2"    # Standard scan, LLM if budget allows
    P3_LOW = "P3"       # Fast scan, Rust-only (utils, helpers, tests)


class SecurityPosture(Enum):
    """
    Overall security posture for the project.

    Determines default strictness levels.
    """
    PARANOID = "paranoid"    # Maximum security (fintech, healthcare)
    STRICT = "strict"        # High security (e-commerce, SaaS)
    STANDARD = "standard"    # Normal security (internal tools)
    RELAXED = "relaxed"      # Minimal security (prototypes, demos)


class ModuleInfo(BaseDomainModel):
    """
    Information about a detected module/component.

    Represents a logical grouping of files with shared
    security characteristics and purpose.
    """

    name: str = ""
    path: str = ""  # Relative path from project root (e.g., "src/auth/")
    description: str = ""  # LLM-generated description
    risk_level: RiskLevel = RiskLevel.P2_MEDIUM

    # Security focus areas for this module
    security_focus: list[str] = Field(default_factory=list)
    # e.g., ["injection", "auth_bypass", "data_leak"]

    # Dependencies on other modules
    depends_on: list[str] = Field(default_factory=list)
    # e.g., ["auth", "database"]

    # Modules that depend on this one
    depended_by: list[str] = Field(default_factory=list)

    # File count in this module
    file_count: int = 0

    # Verification status
    verified: bool = False  # True if AST cross-validated LLM claims

    def to_json(self) -> dict[str, Any]:
        """Convert to JSON with camelCase keys."""
        return {
            "name": self.name,
            "path": self.path,
            "description": self.description,
            "riskLevel": self.risk_level.value,
            "securityFocus": self.security_focus,
            "dependsOn": self.depends_on,
            "dependedBy": self.depended_by,
            "fileCount": self.file_count,
            "verified": self.verified,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ModuleInfo":
        """Create from JSON dict with camelCase keys."""
        return cls(
            name=data.get("name", ""),
            path=data.get("path", ""),
            description=data.get("description", ""),
            risk_level=RiskLevel(data.get("riskLevel", "P2")),
            security_focus=data.get("securityFocus", []),
            depends_on=data.get("dependsOn", []),
            depended_by=data.get("dependedBy", []),
            file_count=data.get("fileCount", 0),
            verified=data.get("verified", False),
        )


class FileException(BaseDomainModel):
    """
    Override for files that don't follow module-level classification.

    Used for critical files in low-risk modules (e.g., utils/crypto.py).
    """

    path: str = ""  # Relative path
    risk_level: RiskLevel = RiskLevel.P0_CRITICAL
    reason: str = ""  # Why this file is an exception
    security_focus: list[str] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        """Convert to JSON with camelCase keys."""
        return {
            "path": self.path,
            "riskLevel": self.risk_level.value,
            "reason": self.reason,
            "securityFocus": self.security_focus,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "FileException":
        """Create from JSON dict."""
        return cls(
            path=data.get("path", ""),
            risk_level=RiskLevel(data.get("riskLevel", "P0")),
            reason=data.get("reason", ""),
            security_focus=data.get("securityFocus", []),
        )


class ProjectIntelligence(BaseDomainModel):
    """
    Complete pre-computed intelligence for a project.

    Stored in .warden/intelligence/ and loaded by CI scans.
    """

    # Schema version for migration support
    schema_version: str = "1.0.0"

    # Generation metadata
    generated_at: str = ""  # ISO 8601 timestamp
    generated_by: str = "warden"  # Tool version

    # Project identity
    project_name: str = ""
    purpose: str = ""  # LLM-generated project purpose
    architecture: str = ""  # LLM-generated architecture description
    security_posture: SecurityPosture = SecurityPosture.STANDARD

    # Module map: module_name -> ModuleInfo
    modules: dict[str, ModuleInfo] = Field(default_factory=dict)

    # File exceptions: file_path -> FileException
    exceptions: dict[str, FileException] = Field(default_factory=dict)

    # Cross-module security rules
    cross_module_rules: list[dict[str, Any]] = Field(default_factory=list)
    # e.g., [{"if_module": "payments", "must_import": ["auth", "validation"]}]

    # Validation metrics
    llm_claims_count: int = 0
    verified_claims_count: int = 0

    @property
    def verification_ratio(self) -> float:
        """Ratio of verified to total LLM claims."""
        if self.llm_claims_count == 0:
            return 1.0
        return self.verified_claims_count / self.llm_claims_count

    @property
    def quality_score(self) -> int:
        """
        Intelligence quality score (0-100).

        Factors:
        - Age (fresher is better)
        - Verification ratio
        - Module coverage
        """
        score = 100

        # Age penalty (max 30 points)
        if self.generated_at:
            try:
                gen_time = datetime.fromisoformat(self.generated_at.replace("Z", "+00:00"))
                age_days = (datetime.now(gen_time.tzinfo) - gen_time).days
                score -= min(age_days * 2, 30)
            except (ValueError, TypeError):
                score -= 15  # Unknown age

        # Verification ratio (max 25 points)
        score -= int((1 - self.verification_ratio) * 25)

        # Module coverage (max 20 points if no modules)
        if len(self.modules) == 0:
            score -= 20

        return max(0, min(100, score))

    def get_module_for_file(self, file_path: str) -> ModuleInfo | None:
        """
        Get the module that contains a file.

        Args:
            file_path: Relative path from project root

        Returns:
            ModuleInfo if found, None otherwise
        """
        # Normalize path
        normalized = file_path.replace("\\", "/").lstrip("./")

        # Check each module's path
        for module in self.modules.values():
            if normalized.startswith(module.path.rstrip("/")):
                return module

        return None

    def get_risk_for_file(self, file_path: str) -> RiskLevel:
        """
        Get risk level for a file, considering exceptions.

        Args:
            file_path: Relative path from project root

        Returns:
            RiskLevel for the file
        """
        normalized = file_path.replace("\\", "/").lstrip("./")

        # Check exceptions first
        if normalized in self.exceptions:
            return self.exceptions[normalized].risk_level

        # Check module
        module = self.get_module_for_file(normalized)
        if module:
            return module.risk_level

        # Default: P1_HIGH for unknown (paranoid approach)
        return RiskLevel.P1_HIGH

    def to_json(self) -> dict[str, Any]:
        """Convert to JSON for storage."""
        return {
            "schemaVersion": self.schema_version,
            "generatedAt": self.generated_at,
            "generatedBy": self.generated_by,
            "projectName": self.project_name,
            "purpose": self.purpose,
            "architecture": self.architecture,
            "securityPosture": self.security_posture.value,
            "modules": {k: v.to_json() for k, v in self.modules.items()},
            "exceptions": {k: v.to_json() for k, v in self.exceptions.items()},
            "crossModuleRules": self.cross_module_rules,
            "llmClaimsCount": self.llm_claims_count,
            "verifiedClaimsCount": self.verified_claims_count,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ProjectIntelligence":
        """Create from JSON dict."""
        modules = {}
        for name, mod_data in data.get("modules", {}).items():
            modules[name] = ModuleInfo.from_json(mod_data)

        exceptions = {}
        for path, exc_data in data.get("exceptions", {}).items():
            exceptions[path] = FileException.from_json(exc_data)

        return cls(
            schema_version=data.get("schemaVersion", "1.0.0"),
            generated_at=data.get("generatedAt", ""),
            generated_by=data.get("generatedBy", "warden"),
            project_name=data.get("projectName", ""),
            purpose=data.get("purpose", ""),
            architecture=data.get("architecture", ""),
            security_posture=SecurityPosture(data.get("securityPosture", "standard")),
            modules=modules,
            exceptions=exceptions,
            cross_module_rules=data.get("crossModuleRules", []),
            llm_claims_count=data.get("llmClaimsCount", 0),
            verified_claims_count=data.get("verifiedClaimsCount", 0),
        )
