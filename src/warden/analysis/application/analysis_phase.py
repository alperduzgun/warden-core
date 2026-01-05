"""
Analysis Phase Orchestrator

Coordinates all static analyzers to produce quality metrics for the ANALYSIS phase.
This is the first phase of the 5-phase pipeline.
"""

import asyncio
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
import structlog

from warden.analysis.domain.quality_metrics import (
    QualityMetrics,
    CodeHotspot,
    QuickWin,
    MetricBreakdown,
)
from warden.cleaning.application.analyzers.complexity_analyzer import ComplexityAnalyzer
from warden.cleaning.application.analyzers.duplication_analyzer import DuplicationAnalyzer
from warden.cleaning.application.analyzers.naming_analyzer import NamingAnalyzer
from warden.cleaning.application.analyzers.magic_number_analyzer import MagicNumberAnalyzer
from warden.cleaning.application.analyzers.maintainability_analyzer import MaintainabilityAnalyzer
from warden.cleaning.application.analyzers.documentation_analyzer import DocumentationAnalyzer
from warden.cleaning.application.analyzers.testability_analyzer import TestabilityAnalyzer
from warden.validation.domain.frame import CodeFile
from warden.shared.infrastructure.exceptions import ValidationError
from warden.shared.infrastructure.ignore_matcher import IgnoreMatcher

logger = structlog.get_logger()


