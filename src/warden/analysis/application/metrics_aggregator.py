"""
Metrics Aggregator

Responsible for aggregating results from multiple analyzers into a unified QualityMetrics object.
"""

from typing import Dict, Any, List, Optional
import structlog

from warden.analysis.domain.quality_metrics import (
    QualityMetrics,
    CodeHotspot,
    QuickWin,
    MetricBreakdown,
)
from warden.cleaning.domain.models import (
    CleaningResult,
    CleaningIssue,
    CleaningIssueType,
    CleaningIssueSeverity,
)

logger = structlog.get_logger()


class MetricsAggregator:
    """
    Aggregates analysis results into QualityMetrics.
    """

    def __init__(self, weights: Dict[str, float]) -> None:
        """
        Initialize MetricsAggregator.

        Args:
            weights: Dictionary of metric weights
        """
        self.weights = weights

    def aggregate(self, all_results: Dict[str, Dict[str, Any]]) -> QualityMetrics:
        """
        Aggregate results from all analyzers into QualityMetrics.

        Args:
            all_results: Results from all files and analyzers

        Returns:
            Aggregated QualityMetrics
        """
        # Initialize metrics
        metrics = QualityMetrics()
        
        # Accumulators
        total_complexity_score = 0.0
        total_duplication_score = 0.0
        total_maintainability_score = 0.0
        total_naming_score = 0.0
        total_documentation_score = 0.0
        total_testability_score = 0.0
        
        documentation_coverage_sum = 0.0
        
        file_count = 0
        all_hotspots = []
        all_quick_wins = []

        for file_path, file_results in all_results.items():
            if not file_results:
                continue

            file_count += 1
            
            # Process Complexity
            if file_results.get("complexity"):
                score, cyclomatic, hotspots = self._process_complexity_results(file_results["complexity"], file_path)
                total_complexity_score += score
                metrics.cyclomatic_complexity += cyclomatic
                all_hotspots.extend(hotspots)
                
            # Process Duplication
            if file_results.get("duplication"):
                score, blocks, lines, quick_wins = self._process_duplication_results(file_results["duplication"], file_path)
                total_duplication_score += score
                metrics.duplicate_blocks += blocks
                metrics.duplicate_lines += lines
                all_quick_wins.extend(quick_wins)
                
            # Process Maintainability
            if file_results.get("maintainability"):
                score, loc = self._process_maintainability_results(file_results["maintainability"])
                total_maintainability_score += score
                metrics.lines_of_code += loc
                
            # Process Naming
            if file_results.get("naming"):
                total_naming_score += self._process_naming_results(file_results["naming"])
                
            # Process Documentation
            if file_results.get("documentation"):
                score, coverage, quick_wins = self._process_documentation_results(file_results["documentation"], file_path)
                total_documentation_score += score
                documentation_coverage_sum += coverage
                all_quick_wins.extend(quick_wins)
                
            # Process Testability
            if file_results.get("testability"):
                score, coverage = self._process_testability_results(file_results["testability"])
                total_testability_score += score
                metrics.test_coverage += coverage  # Note: This is usually per file, accumulation might need average
                
            # Process Magic Numbers
            if file_results.get("magic_numbers"):
                 all_hotspots.extend(self._process_magic_numbers_results(file_results["magic_numbers"], file_path))

        # Calculate averages and final metrics
        if file_count > 0:
            metrics.complexity_score = total_complexity_score / file_count
            metrics.duplication_score = total_duplication_score / file_count
            metrics.maintainability_score = total_maintainability_score / file_count
            metrics.naming_score = total_naming_score / file_count
            metrics.documentation_score = total_documentation_score / file_count
            metrics.testability_score = total_testability_score / file_count
            metrics.documentation_coverage = documentation_coverage_sum / file_count
            # Test coverage average if tracked per file
            if metrics.test_coverage > 0:
                 metrics.test_coverage = metrics.test_coverage / file_count
        else:
             # Defaults are already 0.0 in QualityMetrics, but if we want 5.0 base:
            metrics.complexity_score = 5.0
            metrics.duplication_score = 5.0
            metrics.maintainability_score = 5.0
            metrics.naming_score = 5.0
            metrics.documentation_score = 5.0
            metrics.testability_score = 5.0

        # Calculate Technical Debt
        td_hours = 0.0
        td_hours += (10 - metrics.complexity_score) * 2
        td_hours += (10 - metrics.duplication_score) * 1
        td_hours += (10 - metrics.maintainability_score) * 1.5
        td_hours += (10 - metrics.documentation_score) * 0.5
        metrics.technical_debt_hours = max(0.0, td_hours)

        # Sort and limit
        all_hotspots.sort(key=lambda h: h.impact_score, reverse=True)
        metrics.hotspots = all_hotspots[:10]
        
        all_quick_wins.sort(key=lambda q: q.score_improvement, reverse=True)
        metrics.quick_wins = all_quick_wins[:5]
        
        # Breakdown
        metrics.metric_breakdowns = [
            MetricBreakdown(name="complexity", score=metrics.complexity_score, weight=self.weights.get("complexity", 0.0)),
            MetricBreakdown(name="duplication", score=metrics.duplication_score, weight=self.weights.get("duplication", 0.0)),
            MetricBreakdown(name="maintainability", score=metrics.maintainability_score, weight=self.weights.get("maintainability", 0.0)),
            MetricBreakdown(name="naming", score=metrics.naming_score, weight=self.weights.get("naming", 0.0)),
            MetricBreakdown(name="documentation", score=metrics.documentation_score, weight=self.weights.get("documentation", 0.0)),
            MetricBreakdown(name="testability", score=metrics.testability_score, weight=self.weights.get("testability", 0.0)),
        ]
        
        metrics.overall_score = metrics.calculate_overall_score()
        return metrics

    def _process_complexity_results(self, result: Any, file_path: str) -> tuple[float, int, List[CodeHotspot]]:
        """Process complexity analyzer results."""
        score = 0.0
        cyclomatic = 0
        hotspots = []
        
        if result.success and result.metrics:
            issues = result.issues_found
            score = max(0, 10 - (issues * 0.5))
            
            if "long_methods" in result.metrics:
                cyclomatic = result.metrics.get("long_methods", 0) * 10
                
            for suggestion in result.suggestions[:3]:
                if suggestion.issue:
                    hotspots.append(CodeHotspot(
                        file_path=file_path,
                        line_number=suggestion.issue.line_number,
                        issue_type="high_complexity",
                        severity=suggestion.issue.severity.value,
                        message=suggestion.issue.description,
                        impact_score=2.0
                    ))
        return score, cyclomatic, hotspots

    def _process_duplication_results(self, result: Any, file_path: str) -> tuple[float, int, int, List[QuickWin]]:
        """Process duplication analyzer results."""
        score = 0.0
        blocks = 0
        lines = 0
        quick_wins = []
        
        if result.success:
            issues = result.issues_found
            score = max(0, 10 - (issues * 0.8))
            
            if result.metrics:
                blocks = result.metrics.get("duplicate_blocks", 0)
                lines = result.metrics.get("total_duplicated_lines", 0)
                
            if issues > 0:
                quick_wins.append(QuickWin(
                    type="remove_duplication",
                    description=f"Extract {issues} duplicate code blocks",
                    estimated_effort="30min",
                    score_improvement=0.5,
                    file_path=file_path
                ))
        return score, blocks, lines, quick_wins

    def _process_maintainability_results(self, result: Any) -> tuple[float, int]:
        """Process maintainability analyzer results."""
        score = 0.0
        loc = 0
        
        if result.success and result.metrics:
            score = result.metrics.get("quality_score", 5.0)
            if "halstead_volume" in result.metrics:
                 loc = 100 # Approximate
        return score, loc

    def _process_naming_results(self, result: Any) -> float:
        """Process naming analyzer results."""
        if result.success:
            issues = result.issues_found
            return max(0, 10 - (issues * 0.3))
        return 0.0

    def _process_documentation_results(self, result: Any, file_path: str) -> tuple[float, float, List[QuickWin]]:
        """Process documentation analyzer results."""
        score = 0.0
        coverage = 0.0
        quick_wins = []
        
        if result.success and result.metrics:
            score = result.metrics.get("quality_score", 5.0)
            coverage = result.metrics.get("documentation_coverage", 0.0)
            
            if score < 5:
                quick_wins.append(QuickWin(
                    type="add_documentation",
                    description="Add missing docstrings",
                    estimated_effort="15min",
                    score_improvement=0.3,
                    file_path=file_path
                ))
        return score, coverage, quick_wins

    def _process_testability_results(self, result: Any) -> tuple[float, float]:
        """Process testability analyzer results."""
        score = 0.0
        coverage = 0.0
        if result.success and result.metrics:
            score = result.metrics.get("testability_score", 5.0)
            # Assuming coverage might be there
            coverage = result.metrics.get("test_coverage", 0.0)
        return score, coverage

    def _process_magic_numbers_results(self, result: Any, file_path: str) -> List[CodeHotspot]:
        """Process magic number analyzer results."""
        hotspots = []
        if result.success and result.issues_found > 5:
            hotspots.append(CodeHotspot(
                file_path=file_path,
                line_number=1,
                issue_type="magic_numbers",
                severity="medium",
                message=f"{result.issues_found} magic numbers found",
                impact_score=1.0
            ))
        return hotspots
