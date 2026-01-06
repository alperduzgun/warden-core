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
)
from warden.analysis.application.metrics_aggregator import MetricsAggregator
from warden.cleaning.application.analyzers.complexity_analyzer import ComplexityAnalyzer
from warden.cleaning.application.analyzers.duplication_analyzer import DuplicationAnalyzer
from warden.cleaning.application.analyzers.naming_analyzer import NamingAnalyzer
from warden.cleaning.application.analyzers.magic_number_analyzer import MagicNumberAnalyzer
from warden.cleaning.application.analyzers.maintainability_analyzer import MaintainabilityAnalyzer
from warden.cleaning.application.analyzers.documentation_analyzer import DocumentationAnalyzer
from warden.cleaning.application.analyzers.testability_analyzer import TestabilityAnalyzer
from warden.cleaning.application.analyzers.lsp_diagnostics_analyzer import LSPDiagnosticsAnalyzer
from warden.validation.domain.frame import CodeFile

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
            "lsp_diagnostics": LSPDiagnosticsAnalyzer(),
        }
        
        # Initialize IgnoreMatcher
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.ignore_matcher = IgnoreMatcher(self.project_root, use_gitignore=use_gitignore)

        # Get metric weights from config
        self.weights = self.config.get("weights", self._get_default_weights())
        
        # Initialize Metrics Aggregator
        self.metrics_aggregator = MetricsAggregator(self.weights)

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
        pipeline_context: Optional[Any] = None,
        impacted_files: Optional[List[str]] = None,
    ) -> QualityMetrics:
        """
        Execute analysis phase on code files.

        Args:
            code_files: List of code files to analyze
            pipeline_context: Optional pipeline context with cached ASTs
            impacted_files: Optional list of impacted files

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
                file_results = await self._analyze_file(code_file, pipeline_context)
                all_results[code_file.path] = file_results

            # Aggregate results using MetricsAggregator
            metrics = self.metrics_aggregator.aggregate(all_results)

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

    async def _analyze_file(self, code_file: CodeFile, pipeline_context: Optional[Any] = None) -> Dict[str, Any]:
        """
        Run all analyzers on a single file.

        Args:
            code_file: Code file to analyze
            pipeline_context: Optional pipeline context with cached ASTs

        Returns:
            Dictionary with analyzer results
        """
        # Create tasks for parallel execution
        tasks = {}

        # Get cached AST if available
        ast_tree = None
        if pipeline_context and hasattr(pipeline_context, 'ast_cache'):
            ast_tree = pipeline_context.ast_cache.get(code_file.path)

        # Core analyzers for scoring
        tasks["complexity"] = asyncio.create_task(
            self.analyzers["complexity"].analyze_async(code_file, ast_tree=ast_tree)
        )
        tasks["duplication"] = asyncio.create_task(
            self.analyzers["duplication"].analyze_async(code_file, ast_tree=ast_tree)
        )
        tasks["maintainability"] = asyncio.create_task(
            self.analyzers["maintainability"].analyze_async(code_file, ast_tree=ast_tree)
        )
        tasks["naming"] = asyncio.create_task(
            self.analyzers["naming"].analyze_async(code_file, ast_tree=ast_tree)
        )
        tasks["documentation"] = asyncio.create_task(
            self.analyzers["documentation"].analyze_async(code_file, ast_tree=ast_tree)
        )
        tasks["testability"] = asyncio.create_task(
            self.analyzers["testability"].analyze_async(code_file, ast_tree=ast_tree)
        )
        
        tasks["lsp_diagnostics"] = asyncio.create_task(
            self.analyzers["lsp_diagnostics"].analyze_async(code_file, ast_tree=ast_tree)
        )

        # Additional analyzer for hotspots
        tasks["magic_numbers"] = asyncio.create_task(
            self.analyzers["magic_numbers"].analyze_async(code_file, ast_tree=ast_tree)
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