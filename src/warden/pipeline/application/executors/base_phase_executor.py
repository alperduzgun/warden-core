"""
Base Phase Executor module.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from warden.pipeline.domain.models import PipelineConfig
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class BasePhaseExecutor:
    """Base class for individual phase executors."""

    def __init__(
        self,
        config: PipelineConfig | None = None,
        progress_callback: Callable | None = None,
        project_root: Path | None = None,
        llm_service: Any | None = None,
        semantic_search_service: Any | None = None,
        rate_limiter: Any | None = None,
    ):
        """
        Initialize base phase executor.

        Args:
            config: Pipeline configuration
            progress_callback: Optional callback for progress updates
            project_root: Root directory of the project
            llm_service: Optional LLM service for AI-powered phases
            rate_limiter: Optional RateLimiter instance
        """
        self.config = config or PipelineConfig()
        self.progress_callback = progress_callback
        self.project_root = project_root or Path.cwd()
        self.llm_service = llm_service
        self.semantic_search_service = semantic_search_service
        self.rate_limiter = rate_limiter
