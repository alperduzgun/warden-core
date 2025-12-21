"""
Project domain models.

Panel Source: /warden-panel/src/lib/types/project.ts

TypeScript interfaces:
    - ProjectMeta
    - Project
    - FindingsSummary
    - LastRunInfo
    - ProjectSummary
    - RunHistory
    - ProjectDetail
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any, Type

from warden.shared.domain.base_model import BaseDomainModel
from warden.projects.domain.enums import ProjectStatus, QualityTrend


@dataclass
class ProjectMeta(BaseDomainModel):
    """
    Project metadata (branch and commit info).

    Panel: ProjectMeta interface
    """

    branch: str
    commit: str  # Short commit hash


@dataclass
class FindingsSummary(BaseDomainModel):
    """
    Summary of findings by severity level.

    Panel: FindingsSummary interface
    """

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0

    @property
    def total(self) -> int:
        """Total number of findings across all severities."""
        return self.critical + self.high + self.medium + self.low


@dataclass
class LastRunInfo(BaseDomainModel):
    """
    Information about the last pipeline run.

    Panel: LastRunInfo interface
    """

    status: str  # 'success' | 'running' | 'failed' | 'idle'
    timestamp: datetime  # ISO date string in JSON
    duration: str  # e.g., "1m 43s"


@dataclass
class Project(BaseDomainModel):
    """
    Base project entity.

    Panel: Project interface
    """

    id: str
    name: str
    display_name: str
    meta: ProjectMeta
    provider: Optional[str] = None  # 'github' | 'gitlab' | 'bitbucket' | None

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Override to handle nested ProjectMeta.
        """
        result = super().to_json()
        result["meta"] = self.meta.to_json()
        return result

    @classmethod
    def from_json(cls: Type[Project], data: Dict[str, Any]) -> Project:
        """Deserialize from Panel JSON (camelCase)."""
        return cls(
            id=data["id"],
            name=data["name"],
            display_name=data["displayName"],
            meta=ProjectMeta.from_json(data["meta"]),
            provider=data.get("provider"),
        )


@dataclass
class ProjectSummary(Project):
    """
    Project summary with quality metrics and last run info.

    Panel: ProjectSummary interface (extends Project)
    """

    quality_score: float = 0.0  # 0-10
    trend: str = "stable"  # 'improving' | 'stable' | 'degrading'
    last_run: Optional[LastRunInfo] = None
    findings: Optional[FindingsSummary] = None
    repository_path: Optional[str] = None
    repository_url: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Override to handle nested objects.
        """
        result = super().to_json()
        if self.last_run:
            result["lastRun"] = self.last_run.to_json()
        if self.findings:
            result["findings"] = self.findings.to_json()
        return result

    @classmethod
    def from_json(cls: Type[ProjectSummary], data: Dict[str, Any]) -> ProjectSummary:
        """Deserialize from Panel JSON (camelCase)."""
        return cls(
            id=data["id"],
            name=data["name"],
            display_name=data["displayName"],
            meta=ProjectMeta.from_json(data["meta"]),
            provider=data.get("provider"),
            quality_score=data.get("qualityScore", 0.0),
            trend=data.get("trend", "stable"),
            last_run=LastRunInfo.from_json(data["lastRun"]) if "lastRun" in data else None,
            findings=FindingsSummary.from_json(data["findings"]) if "findings" in data else None,
            repository_path=data.get("repositoryPath"),
            repository_url=data.get("repositoryUrl"),
        )


@dataclass
class RunHistory(BaseDomainModel):
    """
    Historical record of a pipeline run.

    Panel: RunHistory interface
    """

    id: str
    project_id: str
    status: str  # 'success' | 'running' | 'failed' | 'idle'
    timestamp: datetime
    duration: str  # e.g., "1m 43s"
    quality_score: float  # 0-10
    findings: FindingsSummary
    commit: str  # Commit hash
    branch: str

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Override to handle nested FindingsSummary.
        """
        result = super().to_json()
        result["findings"] = self.findings.to_json()
        return result

    @classmethod
    def from_json(cls: Type[RunHistory], data: Dict[str, Any]) -> RunHistory:
        """Deserialize from Panel JSON (camelCase)."""
        return cls(
            id=data["id"],
            project_id=data["projectId"],
            status=data["status"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            duration=data["duration"],
            quality_score=data["qualityScore"],
            findings=FindingsSummary.from_json(data["findings"]),
            commit=data["commit"],
            branch=data["branch"],
        )


@dataclass
class ProjectDetail(ProjectSummary):
    """
    Detailed project view with history.

    Panel: ProjectDetail interface (extends ProjectSummary)
    """

    description: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    total_runs: int = 0
    recent_runs: List[RunHistory] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Override to handle list of RunHistory.
        """
        result = super().to_json()
        result["recentRuns"] = [run.to_json() for run in self.recent_runs]
        return result

    @classmethod
    def from_json(cls: Type[ProjectDetail], data: Dict[str, Any]) -> ProjectDetail:
        """Deserialize from Panel JSON (camelCase)."""
        return cls(
            id=data["id"],
            name=data["name"],
            display_name=data["displayName"],
            meta=ProjectMeta.from_json(data["meta"]),
            provider=data.get("provider"),
            quality_score=data.get("qualityScore", 0.0),
            trend=data.get("trend", "stable"),
            last_run=LastRunInfo.from_json(data["lastRun"]) if "lastRun" in data else None,
            findings=FindingsSummary.from_json(data["findings"]) if "findings" in data else None,
            repository_path=data.get("repositoryPath"),
            repository_url=data.get("repositoryUrl"),
            description=data.get("description"),
            created_at=datetime.fromisoformat(data["createdAt"]),
            total_runs=data.get("totalRuns", 0),
            recent_runs=[RunHistory.from_json(run) for run in data.get("recentRuns", [])],
        )
