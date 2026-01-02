"""
Classification Phase Executor.
"""

import time
from typing import List, Any
from pathlib import Path

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import CodeFile, ValidationFrame
from warden.shared.infrastructure.logging import get_logger
from warden.pipeline.application.executors.base_phase_executor import BasePhaseExecutor

logger = get_logger(__name__)


class ClassificationExecutor(BasePhaseExecutor):
    """Executor for the CLASSIFICATION phase."""

    def __init__(
        self,
        config: PipelineContext = None,
        progress_callback: callable = None,
        project_root: Path = None,
        llm_service: Any = None,
        frames: List[ValidationFrame] = None,
    ):
        super().__init__(config, progress_callback, project_root, llm_service)
        self.frames = frames or []

    async def execute_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute CLASSIFICATION phase."""
        logger.info("executing_phase", phase="CLASSIFICATION")

        if self.progress_callback:
            start_time = time.perf_counter()
            self.progress_callback("phase_started", {
                "phase": "CLASSIFICATION",
                "phase_name": "CLASSIFICATION"
            })

        try:
            # Use LLM version if LLM service is available
            use_llm = self.llm_service is not None

            # Get context from previous phases
            phase_context = context.get_context_for_phase("CLASSIFICATION")

            if use_llm:
                from warden.classification.application.llm_classification_phase import LLMClassificationPhase as ClassificationPhase
                from warden.analysis.application.llm_phase_base import LLMPhaseConfig

                phase = ClassificationPhase(
                    config=LLMPhaseConfig(enabled=True, fallback_to_rules=True),
                    llm_service=self.llm_service,
                    available_frames=self.frames
                )
                logger.info("using_llm_classification_phase", available_frames=len(self.frames))
            else:
                from warden.classification.application.classification_phase import ClassificationPhase
                phase = ClassificationPhase(
                    config=getattr(self.config, 'classification_config', {}),
                    context=phase_context,
                    available_frames=self.frames
                )

            result = await phase.execute_async(code_files)

            # Store results in context
            context.selected_frames = result.selected_frames
            context.suppression_rules = result.suppression_rules
            context.frame_priorities = result.frame_priorities
            context.classification_reasoning = result.reasoning
            context.learned_patterns = result.learned_patterns

            # Add phase result
            context.add_phase_result("CLASSIFICATION", {
                "selected_frames": result.selected_frames,
                "suppression_rules_count": len(result.suppression_rules),
                "reasoning": result.reasoning,
            })

            logger.info(
                "phase_completed",
                phase="CLASSIFICATION",
                selected_frames=result.selected_frames,
            )

        except Exception as e:
            logger.error("phase_failed", phase="CLASSIFICATION", error=str(e))
            context.errors.append(f"CLASSIFICATION failed: {str(e)}")

            # FALLBACK: Use all configured frames if classification fails
            logger.warning("classification_failed_using_all_frames")
            # This will be handled by frame executor

        if self.progress_callback:
            duration = time.perf_counter() - start_time
            classification_data = {
                "phase": "CLASSIFICATION",
                "phase_name": "CLASSIFICATION",
                "duration": duration
            }
            if hasattr(context, 'classification_reasoning') and context.classification_reasoning:
                classification_data["llm_used"] = True
                classification_data["llm_reasoning"] = context.classification_reasoning[:200]
                classification_data["selected_frames"] = context.selected_frames if hasattr(context, 'selected_frames') else []
            self.progress_callback("phase_completed", classification_data)
