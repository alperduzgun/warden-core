"""
Cleanup Analyzer - Main Orchestrator

Coordinates all cleanup analyzers to detect code cleanup opportunities.
Executes analyzers in priority order and combines results.
"""

import structlog
from typing import List, Optional

from warden.cleaning.domain.base import BaseCleaningAnalyzer
from warden.cleaning.domain.models import CleaningResult, CleaningSuggestion
from warden.cleaning.application.analyzers import (
    NamingAnalyzer,
    DuplicationAnalyzer,
    MagicNumberAnalyzer,
    ComplexityAnalyzer,
)
from warden.validation.domain.frame import CodeFile

logger = structlog.get_logger()


class CleaningOrchestrator:
    """
    Main cleanup analyzer that orchestrates all cleanup operations.

    Executes analyzers in priority order:
    1. Naming Analyzer (CRITICAL)
    2. Complexity Analyzer (HIGH)
    3. Duplication Analyzer (HIGH)
    4. Magic Number Analyzer (MEDIUM)

    IMPORTANT: Warden is a REPORTER, not a code modifier.
    This analyzer ONLY detects and reports issues, NEVER modifies code.
    """

    def __init__(self, analyzers: Optional[List[BaseCleaningAnalyzer]] = None):
        """
        Initialize Cleanup Analyzer.

        Args:
            analyzers: Optional list of analyzers. If None, uses default set.
        """
        if analyzers is None:
            # Default analyzers
            self._analyzers = [
                NamingAnalyzer(),
                ComplexityAnalyzer(),
                DuplicationAnalyzer(),
                MagicNumberAnalyzer(),
            ]
        else:
            self._analyzers = analyzers

        # Sort by priority (lowest value first)
        self._analyzers.sort(key=lambda a: a.priority)

        logger.info(
            "cleanup_analyzer_initialized",
            analyzer_count=len(self._analyzers),
            analyzers=[a.name for a in self._analyzers],
        )

    async def analyze_async(
        self,
        code_file: CodeFile,
        cancellation_token: Optional[str] = None,
    ) -> CleaningResult:
        """
        Analyze code for cleanup opportunities.

        Args:
            code_file: The code file to analyze
            cancellation_token: Optional cancellation token

        Returns:
            Combined cleanup result from all analyzers

        Raises:
            ValueError: If code_file is None or empty
        """
        if code_file is None:
            raise ValueError("Code file cannot be None")
        
        if not code_file.content:
            logger.info("skipping_empty_file", file_path=code_file.path)
            return CleaningResult(
                success=True,
                file_path=code_file.path,
                issues_found=0,
                suggestions=[],
                cleanup_score=100.0,
                summary="Skipped empty file",
                analyzer_name="CleaningOrchestrator"
            )

        logger.info(
            "cleanup_analysis_started",
            file_path=code_file.path,
            analyzer_count=len(self._analyzers),
        )

        all_suggestions: List[CleaningSuggestion] = []
        failed_analyzers: List[str] = []
        total_issues = 0
        analyzer_metrics = {}

        # Run each analyzer
        for analyzer in self._analyzers:
            try:
                logger.debug(
                    "running_analyzer",
                    analyzer=analyzer.name,
                    priority=analyzer.priority,
                )

                result = await analyzer.analyze_async(code_file, cancellation_token)

                if result.success:
                    all_suggestions.extend(result.suggestions)
                    total_issues += result.issues_found
                    analyzer_metrics[analyzer.name] = result.metrics

                    logger.info(
                        "analyzer_completed",
                        analyzer=analyzer.name,
                        issues_found=result.issues_found,
                        summary=result.summary,
                    )
                else:
                    failed_analyzers.append(analyzer.name)
                    logger.warning(
                        "analyzer_failed",
                        analyzer=analyzer.name,
                        error=result.error_message,
                    )

            except Exception as e:
                failed_analyzers.append(analyzer.name)
                logger.error(
                    "analyzer_exception",
                    analyzer=analyzer.name,
                    error=str(e),
                    error_type=type(e).__name__,
                )

        # Calculate combined cleanup score
        cleanup_score = self._calculate_combined_score(all_suggestions, code_file.content)

        # Build summary
        summary = self._build_summary(total_issues, failed_analyzers)

        logger.info(
            "cleanup_analysis_completed",
            total_issues=total_issues,
            suggestions_count=len(all_suggestions),
            cleanup_score=cleanup_score,
            failed_analyzers=failed_analyzers,
        )

        return CleaningResult(
            success=len(failed_analyzers) == 0,
            file_path=code_file.path,
            issues_found=total_issues,
            suggestions=all_suggestions,
            cleanup_score=cleanup_score,
            summary=summary,
            error_message=(
                f"Failed analyzers: {', '.join(failed_analyzers)}"
                if failed_analyzers
                else None
            ),
            analyzer_name="CleaningOrchestrator",
            metrics={
                "total_analyzers": len(self._analyzers),
                "successful_analyzers": len(self._analyzers) - len(failed_analyzers),
                "failed_analyzers": len(failed_analyzers),
                "analyzer_metrics": analyzer_metrics,
            },
        )

    def _calculate_combined_score(
        self,
        suggestions: List[CleaningSuggestion],
        code: str
    ) -> float:
        """
        Calculate combined cleanup score.

        Args:
            suggestions: All suggestions from analyzers
            code: Source code

        Returns:
            Score from 0-100 (100 = perfect, no issues)
        """
        if not code:
            return 100.0

        total_lines = len(code.split("\n"))
        if total_lines == 0:
            return 100.0

        # Weight issues by severity
        severity_weights = {
            0: 10.0,  # CRITICAL
            1: 5.0,   # HIGH
            2: 2.0,   # MEDIUM
            3: 1.0,   # LOW
            4: 0.5,   # INFO
        }

        total_weight = 0.0
        for suggestion in suggestions:
            severity_value = suggestion.issue.severity.value
            weight = severity_weights.get(severity_value, 1.0)
            total_weight += weight

        # Calculate score (higher weight = lower score)
        issue_density = total_weight / total_lines
        score = max(0.0, 100.0 - (issue_density * 20.0))  # Scale down the impact
        return round(score, 2)

    @staticmethod
    def _build_summary(total_issues: int, failed_analyzers: List[str]) -> str:
        """
        Build human-readable summary.

        Args:
            total_issues: Total number of issues found
            failed_analyzers: List of analyzers that failed

        Returns:
            Summary string
        """
        if total_issues == 0 and not failed_analyzers:
            return "No cleanup issues found - code looks great!"

        lines = []

        if total_issues > 0:
            lines.append(f"Found {total_issues} cleanup opportunities")
        else:
            lines.append("No cleanup issues found")

        if failed_analyzers:
            lines.append(f"Warning: {len(failed_analyzers)} analyzers failed")

        return "\n".join(lines)

    def get_analyzers(self) -> List[BaseCleaningAnalyzer]:
        """Get list of registered analyzers."""
        return self._analyzers.copy()

    def add_analyzer(self, analyzer: BaseCleaningAnalyzer) -> None:
        """
        Add a new analyzer.

        Args:
            analyzer: Analyzer to add
        """
        self._analyzers.append(analyzer)
        self._analyzers.sort(key=lambda a: a.priority)

        logger.info("analyzer_added", analyzer=analyzer.name)

    def remove_analyzer(self, analyzer_name: str) -> bool:
        """
        Remove an analyzer by name.

        Args:
            analyzer_name: Name of analyzer to remove

        Returns:
            True if removed, False if not found
        """
        initial_count = len(self._analyzers)
        self._analyzers = [a for a in self._analyzers if a.name != analyzer_name]

        removed = len(self._analyzers) < initial_count
        if removed:
            logger.info("analyzer_removed", analyzer=analyzer_name)
        else:
            logger.warning("analyzer_not_found", analyzer=analyzer_name)

        return removed
