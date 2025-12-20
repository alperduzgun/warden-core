"""
Pipeline orchestrator - main execution engine.

Sequential flow:
1. Analysis (code analysis + metrics)
2. Classification (frame recommendation)
3. Validation (frame execution)
4. Fortification (optional - if score < 7.0)
5. Cleaning (optional)

Features:
- YAML config-driven execution
- Fail-fast validation (from config)
- Blocker check (security failures stop pipeline)
- Priority-based frame execution
- Parallel/Sequential execution modes
- Resilience patterns (retry, timeout)
- Correlation ID tracking
- Structured logging
"""
import uuid
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

from warden.core.pipeline.result import PipelineResult
from warden.core.pipeline.factory import create_frame_executor_from_config
from warden.models.pipeline_config import PipelineConfig

# Fallback logger (structlog not installed yet)
try:
    import structlog
    logger = structlog.get_logger()
except ImportError:
    from warden.shared.logger import get_logger
    logger = get_logger(__name__)


class PipelineOrchestrator:
    """
    Main pipeline executor - YAML config-driven.

    Orchestrates sequential execution of pipeline stages with
    resilience patterns and config-based behavior.
    """

    def __init__(
        self,
        config: Optional[PipelineConfig] = None,
        analyzer=None,  # CodeAnalyzer instance
        classifier=None,  # CodeClassifier instance
        frame_executor=None,  # FrameExecutor instance (will be created from config)
        fortifier=None,  # Optional fortifier
        cleaner=None,  # Optional cleaner
    ):
        """
        Initialize pipeline orchestrator.

        Args:
            config: Pipeline configuration (YAML loaded)
            analyzer: Code analyzer instance (optional, auto-created if None)
            classifier: Code classifier instance (optional, auto-created if None)
            frame_executor: Frame executor (will be created from config if None)
            fortifier: Optional fortifier instance
            cleaner: Optional cleaner instance
        """
        self.config = config

        # Auto-create analyzer/classifier if not provided
        if analyzer is None:
            from warden.core.analysis.analyzer import CodeAnalyzer

            # Try to create LLM factory from config
            llm_factory = None
            use_llm = False

            if config and hasattr(config.settings, 'enable_llm'):
                use_llm = config.settings.enable_llm

            if use_llm:
                try:
                    from warden.llm.factory import LlmFactory
                    llm_factory = LlmFactory()
                    self.logger.info(
                        "llm_factory_created",
                        provider=config.settings.llm_provider if hasattr(config.settings, 'llm_provider') else "default"
                    )
                except Exception as e:
                    self.logger.warning(
                        "llm_factory_creation_failed",
                        error=str(e),
                        fallback="ast_only"
                    )

            analyzer = CodeAnalyzer(llm_factory=llm_factory, use_llm=use_llm)

        if classifier is None:
            from warden.core.analysis.classifier import CodeClassifier
            classifier = CodeClassifier()

        self.analyzer = analyzer
        self.classifier = classifier
        self.fortifier = fortifier
        self.cleaner = cleaner
        self.logger = logger

        # Create FrameExecutor from config
        if frame_executor is None and config is not None:
            frame_executor = create_frame_executor_from_config(config)

        self.frame_executor = frame_executor

    async def execute(
        self,
        file_path: str,
        file_content: str,
        language: str = "python",
        enable_fortification: bool = True,
        enable_cleaning: bool = False,
        fail_fast: Optional[bool] = None,
    ) -> PipelineResult:
        """
        Execute full pipeline on a code file.

        Args:
            file_path: Path to code file
            file_content: File content
            language: Programming language
            enable_fortification: Run fortification stage
            enable_cleaning: Run cleaning stage
            fail_fast: Stop on blocker failures (uses config default if None)

        Returns:
            PipelineResult with execution results
        """
        correlation_id = str(uuid.uuid4())
        started_at = datetime.now()
        start_time = time.perf_counter()

        # Get config settings (or use defaults)
        if fail_fast is None:
            fail_fast = self.config.settings.fail_fast if self.config else True

        parallel = self.config.settings.parallel if self.config else False

        self.logger.info(
            "pipeline_started",
            correlation_id=correlation_id,
            file_path=file_path,
            language=language,
        )

        try:
            # Fail-fast validation
            if not file_path:
                raise ValueError("file_path is required")

            # Allow empty content (e.g., __init__.py files)
            if file_content is None:
                raise ValueError("file_content cannot be None")

            path_obj = Path(file_path)
            if not path_obj.suffix:
                raise ValueError(f"Invalid file path: {file_path}")

            # Stage 1: Analysis
            self.logger.info(
                "stage_started",
                correlation_id=correlation_id,
                stage="analysis",
            )

            analysis_result = await self._execute_analysis(
                file_path, file_content, language, correlation_id
            )

            if not analysis_result:
                return self._create_error_result(
                    correlation_id,
                    started_at,
                    start_time,
                    "Analysis stage failed",
                    failed_stage="analysis",
                )

            # Stage 2: Classification
            self.logger.info(
                "stage_started",
                correlation_id=correlation_id,
                stage="classification",
            )

            classification_result = await self._execute_classification(
                file_path, file_content, language, correlation_id
            )

            if not classification_result:
                return self._create_error_result(
                    correlation_id,
                    started_at,
                    start_time,
                    "Classification stage failed",
                    failed_stage="classification",
                )

            # Stage 3: Validation
            self.logger.info(
                "stage_started",
                correlation_id=correlation_id,
                stage="validation",
            )

            validation_summary = await self._execute_validation(
                file_path,
                file_content,
                language,
                classification_result,
                correlation_id,
                parallel,
            )

            if not validation_summary:
                return self._create_error_result(
                    correlation_id,
                    started_at,
                    start_time,
                    "Validation stage failed",
                    failed_stage="validation",
                )

            # Check for blocker failures
            blocker_failures = validation_summary.get("blockerFailures", [])
            if fail_fast and blocker_failures:
                completed_at = datetime.now()
                duration_ms = (time.perf_counter() - start_time) * 1000

                self.logger.warning(
                    "pipeline_stopped_blocker",
                    correlation_id=correlation_id,
                    blocker_count=len(blocker_failures),
                    duration_ms=duration_ms,
                )

                return PipelineResult(
                    success=False,
                    correlation_id=correlation_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    analysis_result=analysis_result,
                    classification_result=classification_result,
                    validation_summary=validation_summary,
                    message="Pipeline stopped - blocker failures detected",
                    blocker_failures=blocker_failures,
                    failed_stage="validation",
                )

            # Stage 4: Fortification (optional)
            fortification_result = None
            if enable_fortification and self.fortifier:
                score = analysis_result.get("score", 10.0)
                if score < 7.0:
                    self.logger.info(
                        "stage_started",
                        correlation_id=correlation_id,
                        stage="fortification",
                        score=score,
                    )

                    fortification_result = await self._execute_fortification(
                        file_path, file_content, language, correlation_id
                    )

            # Stage 5: Cleaning (optional)
            cleaning_result = None
            if enable_cleaning and self.cleaner:
                self.logger.info(
                    "stage_started",
                    correlation_id=correlation_id,
                    stage="cleaning",
                )

                cleaning_result = await self._execute_cleaning(
                    file_path, file_content, language, correlation_id
                )

            # Success
            completed_at = datetime.now()
            duration_ms = (time.perf_counter() - start_time) * 1000

            self.logger.info(
                "pipeline_completed",
                correlation_id=correlation_id,
                duration_ms=duration_ms,
                stages_completed=5
                if (fortification_result and cleaning_result)
                else 3,
            )

            return PipelineResult(
                success=True,
                correlation_id=correlation_id,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                analysis_result=analysis_result,
                classification_result=classification_result,
                validation_summary=validation_summary,
                fortification_result=fortification_result,
                cleaning_result=cleaning_result,
                message="Pipeline completed successfully",
            )

        except Exception as ex:
            completed_at = datetime.now()
            duration_ms = (time.perf_counter() - start_time) * 1000

            self.logger.error(
                "pipeline_failed",
                correlation_id=correlation_id,
                error=str(ex),
                error_type=type(ex).__name__,
                duration_ms=duration_ms,
            )

            return PipelineResult(
                success=False,
                correlation_id=correlation_id,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                message=f"Pipeline failed: {str(ex)}",
                errors=[str(ex)],
            )

    async def _execute_analysis(
        self,
        file_path: str,
        file_content: str,
        language: str,
        correlation_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Execute analysis stage."""
        if not self.analyzer:
            self.logger.warning(
                "analyzer_not_configured",
                correlation_id=correlation_id,
            )
            return {"score": 5.0, "issues": [], "metrics": {}}

        try:
            result = await self.analyzer.analyze(file_path, file_content, language)
            return result
        except Exception as ex:
            self.logger.error(
                "analysis_failed",
                correlation_id=correlation_id,
                error=str(ex),
            )
            return None

    async def _execute_classification(
        self,
        file_path: str,
        file_content: str,
        language: str,
        correlation_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Execute classification stage."""
        if not self.classifier:
            self.logger.warning(
                "classifier_not_configured",
                correlation_id=correlation_id,
            )
            # Default: recommend all frames
            return {
                "characteristics": {
                    "hasAsync": False,
                    "hasUserInput": False,
                    "hasExternalCalls": False,
                },
                "recommendedFrames": ["security", "fuzz", "property"],
            }

        try:
            result = await self.classifier.classify(file_path, file_content, language)
            return result
        except Exception as ex:
            self.logger.error(
                "classification_failed",
                correlation_id=correlation_id,
                error=str(ex),
            )
            return None

    async def _execute_validation(
        self,
        file_path: str,
        file_content: str,
        language: str,
        classification_result: Dict[str, Any],
        correlation_id: str,
        parallel: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Execute validation stage."""
        if not self.frame_executor:
            self.logger.warning(
                "frame_executor_not_configured",
                correlation_id=correlation_id,
            )
            return {
                "totalFrames": 0,
                "passedFrames": 0,
                "failedFrames": 0,
                "blockerFailures": [],
            }

        try:
            recommended_frames = classification_result.get("recommendedFrames", [])
            characteristics = classification_result.get("characteristics", {})

            result = await self.frame_executor.execute(
                file_path=file_path,
                file_content=file_content,
                language=language,
                recommended_frames=recommended_frames,
                characteristics=characteristics,
                correlation_id=correlation_id,
                parallel=parallel,  # Use config setting
            )
            return result
        except Exception as ex:
            self.logger.error(
                "validation_failed",
                correlation_id=correlation_id,
                error=str(ex),
            )
            return None

    async def _execute_fortification(
        self,
        file_path: str,
        file_content: str,
        language: str,
        correlation_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Execute fortification stage (optional)."""
        try:
            result = await self.fortifier.fortify(file_path, file_content, language)
            return result
        except Exception as ex:
            self.logger.error(
                "fortification_failed",
                correlation_id=correlation_id,
                error=str(ex),
            )
            return None

    async def _execute_cleaning(
        self,
        file_path: str,
        file_content: str,
        language: str,
        correlation_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Execute cleaning stage (optional)."""
        try:
            result = await self.cleaner.clean(file_path, file_content, language)
            return result
        except Exception as ex:
            self.logger.error(
                "cleaning_failed",
                correlation_id=correlation_id,
                error=str(ex),
            )
            return None

    def _create_error_result(
        self,
        correlation_id: str,
        started_at: datetime,
        start_time: float,
        message: str,
        failed_stage: str = None,
    ) -> PipelineResult:
        """Create error result."""
        completed_at = datetime.now()
        duration_ms = (time.perf_counter() - start_time) * 1000

        return PipelineResult(
            success=False,
            correlation_id=correlation_id,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            message=message,
            failed_stage=failed_stage,
            errors=[message],
        )
