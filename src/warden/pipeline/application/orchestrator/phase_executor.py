"""
Phase executor for individual pipeline phases.

Refactored to delegate to specific phase executors.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from warden.analysis.application.triage_phase import TriagePhase  # Phase 0.5
from warden.pipeline.application.executors.analysis_executor import AnalysisExecutor
from warden.pipeline.application.executors.classification_executor import ClassificationExecutor
from warden.pipeline.application.executors.cleaning_executor import CleaningExecutor
from warden.pipeline.application.executors.fortification_executor import FortificationExecutor

# Import specific executors
from warden.pipeline.application.executors.pre_analysis_executor import PreAnalysisExecutor
from warden.pipeline.domain.models import PipelineConfig
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile, ValidationFrame

logger = get_logger(__name__)


class PhaseExecutor:
    """
    Executes individual pipeline phases.

    Acts as a facade delegating to specific phase executors.
    """

    def __init__(
        self,
        config: PipelineConfig | None = None,
        progress_callback: Callable | None = None,
        project_root: Path | None = None,
        llm_service: Any | None = None,
        frames: list[ValidationFrame] | None = None,
        semantic_search_service: Any | None = None,
        rate_limiter: Any | None = None,
    ):
        """
        Initialize phase executor.

        Args:
            config: Pipeline configuration
            progress_callback: Optional callback for progress updates
            project_root: Root directory of the project
            llm_service: Optional LLM service for AI-powered phases
            frames: List of all available validation frames
            semantic_search_service: Optional semantic search service
        """
        self.config = config or PipelineConfig()
        self._progress_callback = progress_callback
        self.project_root = project_root or Path.cwd()
        self.llm_service = llm_service
        self.frames = frames or []
        self.semantic_search_service = semantic_search_service
        self.rate_limiter = rate_limiter

        # Initialize specific executors
        self.pre_analysis_executor = PreAnalysisExecutor(
            config=self.config,
            progress_callback=self._progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
            semantic_search_service=self.semantic_search_service,
            rate_limiter=self.rate_limiter,
        )
        self.analysis_executor = AnalysisExecutor(
            config=self.config,
            progress_callback=self._progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
            semantic_search_service=self.semantic_search_service,
            rate_limiter=self.rate_limiter,
        )
        self.triage_phase = TriagePhase(
            project_root=self.project_root,
            progress_callback=self._progress_callback,
            config=self.config.pre_analysis_config,  # Share config with pre_analysis or dedicated
            llm_service=self.llm_service,
        )
        self.classification_executor = ClassificationExecutor(
            config=self.config,
            progress_callback=self._progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
            # Pass all available frames to classification for dynamic selection
            frames=self.frames,
            available_frames=self.frames,
            semantic_search_service=self.semantic_search_service,
            rate_limiter=self.rate_limiter,
        )
        self.fortification_executor = FortificationExecutor(
            config=self.config,
            progress_callback=self._progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
            semantic_search_service=self.semantic_search_service,
            rate_limiter=self.rate_limiter,
        )
        self.cleaning_executor = CleaningExecutor(
            config=self.config,
            progress_callback=self._progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
            semantic_search_service=self.semantic_search_service,
            rate_limiter=self.rate_limiter,
        )

    @property
    def progress_callback(self) -> Callable | None:
        """Get progress callback."""
        return self._progress_callback

    @progress_callback.setter
    def progress_callback(self, value: Callable | None) -> None:
        """Set progress callback and propagate to sub-executors."""
        self._progress_callback = value
        self.pre_analysis_executor.progress_callback = value
        self.triage_phase.progress_callback = value
        self.analysis_executor.progress_callback = value
        self.classification_executor.progress_callback = value
        self.fortification_executor.progress_callback = value
        self.cleaning_executor.progress_callback = value

    async def execute_pre_analysis_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
    ) -> None:
        """Execute PRE-ANALYSIS phase."""
        await self.pre_analysis_executor.execute_async(context, code_files)

    async def execute_triage_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
    ) -> None:
        """Execute TRIAGE phase (adaptive hybrid triage)."""
        await self.triage_phase.execute_async(code_files, context)

    async def execute_analysis_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
    ) -> None:
        """Execute ANALYSIS phase."""
        await self.analysis_executor.execute_async(context, code_files)

    async def execute_classification_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
    ) -> None:
        """Execute CLASSIFICATION phase."""
        await self.classification_executor.execute_async(context, code_files)

    async def execute_fortification_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
    ) -> None:
        """Execute FORTIFICATION phase."""
        await self.fortification_executor.execute_async(context, code_files)

    async def execute_cleaning_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
    ) -> None:
        """Execute CLEANING phase."""
        await self.cleaning_executor.execute_async(context, code_files)
