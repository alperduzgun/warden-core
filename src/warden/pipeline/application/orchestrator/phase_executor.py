"""
Phase executor for individual pipeline phases.

Refactored to delegate to specific phase executors.
"""

from pathlib import Path
from typing import Any, List, Optional, Callable

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.pipeline.domain.models import PipelineConfig
from warden.validation.domain.frame import CodeFile, ValidationFrame
from warden.shared.infrastructure.logging import get_logger

# Import specific executors
from warden.pipeline.application.executors.pre_analysis_executor import PreAnalysisExecutor
from warden.pipeline.application.executors.analysis_executor import AnalysisExecutor
from warden.pipeline.application.executors.classification_executor import ClassificationExecutor
from warden.pipeline.application.executors.fortification_executor import FortificationExecutor
from warden.pipeline.application.executors.cleaning_executor import CleaningExecutor

logger = get_logger(__name__)


class PhaseExecutor:
    """
    Executes individual pipeline phases.
    
    Acts as a facade delegating to specific phase executors.
    """

    def __init__(
        self,
        config: Optional[PipelineConfig] = None,
        progress_callback: Optional[Callable] = None,
        project_root: Optional[Path] = None,
        llm_service: Optional[Any] = None,
        frames: Optional[List[ValidationFrame]] = None,
        semantic_search_service: Optional[Any] = None,
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

        # Initialize specific executors
        self.pre_analysis_executor = PreAnalysisExecutor(
            config=self.config,
            progress_callback=self._progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
            semantic_search_service=self.semantic_search_service
        )
        self.analysis_executor = AnalysisExecutor(
            config=self.config,
            progress_callback=self._progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
            semantic_search_service=self.semantic_search_service
        )
        self.classification_executor = ClassificationExecutor(
            config=self.config,
            progress_callback=self._progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
            # Pass all available frames to classification for dynamic selection
            frames=self.frames,
            available_frames=self.frames,
            semantic_search_service=self.semantic_search_service
        )
        self.fortification_executor = FortificationExecutor(
            config=self.config,
            progress_callback=self._progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
            semantic_search_service=self.semantic_search_service
        )
        self.cleaning_executor = CleaningExecutor(
            config=self.config,
            progress_callback=self._progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
            semantic_search_service=self.semantic_search_service
        )
    
    @property
    def progress_callback(self) -> Optional[Callable]:
        """Get progress callback."""
        return self._progress_callback

    @progress_callback.setter
    def progress_callback(self, value: Optional[Callable]) -> None:
        """Set progress callback and propagate to sub-executors."""
        self._progress_callback = value
        self.pre_analysis_executor.progress_callback = value
        self.analysis_executor.progress_callback = value
        self.classification_executor.progress_callback = value
        self.fortification_executor.progress_callback = value
        self.cleaning_executor.progress_callback = value

    async def execute_pre_analysis_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute PRE-ANALYSIS phase."""
        await self.pre_analysis_executor.execute_async(context, code_files)

    async def execute_analysis_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute ANALYSIS phase."""
        await self.analysis_executor.execute_async(context, code_files)

    async def execute_classification_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute CLASSIFICATION phase."""
        await self.classification_executor.execute_async(context, code_files)

    async def execute_fortification_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute FORTIFICATION phase."""
        await self.fortification_executor.execute_async(context, code_files)

    async def execute_cleaning_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute CLEANING phase."""
        await self.cleaning_executor.execute_async(context, code_files)