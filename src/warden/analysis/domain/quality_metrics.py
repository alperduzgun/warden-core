"""
Quality Metrics Model for Analysis Phase.

Provides comprehensive code quality scoring on a 0-10 scale.
Panel UI compatible with before/after comparison support.
"""

from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pydantic import Field

from warden.shared.domain.base_model import BaseDomainModel


class MetricBreakdown(BaseDomainModel):
    """
    Individual metric score with details.

    Each metric contributes to the overall quality score.
    """

    name: str  # e.g., "complexity", "duplication"
    score: float  # 0.0 to 10.0
    weight: float  # Weight in overall score calculation (0.0 to 1.0)
    details: Dict[str, Any] = Field(default_factory=dict)

    @property
    def weighted_score(self) -> float:
        """Calculate weighted contribution to overall score."""
        return self.score * self.weight

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            "name": self.name,
            "score": round(self.score, 2),
            "weight": self.weight,
            "weightedScore": round(self.weighted_score, 2),
            "details": self.details,
        }


class CodeHotspot(BaseDomainModel):
    """
    Problematic area in code that needs attention.

    Highlights specific locations with issues.
    """

    file_path: str
    line_number: int
    issue_type: str  # e.g., "high_complexity", "duplication"
    severity: Union[str, int]  # "critical", "high", "medium", "low" or 0-3
    message: str
    impact_score: float  # How much it affects overall quality (0.0 to 10.0)

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            "filePath": self.file_path,
            "lineNumber": self.line_number,
            "issueType": self.issue_type,
            "severity": self.severity,
            "message": self.message,
            "impactScore": round(self.impact_score, 2),
        }


class QuickWin(BaseDomainModel):
    """
    Easy improvement that can boost quality score.

    Low-effort, high-impact improvements.
    """

    type: str  # e.g., "remove_duplication", "extract_method"
    description: str
    estimated_effort: str  # e.g., "5min", "30min", "2h"
    score_improvement: float  # Expected score increase
    file_path: Optional[str] = None
    line_number: Optional[int] = None

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = {
            "type": self.type,
            "description": self.description,
            "estimatedEffort": self.estimated_effort,
            "scoreImprovement": f"+{self.score_improvement:.1f}",
        }

        if self.file_path:
            data["filePath"] = self.file_path
        if self.line_number:
            data["lineNumber"] = self.line_number

        return data


