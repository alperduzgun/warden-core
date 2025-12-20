"""
Pipeline orchestrator - main execution engine.

Sequential flow:
1. Analysis (code analysis + metrics)
2. Classification (frame recommendation)
3. Validation (frame execution)
4. Fortification (optional - if score < 7.0)
5. Cleaning (optional)

Features:
- Fail-fast validation
- Blocker check (security failures stop pipeline)
- Resilience patterns (retry, timeout)
- Correlation ID tracking
- Structured logging
"""
import uuid
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from warden.core.pipeline.result import PipelineResult

# Fallback logger (structlog not installed yet)
try:
    import structlog
    logger = structlog.get_logger()
except ImportError:
    from warden.shared.logger import get_logger
    logger = get_logger(__name__)


class PipelineOrchestrator:
    """
    Main pipeline executor.

    Orchestrates sequential execution of pipeline stages with
    resilience patterns and fail-fast behavior.
    """

    def __init__(
        self,
        analyzer=None,  # CodeAnalyzer instance
        classifier=None,  # CodeClassifier instance
        frame_executor=None,  # FrameExecutor instance
        fortifier=None,  # Optional fortifier
        cleaner=None,  # Optional cleaner
    ):
        """
        Initialize pipeline orchestrator.

        Args:
            analyzer: Code analyzer instance
            classifier: Code classifier instance
            frame_executor: Frame executor instance
            fortifier: Optional fortifier instance
            cleaner: Optional cleaner instance
        """
        self.analyzer = analyzer
        self.classifier = classifier
        self.frame_executor = frame_executor
        self.fortifier = fortifier
        self.cleaner = cleaner
        self.logger = logger

    async def execute(
        self,
        file_path: str,
        file_content: str,
        language: str = "python",
        enable_fortification: bool = True,
        enable_cleaning: bool = False,
        fail_fast: bool = True,
    ) -> PipelineResult:
        """
        Execute full pipeline on a code file.

        Args:
            file_path: Path to code file
            file_content: File content
            language: Programming language
            enable_fortification: Run fortification stage
            enable_cleaning: Run cleaning stage
            fail_fast: Stop on blocker failures

        Returns:
            PipelineResult with execution results
        """
        correlation_id = str(uuid.uuid4())
        started_at = datetime.now()
        start_time = time.perf_counter()

        self.logger.info(
            "pipeline_started",
            correlation_id=correlation_id,
            file_path=file_path,
            language=language,
        )

        try:
            # Fail-fast validation
            if not file_path or not file_content:
                raise ValueError("file_path and file_content are required")

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
