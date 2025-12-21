"""
Reports domain models.

Panel Source: /warden-panel/src/lib/types/warden.ts

TypeScript interfaces:
    export interface GuardianReport {
        filePath: string;
        scoreBefore: number;
        scoreAfter: number;
        linesBefore: number;
        linesAfter: number;
        filesModified: string[];
        filesCreated: string[];
        timestamp: Date;
        issuesBySeverity: Record<string, number>;
        issuesByCategory: Record<string, number>;
        projectId?: string;
        tenantId?: string;
        generatedBy?: string;
        improvementPercentage: number;
    }

    export interface DashboardMetrics {
        totalIssues: number;
        criticalIssues: number;
        highIssues: number;
        mediumIssues: number;
        lowIssues: number;
        overallScore: number;  // 0-100
        trend: 'improving' | 'degrading' | 'stable';
        lastScanTime: Date;
        filesScanned: number;
        linesScanned: number;
    }
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional

from warden.shared.domain.base_model import BaseDomainModel


@dataclass
class GuardianReport(BaseDomainModel):
    """
    Guardian analysis report with before/after metrics.

    Panel: GuardianReport interface

    The improvementPercentage is a computed property that shows the
    percentage improvement from score_before to score_after.
    """

    file_path: str
    score_before: float  # 0-100
    score_after: float  # 0-100
    lines_before: int
    lines_after: int
    files_modified: List[str]
    files_created: List[str]
    timestamp: datetime
    issues_by_severity: Dict[str, int]  # {"critical": 2, "high": 3}
    issues_by_category: Dict[str, int]  # {"security": 5, "performance": 2}
    project_id: Optional[str] = None
    tenant_id: Optional[str] = None
    generated_by: Optional[str] = None

    @property
    def improvement_percentage(self) -> float:
        """
        Calculate improvement percentage.

        Formula: ((after - before) / before) * 100

        Returns:
            Percentage improvement (positive) or degradation (negative).
            Returns 0.0 if score_before is 0 to avoid division by zero.

        Examples:
            score_before=50, score_after=75 -> +50.0% improvement
            score_before=80, score_after=60 -> -25.0% degradation
            score_before=0, score_after=50 -> 0.0 (undefined)
        """
        if self.score_before == 0:
            return 0.0
        return ((self.score_after - self.score_before) / self.score_before) * 100

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON.

        Override to include computed improvementPercentage field.
        """
        result = super().to_json()

        # Add computed field to JSON output
        result["improvementPercentage"] = self.improvement_percentage

        return result

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "GuardianReport":
        """
        Deserialize from Panel JSON (camelCase).

        Note: improvementPercentage is ignored as it's a computed property.
        """
        return cls(
            file_path=data["filePath"],
            score_before=data["scoreBefore"],
            score_after=data["scoreAfter"],
            lines_before=data["linesBefore"],
            lines_after=data["linesAfter"],
            files_modified=data["filesModified"],
            files_created=data["filesCreated"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            issues_by_severity=data["issuesBySeverity"],
            issues_by_category=data["issuesByCategory"],
            project_id=data.get("projectId"),
            tenant_id=data.get("tenantId"),
            generated_by=data.get("generatedBy"),
        )


@dataclass
class DashboardMetrics(BaseDomainModel):
    """
    Dashboard metrics for overview cards.

    Aggregates project-wide quality metrics.
    Panel uses this for the dashboard overview page.
    """

    total_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int
    overall_score: float  # 0-100
    trend: str  # 'improving' | 'degrading' | 'stable'
    last_scan_time: datetime
    files_scanned: int
    lines_scanned: int

    def to_json(self) -> Dict[str, Any]:
        """
        Convert to Panel-compatible JSON (camelCase).

        Returns:
            Dict[str, Any]: Panel-compatible dictionary

        Examples:
            >>> metrics = DashboardMetrics(
            ...     total_issues=42,
            ...     critical_issues=3,
            ...     high_issues=8,
            ...     medium_issues=15,
            ...     low_issues=16,
            ...     overall_score=72.5,
            ...     trend="improving",
            ...     last_scan_time=datetime(2025, 12, 21, 10, 30, 0),
            ...     files_scanned=123,
            ...     lines_scanned=5432
            ... )
            >>> json_data = metrics.to_json()
            >>> json_data['totalIssues']
            42
            >>> json_data['overallScore']
            72.5
        """
        return {
            "totalIssues": self.total_issues,
            "criticalIssues": self.critical_issues,
            "highIssues": self.high_issues,
            "mediumIssues": self.medium_issues,
            "lowIssues": self.low_issues,
            "overallScore": self.overall_score,
            "trend": self.trend,
            "lastScanTime": self.last_scan_time.isoformat(),
            "filesScanned": self.files_scanned,
            "linesScanned": self.lines_scanned
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "DashboardMetrics":
        """
        Parse Panel JSON (camelCase) to Python model.

        Args:
            data: Panel-compatible dictionary with camelCase keys

        Returns:
            DashboardMetrics: Parsed model instance

        Examples:
            >>> json_data = {
            ...     "totalIssues": 42,
            ...     "criticalIssues": 3,
            ...     "highIssues": 8,
            ...     "mediumIssues": 15,
            ...     "lowIssues": 16,
            ...     "overallScore": 72.5,
            ...     "trend": "improving",
            ...     "lastScanTime": "2025-12-21T10:30:00",
            ...     "filesScanned": 123,
            ...     "linesScanned": 5432
            ... }
            >>> metrics = DashboardMetrics.from_json(json_data)
            >>> metrics.total_issues
            42
        """
        return cls(
            total_issues=data["totalIssues"],
            critical_issues=data["criticalIssues"],
            high_issues=data["highIssues"],
            medium_issues=data["mediumIssues"],
            low_issues=data["lowIssues"],
            overall_score=data["overallScore"],
            trend=data["trend"],
            last_scan_time=datetime.fromisoformat(data["lastScanTime"]),
            files_scanned=data["filesScanned"],
            lines_scanned=data["linesScanned"]
        )
