"""
Base Phase Executor module.
"""

from pathlib import Path
from typing import Any, Optional, Callable

from warden.pipeline.domain.models import PipelineConfig
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class BasePhaseExecutor:
    """Base class for individual phase executors."""

    def __init__(
        self,
        config: Optional[PipelineConfig] = None,
        progress_callback: Optional[Callable] = None,
        project_root: Optional[Path] = None,
        llm_service: Optional[Any] = None,
        semantic_search_service: Optional[Any] = None,
    ):
        """
        Initialize base phase executor.

        Args:
            config: Pipeline configuration
            progress_callback: Optional callback for progress updates
            project_root: Root directory of the project
            llm_service: Optional LLM service for AI-powered phases
        """
        self.config = config or PipelineConfig()
        self.progress_callback = progress_callback
        self.project_root = project_root or Path.cwd()
        self.llm_service = llm_service
        self.semantic_search_service = semantic_search_service
