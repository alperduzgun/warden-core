"""
PRE-ANALYSIS Phase Orchestrator.

Phase 0 of the 6-phase pipeline that analyzes project structure and file contexts
to enable context-aware analysis and false positive prevention.
"""

import asyncio
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
import structlog

from warden.analysis.domain.file_context import (
    FileContext,
    PreAnalysisResult,
)
from warden.analysis.domain.project_context import ProjectContext
from warden.analysis.application.project_structure_analyzer import ProjectStructureAnalyzer
from warden.analysis.application.file_context_analyzer import FileContextAnalyzer
from warden.validation.domain.frame import CodeFile

logger = structlog.get_logger()


class PreAnalysisPhase:
    """
    PRE-ANALYSIS Phase orchestrator (Phase 0).

    Analyzes project structure and determines file contexts before
    the main analysis pipeline begins. This enables context-aware
    analysis and false positive prevention.
    """

    def __init__(
        self,
        project_root: Path,
        progress_callback: Optional[Callable] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize PRE-ANALYSIS phase.

        Args:
            project_root: Root directory of the project
            progress_callback: Optional callback for progress updates
            config: Optional configuration including LLM settings
        """
        self.project_root = Path(project_root)
        self.progress_callback = progress_callback
        self.config = config or {}

        # Initialize analyzers
        self.project_analyzer = ProjectStructureAnalyzer(self.project_root)
        self.file_analyzer: Optional[FileContextAnalyzer] = None  # Created after project analysis
        self.llm_analyzer = None  # Will be initialized if enabled

    async def execute(self, code_files: List[CodeFile]) -> PreAnalysisResult:
        """
        Execute PRE-ANALYSIS phase.

        Args:
            code_files: List of code files to analyze

        Returns:
            PreAnalysisResult with project and file contexts
        """
        start_time = time.perf_counter()

        logger.info(
            "pre_analysis_phase_started",
            project_root=str(self.project_root),
            file_count=len(code_files),
        )

        # Notify progress
        if self.progress_callback:
            self.progress_callback("pre_analysis_started", {
                "phase": "pre_analysis",
                "total_files": len(code_files),
            })

        try:
            # Step 1: Initialize LLM analyzer if enabled
            await self._initialize_llm_analyzer()

            # Step 2: Analyze project structure
            project_context = await self._analyze_project_structure()

            # Step 3: Initialize file analyzer with project context and LLM
            self.file_analyzer = FileContextAnalyzer(project_context, self.llm_analyzer)

            # Step 4: Analyze file contexts in parallel
            file_contexts = await self._analyze_file_contexts(code_files)

            # Step 5: Calculate statistics
            statistics = self._calculate_statistics(file_contexts)

            # Create result
            result = PreAnalysisResult(
                project_context=project_context,
                file_contexts=file_contexts,
                total_files_analyzed=len(file_contexts),
                files_by_context=statistics["files_by_context"],
                total_suppressions_configured=statistics["total_suppressions"],
                suppression_by_context=statistics["suppression_by_context"],
                analysis_duration=time.perf_counter() - start_time,
            )

            logger.info(
                "pre_analysis_phase_completed",
                project_type=project_context.project_type.value,
                framework=project_context.framework.value,
                files_analyzed=result.total_files_analyzed,
                context_distribution=result.files_by_context,
                duration=result.analysis_duration,
            )

            # Notify completion
            if self.progress_callback:
                self.progress_callback("pre_analysis_completed", {
                    "phase": "pre_analysis",
                    "project_type": project_context.project_type.value,
                    "framework": project_context.framework.value,
                    "contexts": result.get_context_summary(),
                    "duration": f"{result.analysis_duration:.2f}s",
                })

            return result

        except Exception as e:
            logger.error(
                "pre_analysis_phase_failed",
                error=str(e),
            )

            # Return minimal result on failure
            return PreAnalysisResult(
                project_context=ProjectContext(
                    project_root=str(self.project_root),
                    project_name=self.project_root.name,
                ),
                file_contexts={},
                analysis_duration=time.perf_counter() - start_time,
            )

    async def _initialize_llm_analyzer(self) -> None:
        """Initialize LLM analyzer if enabled in config."""
        use_llm = self.config.get("pre_analysis", {}).get("use_llm", False)

        if not use_llm:
            logger.info("llm_disabled_for_pre_analysis")
            return

        try:
            from warden.analysis.application.llm_context_analyzer import LlmContextAnalyzer
            from warden.llm.config import load_llm_config_async

            # Load LLM configuration
            llm_config = await load_llm_config_async()

            # Get PRE-ANALYSIS specific config
            pre_analysis_config = self.config.get("pre_analysis", {})
            confidence_threshold = pre_analysis_config.get("llm_threshold", 0.7)
            batch_size = pre_analysis_config.get("batch_size", 10)

            # Initialize LLM analyzer
            self.llm_analyzer = LlmContextAnalyzer(
                llm_config=llm_config,
                confidence_threshold=confidence_threshold,
                batch_size=batch_size,
                cache_enabled=True,
            )

            logger.info(
                "llm_analyzer_initialized",
                confidence_threshold=confidence_threshold,
                batch_size=batch_size,
            )

        except Exception as e:
            logger.warning(
                "llm_initialization_failed",
                error=str(e),
                fallback="rule-based detection only",
            )
            self.llm_analyzer = None

    async def _analyze_project_structure(self) -> ProjectContext:
        """
        Analyze project structure and characteristics.

        Returns:
            ProjectContext with detected information
        """
        logger.info("analyzing_project_structure")

        # Run project structure analysis
        project_context = await self.project_analyzer.analyze_async()

        logger.info(
            "project_structure_analyzed",
            project_type=project_context.project_type.value,
            framework=project_context.framework.value,
            architecture=project_context.architecture.value,
            test_framework=project_context.test_framework.value,
            build_tools=[t.value for t in project_context.build_tools],
            confidence=project_context.confidence,
        )

        return project_context

    async def _analyze_file_contexts(
        self,
        code_files: List[CodeFile]
    ) -> Dict[str, Any]:
        """
        Analyze context for each file.

        Args:
            code_files: List of code files to analyze

        Returns:
            Dictionary mapping file paths to FileContextInfo
        """
        logger.info(
            "analyzing_file_contexts",
            file_count=len(code_files),
        )

        # Create tasks for parallel analysis
        tasks = []
        for code_file in code_files:
            task = asyncio.create_task(
                self._analyze_single_file(code_file)
            )
            tasks.append((code_file.path, task))

        # Wait for all analyses to complete
        file_contexts = {}
        for file_path, task in tasks:
            try:
                context_info = await task
                file_contexts[file_path] = context_info
            except Exception as e:
                logger.warning(
                    "file_context_analysis_failed",
                    file=file_path,
                    error=str(e),
                )
                # Use default production context on failure
                file_contexts[file_path] = self._get_default_context(file_path)

        return file_contexts

    async def _analyze_single_file(self, code_file: CodeFile) -> Any:
        """
        Analyze a single file's context.

        Args:
            code_file: Code file to analyze

        Returns:
            FileContextInfo for the file
        """
        # Run analysis in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.file_analyzer.analyze_file,
            Path(code_file.path)
        )

    def _get_default_context(self, file_path: str) -> Any:
        """
        Get default context for a file when analysis fails.

        Args:
            file_path: Path to the file

        Returns:
            Default FileContextInfo with production context
        """
        from warden.analysis.domain.file_context import FileContextInfo, ContextWeights

        return FileContextInfo(
            file_path=file_path,
            context=FileContext.PRODUCTION,
            confidence=0.0,
            detection_method="default",
            weights=ContextWeights(FileContext.PRODUCTION),
            suppressed_issues=[],
            suppression_reason="Analysis failed - using default production rules",
        )

    def _calculate_statistics(
        self,
        file_contexts: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate statistics from file contexts.

        Args:
            file_contexts: Dictionary of file contexts

        Returns:
            Statistics dictionary
        """
        files_by_context = {}
        suppression_by_context = {}
        total_suppressions = 0

        for context_info in file_contexts.values():
            # Count files by context
            context_name = context_info.context.value
            files_by_context[context_name] = files_by_context.get(context_name, 0) + 1

            # Count suppressions
            if context_info.suppressed_issues:
                suppression_count = len(context_info.suppressed_issues)
                if suppression_count > 0:
                    total_suppressions += suppression_count
                    suppression_by_context[context_name] = suppression_by_context.get(context_name, 0) + suppression_count

        return {
            "files_by_context": files_by_context,
            "suppression_by_context": suppression_by_context,
            "total_suppressions": total_suppressions,
        }

    async def execute_with_weights(
        self,
        code_files: List[CodeFile],
        custom_weights: Optional[Dict[str, Dict[str, float]]] = None
    ) -> PreAnalysisResult:
        """
        Execute PRE-ANALYSIS with custom weight configurations.

        Args:
            code_files: List of code files to analyze
            custom_weights: Optional custom weights per context

        Returns:
            PreAnalysisResult with custom weights applied
        """
        # Run standard analysis
        result = await self.execute(code_files)

        # Apply custom weights if provided
        if custom_weights:
            for file_path, context_info in result.file_contexts.items():
                context_name = context_info.context.value
                if context_name in custom_weights:
                    # Update weights in context info
                    for metric, weight in custom_weights[context_name].items():
                        context_info.weights.weights[metric] = weight

            logger.info(
                "custom_weights_applied",
                contexts=list(custom_weights.keys()),
            )

        return result

    def get_suppression_summary(self, result: PreAnalysisResult) -> str:
        """
        Get human-readable summary of suppressions.

        Args:
            result: PreAnalysisResult to summarize

        Returns:
            Formatted suppression summary
        """
        if not result.suppression_by_context:
            return "No suppressions configured"

        summary_parts = []
        for context, count in sorted(result.suppression_by_context.items()):
            summary_parts.append(f"{context}: {count} suppressions")

        total = result.total_suppressions_configured
        summary = f"Total: {total} suppressions | " + " | ".join(summary_parts)

        return summary

    def should_skip_file(
        self,
        file_path: str,
        result: PreAnalysisResult
    ) -> bool:
        """
        Determine if a file should be skipped in analysis.

        Args:
            file_path: Path to check
            result: PreAnalysisResult with file contexts

        Returns:
            True if file should be skipped
        """
        if file_path not in result.file_contexts:
            return False  # Don't skip unknown files

        context_info = result.file_contexts[file_path]

        # Skip vendor and generated files
        if context_info.is_vendor or context_info.is_generated:
            logger.debug(
                "skipping_file",
                file=file_path,
                reason="vendor_or_generated",
            )
            return True

        # Skip documentation files
        if context_info.context == FileContext.DOCUMENTATION:
            logger.debug(
                "skipping_file",
                file=file_path,
                reason="documentation",
            )
            return True

        # Skip files with ignore markers
        if context_info.has_ignore_marker:
            logger.debug(
                "skipping_file",
                file=file_path,
                reason="ignore_marker",
            )
            return True

        return False