class AnalysisPhase:
    """
    Analysis Phase orchestrator for quality metrics calculation.

    Coordinates multiple analyzers to produce a comprehensive quality score
    for the Panel UI's Summary tab.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[callable] = None,
        project_root: Optional[Path] = None,
        use_gitignore: bool = True,
    ) -> None:
        """
        Initialize Analysis Phase.

        Args:
            config: Analysis configuration including weights and LLM settings
            progress_callback: Optional callback for progress updates
        """
        self.config = config or self._get_default_config()
        self.progress_callback = progress_callback

        # Initialize analyzers
        self.analyzers = {
            "complexity": ComplexityAnalyzer(),
            "duplication": DuplicationAnalyzer(),
            "naming": NamingAnalyzer(),
            "magic_numbers": MagicNumberAnalyzer(),
            "maintainability": MaintainabilityAnalyzer(),
            "documentation": DocumentationAnalyzer(),
            "testability": TestabilityAnalyzer(),
        }
        
        # Initialize IgnoreMatcher
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.ignore_matcher = IgnoreMatcher(self.project_root, use_gitignore=use_gitignore)

        # Get metric weights from config
        self.weights = self.config.get("weights", self._get_default_weights())

        logger.info(
            "analysis_phase_initialized",
            analyzer_count=len(self.analyzers),
            weights=self.weights,
        )

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default analysis configuration."""
        return {
            "enabled": True,
            "use_llm": False,  # LLM enhancement disabled by default
            "llm_provider": "azure_openai",
            "weights": self._get_default_weights(),
            "timeout": 5.0,  # 5 second timeout for analysis phase
        }

    def _get_default_weights(self) -> Dict[str, float]:
        """Get default metric weights for score calculation."""
        return {
            "complexity": 0.25,
            "duplication": 0.20,
            "maintainability": 0.20,
            "naming": 0.15,
            "documentation": 0.10,
            "testability": 0.10,
        }

    async def execute(
        self,
        code_files: List[CodeFile],
        impacted_files: Optional[List[str]] = None,
    ) -> QualityMetrics:
        """
        Execute analysis phase on code files.

        Args:
            code_files: List of code files to analyze

        Returns:
            QualityMetrics with comprehensive scoring

        Raises:
            ValidationError: If analysis fails
        """
        # Filter files based on ignore matcher
        original_count = len(code_files)
        code_files = [
            cf for cf in code_files 
            if not self.ignore_matcher.should_ignore_for_frame(Path(cf.path), "analysis")
        ]
        
        if len(code_files) < original_count:
            logger.info(
                "analysis_phase_files_ignored",
                ignored=original_count - len(code_files),
                remaining=len(code_files)
            )

        if not code_files:
            return QualityMetrics()

        start_time = time.perf_counter()

        logger.info(
            "analysis_phase_started",
            file_count=len(code_files),
        )

        # Notify progress callback
        if self.progress_callback:
            self.progress_callback("analysis_started", {
                "phase": "analysis",
                "total_files": len(code_files),
            })

        try:
            # Run all analyzers in parallel for each file
            all_results = {}
            for code_file in code_files:
                file_results = await self._analyze_file(code_file)
                all_results[code_file.path] = file_results

            # Aggregate results
            metrics = self._aggregate_results(all_results)

            # Calculate analysis duration
            metrics.analysis_duration = time.perf_counter() - start_time
            metrics.file_count = len(code_files)

            logger.info(
                "analysis_phase_completed",
                overall_score=metrics.overall_score,
                duration=metrics.analysis_duration,
                hotspots_found=len(metrics.hotspots),
                quick_wins_found=len(metrics.quick_wins),
            )

            # Notify progress callback with final score
            if self.progress_callback:
                self.progress_callback("analysis_completed", {
                    "phase": "analysis",
                    "score": f"{metrics.overall_score:.1f}/10.0",
                    "duration": f"{metrics.analysis_duration:.2f}s",
                })

            return metrics

        except Exception as e:
            logger.error(
                "analysis_phase_failed",
                error=str(e),
            )
            # Return basic metrics on failure
            return QualityMetrics(
                overall_score=5.0,  # Default middle score
                analysis_duration=time.perf_counter() - start_time,
                file_count=len(code_files),
            )

    async def _analyze_file(self, code_file: CodeFile) -> Dict[str, Any]:
        """
        Run all analyzers on a single file.

        Args:
            code_file: Code file to analyze

        Returns:
            Dictionary with analyzer results
        """
        # Create tasks for parallel execution
        tasks = {}

        # Core analyzers for scoring
        tasks["complexity"] = asyncio.create_task(
            self.analyzers["complexity"].analyze_async(code_file)
        )
        tasks["duplication"] = asyncio.create_task(
            self.analyzers["duplication"].analyze_async(code_file)
        )
        tasks["maintainability"] = asyncio.create_task(
            self.analyzers["maintainability"].analyze_async(code_file)
        )
        tasks["naming"] = asyncio.create_task(
            self.analyzers["naming"].analyze_async(code_file)
        )
        tasks["documentation"] = asyncio.create_task(
            self.analyzers["documentation"].analyze_async(code_file)
        )
        tasks["testability"] = asyncio.create_task(
            self.analyzers["testability"].analyze_async(code_file)
        )

        # Additional analyzer for hotspots
        tasks["magic_numbers"] = asyncio.create_task(
            self.analyzers["magic_numbers"].analyze_async(code_file)
        )

        # Wait for all analyzers with timeout
        try:
            timeout = self.config.get("timeout", 5.0)
            results = await asyncio.wait_for(
                asyncio.gather(*tasks.values(), return_exceptions=True),
                timeout=timeout
            )

            # Map results back to analyzer names
            analyzer_results = {}
            for (name, _), result in zip(tasks.items(), results):
                if isinstance(result, Exception):
                    logger.warning(
                        "analyzer_failed",
                        analyzer=name,
                        error=str(result),
                        file=code_file.path,
                    )
                    analyzer_results[name] = None
                else:
                    analyzer_results[name] = result

            return analyzer_results

        except asyncio.TimeoutError:
            logger.warning(
                "file_analysis_timeout",
                file=code_file.path,
                timeout=timeout,
            )
            return {}

    def _aggregate_results(self, all_results: Dict[str, Dict[str, Any]]) -> QualityMetrics:
        """
        Aggregate results from all analyzers into QualityMetrics.

        Args:
            all_results: Results from all files and analyzers

        Returns:
            Aggregated QualityMetrics
        """
        # Initialize scores
        total_complexity_score = 0
        total_duplication_score = 0
        total_maintainability_score = 0
        total_naming_score = 0
        total_documentation_score = 0
        total_testability_score = 0

        # Aggregate metrics
        total_cyclomatic = 0
        total_cognitive = 0
        total_loc = 0
        total_duplicate_blocks = 0
        total_duplicate_lines = 0
        documentation_coverage = 0
        test_coverage = 0

        # Collect hotspots and quick wins
        all_hotspots = []
        all_quick_wins = []

        file_count = 0

        for file_path, file_results in all_results.items():
            if not file_results:
                continue

            file_count += 1

            # Extract scores from each analyzer result
            if file_results.get("complexity"):
                result = file_results["complexity"]
                if result.success and result.metrics:
                    # Calculate complexity score (inverse of issues)
                    issues = result.issues_found
                    complexity_score = max(0, 10 - (issues * 0.5))
                    total_complexity_score += complexity_score

                    # Extract metrics
                    if "long_methods" in result.metrics:
                        total_cyclomatic += result.metrics.get("long_methods", 0) * 10

                    # Add hotspots for complex methods
                    for suggestion in result.suggestions[:3]:  # Top 3 issues
                        if suggestion.issue:
                            all_hotspots.append(
                                CodeHotspot(
                                    file_path=file_path,
                                    line_number=suggestion.issue.line_number,
                                    issue_type="high_complexity",
                                    severity=suggestion.issue.severity.value,
                                    message=suggestion.issue.description,
                                    impact_score=2.0,
                                )
                            )

            if file_results.get("duplication"):
                result = file_results["duplication"]
                if result.success:
                    # Calculate duplication score
                    issues = result.issues_found
                    duplication_score = max(0, 10 - (issues * 0.8))
                    total_duplication_score += duplication_score

                    # Extract metrics
                    if result.metrics:
                        total_duplicate_blocks += result.metrics.get("duplicate_blocks", 0)
                        total_duplicate_lines += result.metrics.get("total_duplicated_lines", 0)

                    # Add quick win for duplication
                    if issues > 0:
                        all_quick_wins.append(
                            QuickWin(
                                type="remove_duplication",
                                description=f"Extract {issues} duplicate code blocks",
                                estimated_effort="30min",
                                score_improvement=0.5,
                                file_path=file_path,
                            )
                        )

            if file_results.get("maintainability"):
                result = file_results["maintainability"]
                if result.success and result.metrics:
                    # Use the quality score from maintainability analyzer
                    maintainability_score = result.metrics.get("quality_score", 5.0)
                    total_maintainability_score += maintainability_score

                    # Add LOC
                    if "halstead_volume" in result.metrics:
                        total_loc += 100  # Approximate from Halstead

            if file_results.get("naming"):
                result = file_results["naming"]
                if result.success:
                    # Calculate naming score
                    issues = result.issues_found
                    naming_score = max(0, 10 - (issues * 0.3))
                    total_naming_score += naming_score

            if file_results.get("documentation"):
                result = file_results["documentation"]
                if result.success and result.metrics:
                    # Use the quality score from documentation analyzer
                    doc_score = result.metrics.get("quality_score", 5.0)
                    total_documentation_score += doc_score
                    documentation_coverage += result.metrics.get("documentation_coverage", 0)

                    # Add quick win for missing docs
                    if doc_score < 5:
                        all_quick_wins.append(
                            QuickWin(
                                type="add_documentation",
                                description="Add missing docstrings",
                                estimated_effort="15min",
                                score_improvement=0.3,
                                file_path=file_path,
                            )
                        )

            if file_results.get("testability"):
                result = file_results["testability"]
                if result.success and result.metrics:
                    # Use the testability score
                    test_score = result.metrics.get("testability_score", 5.0)
                    total_testability_score += test_score

            # Check magic numbers for hotspots
            if file_results.get("magic_numbers"):
                result = file_results["magic_numbers"]
                if result.success and result.issues_found > 5:
                    all_hotspots.append(
                        CodeHotspot(
                            file_path=file_path,
                            line_number=1,
                            issue_type="magic_numbers",
                            severity="medium",
                            message=f"{result.issues_found} magic numbers found",
                            impact_score=1.0,
                        )
                    )

        # Calculate average scores
        if file_count > 0:
            complexity_score = total_complexity_score / file_count
            duplication_score = total_duplication_score / file_count
            maintainability_score = total_maintainability_score / file_count
            naming_score = total_naming_score / file_count
            documentation_score = total_documentation_score / file_count
            testability_score = total_testability_score / file_count
            avg_doc_coverage = documentation_coverage / file_count
        else:
            # Default scores if no files
            complexity_score = 5.0
            duplication_score = 5.0
            maintainability_score = 5.0
            naming_score = 5.0
            documentation_score = 5.0
            testability_score = 5.0
            avg_doc_coverage = 0.0

        # Calculate technical debt (rough estimation)
        technical_debt_hours = 0
        technical_debt_hours += (10 - complexity_score) * 2  # 2 hours per complexity point
        technical_debt_hours += (10 - duplication_score) * 1  # 1 hour per duplication point
        technical_debt_hours += (10 - maintainability_score) * 1.5
        technical_debt_hours += (10 - documentation_score) * 0.5
        technical_debt_hours = max(0, technical_debt_hours)

        # Sort and limit hotspots/quick wins
        all_hotspots.sort(key=lambda h: h.impact_score, reverse=True)
        all_quick_wins.sort(key=lambda q: q.score_improvement, reverse=True)

        # Create QualityMetrics
        metrics = QualityMetrics(
            complexity_score=complexity_score,
            duplication_score=duplication_score,
            maintainability_score=maintainability_score,
            naming_score=naming_score,
            documentation_score=documentation_score,
            testability_score=testability_score,

            # Detailed metrics
            cyclomatic_complexity=total_cyclomatic,
            cognitive_complexity=total_cognitive,
            lines_of_code=total_loc,
            duplicate_blocks=total_duplicate_blocks,
            duplicate_lines=total_duplicate_lines,
            documentation_coverage=avg_doc_coverage,
            test_coverage=test_coverage,

            # Technical debt
            technical_debt_hours=technical_debt_hours,

            # Top hotspots and quick wins
            hotspots=all_hotspots[:10],  # Top 10 hotspots
            quick_wins=all_quick_wins[:5],  # Top 5 quick wins
        )

        # Create metric breakdowns with configured weights
        metrics.metric_breakdowns = [
            MetricBreakdown("complexity", complexity_score, self.weights["complexity"]),
            MetricBreakdown("duplication", duplication_score, self.weights["duplication"]),
            MetricBreakdown("maintainability", maintainability_score, self.weights["maintainability"]),
            MetricBreakdown("naming", naming_score, self.weights["naming"]),
            MetricBreakdown("documentation", documentation_score, self.weights["documentation"]),
            MetricBreakdown("testability", testability_score, self.weights["testability"]),
        ]

        # Calculate overall score
        metrics.overall_score = metrics.calculate_overall_score()

        return metrics

    async def execute_with_llm(self, code_files: List[CodeFile]) -> QualityMetrics:
        """
        Execute analysis with LLM enhancement.

        Args:
            code_files: List of code files to analyze

        Returns:
            Enhanced QualityMetrics with LLM insights

        Note:
            This is a placeholder for future LLM integration.
            Will be implemented when LLM analyzer is added.
        """
        # First run standard analysis
        metrics = await self.execute(code_files)

        if self.config.get("use_llm", False):
            logger.info("llm_enhancement_requested_but_not_implemented")
            # TODO: Integrate LLM analyzer when available
            # llm_insights = await self.llm_analyzer.enhance_metrics(metrics, code_files)
            # metrics.llm_insights = llm_insights

        return metrics