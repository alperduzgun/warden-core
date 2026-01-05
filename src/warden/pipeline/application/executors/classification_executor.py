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
        available_frames: List[ValidationFrame] = None,
        semantic_search_service: Any = None,
    ):
        super().__init__(config, progress_callback, project_root, llm_service)
        self.frames = frames or []
        self.available_frames = available_frames or self.frames
        self.semantic_search_service = semantic_search_service

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
                    available_frames=self.available_frames,
                    context=phase_context,
                    semantic_search_service=self.semantic_search_service
                )
                logger.info("using_llm_classification_phase", available_frames=len(self.available_frames))
            else:
                from warden.classification.application.classification_phase import ClassificationPhase
                phase = ClassificationPhase(
                    config=getattr(self.config, 'classification_config', {}),
                    context=phase_context,
                    available_frames=self.available_frames,
                    semantic_search_service=self.semantic_search_service
                )

            # Optimization: Filter out unchanged files to save LLM tokens/Validation time
            files_to_classify = []
            file_contexts = getattr(context, 'file_contexts', {})
            
            for cf in code_files:
                f_info = file_contexts.get(cf.path)
                # If no context info or not marked unchanged, we classify it
                if not f_info or not getattr(f_info, 'is_unchanged', False):
                    files_to_classify.append(cf)
            
            if not files_to_classify:
                 logger.info("classification_phase_skipped_optimization", reason="all_files_unchanged")
                 # Reuse previous classification if available (complex, for now just skip)
                 # In a real persistence scenario, we would reload 'selected_frames' from memory here.
                 # For now, we assume if nothing changed, we don't need to re-classify or re-select frames 
                 # because specific frame execution will also be skipped.
                 
                 # However, we must ensure 'selected_frames' is at least populated if we skip.
                 # If we skip classification, we might default to ALL enabled frames or previous state.
                 # Strategy: If all files unchanged, we rely on FrameExecutor's skip logic, 
                 # but we still need a list of frames to *attempt* to run.
                 
                 # Create a dummy result with previous selected frames or default
                 from warden.classification.application.classification_phase import ClassificationResult
                 
                 # Try to restore from memory (Phase 0 should have populated this if we had a persistent store for it)
                 # Since we don't have per-run persistence for classification yet, we'll assume defaults
                 # BUT: If we skip classification, we might miss new rules. 
                 # RISK: If we skip classification, context.selected_frames will be empty?
                 
                 # Better approach: If files unchanged, use Memory to get *previous* classification?
                 # Current MemoryManager implementation doesn't store 'last_run_classification'.
                 
                 # Compromise: For files that are unchanged, we TRUST that previous classification holds for them.
                 # But we need to output a result.
                 
                 # Minimal fallback: Select all configured frames (safest)
                 # The FrameExecutor will then skip individual files.
                 result = ClassificationResult(
                     selected_frames=[], # Will trigger "all frames" fallback in logic below?
                     suppression_rules=[],
                     reasoning="Classification skipped (No changes detected)"
                 )
                 # Wait, if selected_frames is empty, caller logic might warn.
                 # Let's check `result.selected_frames` usage below.
                 pass
            else:
                if len(files_to_classify) < len(code_files):
                    logger.info("classification_phase_optimizing", total=len(code_files), classifying=len(files_to_classify))
                result = await phase.execute_async(files_to_classify)
            
            # If we skipped (result not assigned in if-block), we need to handle it.
            # Actually, `ClassificationPhase` might return empty if input is empty?
            if 'result' not in locals():
                 # We skipped. We need to populate context.selected_frames so FrameExecutor knows what to do.
                 # If we don't select frames, FrameExecutor might run nothing or everything.
                 # Let's inspect context to see if we have previous run data? No.
                 
                 # SAFE FIX: If we skip classification, we simply return "Use All Frames" 
                 # because FrameExecutor will skip the *execution* on unchanged files anyway.
                 # This avoids cost of LLM Classification.
                 from warden.classification.application.classification_phase import ClassificationResult
                 result = ClassificationResult(
                     selected_frames=[], # Empty list often implies "default/all" or "none" depending on logic
                     suppression_rules=[],
                     reasoning="Classification skipped (No changes)"
                 )
                 # Actually, let's look at line 84: context.selected_frames = result.selected_frames
                 # If it's empty, FrameExecutor checks: `if not frames_to_execute` -> warning.
                 
                 # So we MUST provide frames.
                 # Let's use available_frames names
                 result.selected_frames = [f.frame_id for f in self.available_frames]

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