class QualityMetrics(BaseDomainModel):
    """
    Comprehensive code quality metrics for Analysis phase.

    Provides overall quality score and detailed breakdowns.
    Panel UI compatible with before/after comparison support.
    """

    # Overall score (0-10 scale)
    overall_score: float = 0.0

    # Individual metric scores (0-10 scale)
    complexity_score: float = 0.0
    duplication_score: float = 0.0
    maintainability_score: float = 0.0
    naming_score: float = 0.0
    documentation_score: float = 0.0
    testability_score: float = 0.0

    # Detailed metrics
    cyclomatic_complexity: int = 0
    cognitive_complexity: int = 0
    lines_of_code: int = 0
    duplicate_blocks: int = 0
    duplicate_lines: int = 0
    test_coverage: float = 0.0  # Percentage (0-100)
    documentation_coverage: float = 0.0  # Percentage (0-100)

    # Technical debt estimation
    technical_debt_hours: float = 0.0  # Estimated hours to fix all issues

    # Problem areas
    hotspots: List[CodeHotspot] = Field(default_factory=list)

    # Quick improvements
    quick_wins: List[QuickWin] = Field(default_factory=list)

    # Metric breakdowns with weights
    metric_breakdowns: List[MetricBreakdown] = Field(default_factory=list)

    # Trend information (if historical data available)
    trend: Optional[str] = None  # "improving", "degrading", "stable"
    previous_score: Optional[float] = None

    # Analysis metadata
    analyzed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    analysis_duration: float = 0.0  # Seconds
    file_count: int = 0

    def model_post_init(self, __context: Any) -> None:
        """Initialize metric breakdowns if not provided."""
        if not self.metric_breakdowns:
            self.metric_breakdowns = self._create_default_breakdowns()

        # Recalculate overall score if needed
        if self.overall_score == 0.0 and self.metric_breakdowns:
            self.overall_score = self.calculate_overall_score()

    def _create_default_breakdowns(self) -> List[MetricBreakdown]:
        """Create default metric breakdowns with standard weights."""
        return [
            MetricBreakdown(
                name="complexity",
                score=self.complexity_score,
                weight=0.25,
                details={
                    "cyclomatic": self.cyclomatic_complexity,
                    "cognitive": self.cognitive_complexity,
                }
            ),
            MetricBreakdown(
                name="duplication",
                score=self.duplication_score,
                weight=0.20,
                details={
                    "duplicate_blocks": self.duplicate_blocks,
                    "duplicate_lines": self.duplicate_lines,
                }
            ),
            MetricBreakdown(
                name="maintainability",
                score=self.maintainability_score,
                weight=0.20,
                details={
                    "lines_of_code": self.lines_of_code,
                }
            ),
            MetricBreakdown(
                name="naming",
                score=self.naming_score,
                weight=0.15,
                details={}
            ),
            MetricBreakdown(
                name="documentation",
                score=self.documentation_score,
                weight=0.10,
                details={
                    "coverage": f"{self.documentation_coverage:.1f}%",
                }
            ),
            MetricBreakdown(
                name="testability",
                score=self.testability_score,
                weight=0.10,
                details={
                    "test_coverage": f"{self.test_coverage:.1f}%",
                }
            ),
        ]

    def calculate_overall_score(self) -> float:
        """
        Calculate weighted overall score from individual metrics.

        Returns:
            Overall quality score (0.0 to 10.0)
        """
        if not self.metric_breakdowns:
            return 0.0

        total_weight = sum(mb.weight for mb in self.metric_breakdowns)
        if total_weight == 0:
            return 0.0

        weighted_sum = sum(mb.weighted_score for mb in self.metric_breakdowns)
        score = weighted_sum / total_weight

        # Ensure score is within bounds
        return max(0.0, min(10.0, score))

    @property
    def technical_debt_formatted(self) -> str:
        """Format technical debt as human-readable string."""
        hours = self.technical_debt_hours

        if hours < 1:
            minutes = int(hours * 60)
            return f"{minutes}m"
        elif hours < 24:
            whole_hours = int(hours)
            minutes = int((hours - whole_hours) * 60)
            if minutes > 0:
                return f"{whole_hours}h {minutes}m"
            return f"{whole_hours}h"
        else:
            days = int(hours / 8)  # Assuming 8-hour workday
            remaining_hours = int(hours % 8)
            if remaining_hours > 0:
                return f"{days}d {remaining_hours}h"
            return f"{days}d"

    @property
    def quality_grade(self) -> str:
        """
        Get letter grade based on overall score.

        Returns:
            Grade (A, B, C, D, F)
        """
        if self.overall_score >= 9.0:
            return "A"
        elif self.overall_score >= 8.0:
            return "B"
        elif self.overall_score >= 7.0:
            return "C"
        elif self.overall_score >= 6.0:
            return "D"
        else:
            return "F"

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        data = {
            "overallScore": round(self.overall_score, 1),
            "qualityGrade": self.quality_grade,

            # Individual scores
            "scores": {
                "complexity": round(self.complexity_score, 1),
                "duplication": round(self.duplication_score, 1),
                "maintainability": round(self.maintainability_score, 1),
                "naming": round(self.naming_score, 1),
                "documentation": round(self.documentation_score, 1),
                "testability": round(self.testability_score, 1),
            },

            # Detailed metrics
            "metrics": {
                "cyclomaticComplexity": self.cyclomatic_complexity,
                "cognitiveComplexity": self.cognitive_complexity,
                "linesOfCode": self.lines_of_code,
                "duplicateBlocks": self.duplicate_blocks,
                "duplicateLines": self.duplicate_lines,
                "testCoverage": round(self.test_coverage, 1),
                "documentationCoverage": round(self.documentation_coverage, 1),
            },

            # Technical debt
            "technicalDebt": self.technical_debt_formatted,
            "technicalDebtHours": round(self.technical_debt_hours, 2),

            # Problem areas
            "hotspots": [h.to_json() for h in self.hotspots],
            "hotspotsCount": len(self.hotspots),

            # Quick wins
            "quickWins": [qw.to_json() for qw in self.quick_wins],
            "quickWinsCount": len(self.quick_wins),

            # Metric breakdowns
            "metricBreakdowns": [mb.to_json() for mb in self.metric_breakdowns],

            # Metadata
            "analyzedAt": self.analyzed_at,
            "analysisDuration": round(self.analysis_duration, 2),
            "fileCount": self.file_count,
        }

        # Add trend information if available
        if self.trend:
            data["trend"] = self.trend
        if self.previous_score is not None:
            data["previousScore"] = round(self.previous_score, 1)
            data["scoreChange"] = round(self.overall_score - self.previous_score, 1)

        return data

    def to_panel_summary(self) -> Dict[str, Any]:
        """
        Convert to Panel UI Summary tab format.

        Used specifically for the Summary tab in Panel UI.
        """
        return {
            "score": f"{self.overall_score:.1f}/10.0",
            "grade": self.quality_grade,
            "breakdown": {
                "complexity": {"score": self.complexity_score, "trend": "→"},
                "duplication": {"score": self.duplication_score, "trend": "→"},
                "maintainability": {"score": self.maintainability_score, "trend": "→"},
                "naming": {"score": self.naming_score, "trend": "→"},
                "documentation": {"score": self.documentation_score, "trend": "→"},
                "testability": {"score": self.testability_score, "trend": "→"},
            },
            "technicalDebt": self.technical_debt_formatted,
            "hotspots": len(self.hotspots),
            "quickWins": len(self.quick_wins),
        }

    @classmethod
    def calculate_from_analyzers(
        cls,
        complexity_result: Optional[Any] = None,
        duplication_result: Optional[Any] = None,
        naming_result: Optional[Any] = None,
        maintainability_result: Optional[Any] = None,
        documentation_result: Optional[Any] = None,
        testability_result: Optional[Any] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> "QualityMetrics":
        """
        Calculate quality metrics from analyzer results.

        Args:
            *_result: Results from individual analyzers
            weights: Optional custom weights for metrics

        Returns:
            QualityMetrics instance with calculated scores
        """
        # Default weights if not provided
        if weights is None:
            weights = {
                "complexity": 0.25,
                "duplication": 0.20,
                "maintainability": 0.20,
                "naming": 0.15,
                "documentation": 0.10,
                "testability": 0.10,
            }

        # Initialize metrics
        metrics = cls()

        # Process each analyzer result
        if complexity_result:
            metrics.complexity_score = complexity_result.get("score", 5.0)
            metrics.cyclomatic_complexity = complexity_result.get("cyclomatic", 0)
            metrics.cognitive_complexity = complexity_result.get("cognitive", 0)

        if duplication_result:
            metrics.duplication_score = duplication_result.get("score", 5.0)
            metrics.duplicate_blocks = duplication_result.get("blocks", 0)
            metrics.duplicate_lines = duplication_result.get("lines", 0)

        if naming_result:
            metrics.naming_score = naming_result.get("score", 5.0)

        if maintainability_result:
            metrics.maintainability_score = maintainability_result.get("score", 5.0)
            metrics.lines_of_code = maintainability_result.get("loc", 0)

        if documentation_result:
            metrics.documentation_score = documentation_result.get("score", 5.0)
            metrics.documentation_coverage = documentation_result.get("coverage", 0.0)

        if testability_result:
            metrics.testability_score = testability_result.get("score", 5.0)
            metrics.test_coverage = testability_result.get("coverage", 0.0)

        # Create metric breakdowns with custom weights
        metrics.metric_breakdowns = [
            MetricBreakdown("complexity", metrics.complexity_score, weights["complexity"]),
            MetricBreakdown("duplication", metrics.duplication_score, weights["duplication"]),
            MetricBreakdown("maintainability", metrics.maintainability_score, weights["maintainability"]),
            MetricBreakdown("naming", metrics.naming_score, weights["naming"]),
            MetricBreakdown("documentation", metrics.documentation_score, weights["documentation"]),
            MetricBreakdown("testability", metrics.testability_score, weights["testability"]),
        ]

        # Calculate overall score
        metrics.overall_score = metrics.calculate_overall_score()

        return metrics