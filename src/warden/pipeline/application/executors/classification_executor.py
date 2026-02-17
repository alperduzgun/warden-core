"""
Classification Phase Executor.
"""

import time
import traceback
from pathlib import Path
from typing import Any

from warden.pipeline.application.executors.base_phase_executor import BasePhaseExecutor
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile, ValidationFrame

logger = get_logger(__name__)


class ClassificationExecutor(BasePhaseExecutor):
    """Executor for the CLASSIFICATION phase."""

    def __init__(
        self,
        config: PipelineContext = None,
        progress_callback: callable = None,
        project_root: Path = None,
        llm_service: Any = None,
        frames: list[ValidationFrame] = None,
        available_frames: list[ValidationFrame] = None,
        semantic_search_service: Any = None,
        rate_limiter: Any = None,
    ):
        super().__init__(config, progress_callback, project_root, llm_service, rate_limiter)
        self.frames = frames or []
        self.available_frames = available_frames or self.frames
        self.semantic_search_service = semantic_search_service

    async def execute_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
    ) -> None:
        """Execute CLASSIFICATION phase."""
        logger.info("executing_phase", phase="CLASSIFICATION", file_count=len(code_files))

        if self.progress_callback:
            start_time = time.perf_counter()
            self.progress_callback("phase_started", {"phase": "CLASSIFICATION", "phase_name": "CLASSIFICATION"})

        try:
            # Respect global use_llm flag and LLM service availability
            use_llm = getattr(self.config, "use_llm", True) and self.llm_service is not None

            # Get context from previous phases
            phase_context = context.get_context_for_phase("CLASSIFICATION")

            if use_llm:
                from warden.analysis.application.llm_phase_base import LLMPhaseConfig
                from warden.classification.application.llm_classification_phase import (
                    LLMClassificationPhase as ClassificationPhase,
                )

                phase = ClassificationPhase(
                    config=LLMPhaseConfig(
                        enabled=True,
                        fallback_to_rules=True,
                        tpm_limit=self.config.llm_config.get("tpm_limit", 1000)
                        if getattr(self.config, "llm_config", None)
                        else (getattr(self.config.llm, "tpm_limit", 1000) if hasattr(self.config, "llm") else 1000),
                        rpm_limit=self.config.llm_config.get("rpm_limit", 6)
                        if getattr(self.config, "llm_config", None)
                        else (getattr(self.config.llm, "rpm_limit", 6) if hasattr(self.config, "llm") else 6),
                    ),
                    llm_service=self.llm_service,
                    available_frames=self.available_frames,
                    context=phase_context,
                    semantic_search_service=self.semantic_search_service,
                    memory_manager=getattr(self.config, "memory_manager", None),
                    rate_limiter=self.rate_limiter,
                )
                logger.info("using_llm_classification_phase", available_frames=len(self.available_frames))
            else:
                from warden.classification.application.classification_phase import ClassificationPhase

                phase = ClassificationPhase(
                    config=getattr(self.config, "classification_config", {}),
                    context=phase_context,
                    available_frames=self.available_frames,
                    semantic_search_service=self.semantic_search_service,
                )

            # Optimization: Filter out unchanged files to save LLM tokens/Validation time
            files_to_classify = []
            file_contexts = getattr(context, "file_contexts", {})

            for cf in code_files:
                f_info = file_contexts.get(cf.path)
                # If no context info or not marked unchanged, we classify it
                if not f_info or not getattr(f_info, "is_unchanged", False):
                    files_to_classify.append(cf)

            # BATCH 1: Fix fragile locals() check - use explicit variable
            from warden.classification.application.classification_phase import ClassificationResult

            result: ClassificationResult | None = None

            if not files_to_classify:
                logger.info("classification_phase_skipped_optimization", reason="all_files_unchanged")
                # No files to classify - use all available frames
                # FrameExecutor will skip execution on unchanged files
                result = ClassificationResult(
                    selected_frames=[f.frame_id for f in self.available_frames],
                    suppression_rules=[],
                    reasoning="Classification skipped (No changes detected)",
                )
                logger.debug(
                    "classification_default_all_frames",
                    frame_count=len(self.available_frames),
                )
            else:
                if len(files_to_classify) < len(code_files):
                    logger.info(
                        "classification_phase_optimizing", total=len(code_files), classifying=len(files_to_classify)
                    )
                result = await phase.execute_async(files_to_classify)

            # Validate result exists (should always be set by above branches)
            if result is None:
                logger.warning(
                    "classification_result_none",
                    reason="unexpected_branch",
                    action="using_all_frames",
                )
                result = ClassificationResult(
                    selected_frames=[f.frame_id for f in self.available_frames],
                    suppression_rules=[],
                    reasoning="Classification fallback (Unexpected None result)",
                )

            # Store results in context
            context.selected_frames = result.selected_frames
            context.suppression_rules = result.suppression_rules
            context.frame_priorities = result.frame_priorities
            context.classification_reasoning = result.reasoning
            context.learned_patterns = result.learned_patterns
            context.advisories = getattr(result, "advisories", [])

            # Adaptive frame selection based on context (Tier 2: Context-Awareness)
            if hasattr(context, "findings") and context.findings:
                # Refine frame selection based on prior findings
                selected_frames_refined = self._refine_frame_selection(context, result.selected_frames)

                if selected_frames_refined != result.selected_frames:
                    logger.info(
                        "adaptive_frame_selection",
                        original_count=len(result.selected_frames),
                        refined_count=len(selected_frames_refined),
                        reason="context_aware_refinement",
                    )
                    context.selected_frames = selected_frames_refined

            # Add phase result
            context.add_phase_result(
                "CLASSIFICATION",
                {
                    "selected_frames": result.selected_frames,
                    "suppression_rules_count": len(result.suppression_rules),
                    "reasoning": result.reasoning,
                },
            )

            logger.info(
                "phase_completed",
                phase="CLASSIFICATION",
                selected_frames=result.selected_frames,
            )

        except RuntimeError as e:
            logger.error("phase_failed", phase="CLASSIFICATION", error=str(e), tb=traceback.format_exc())
            context.errors.append(f"CLASSIFICATION failed: {e!s}")
            raise e
        except Exception as e:
            logger.error("phase_failed", phase="CLASSIFICATION", error=str(e), tb=traceback.format_exc())
            context.errors.append(f"CLASSIFICATION failed: {e!s}")

            # FALLBACK: Use all configured frames if classification fails
            logger.warning("classification_failed_using_all_frames")
            # This will be handled by frame executor

        if self.progress_callback:
            duration = time.perf_counter() - start_time
            classification_data = {"phase": "CLASSIFICATION", "phase_name": "CLASSIFICATION", "duration": duration}
            if hasattr(context, "classification_reasoning") and context.classification_reasoning:
                classification_data["llm_used"] = True
                classification_data["llm_reasoning"] = context.classification_reasoning[:200]
                classification_data["selected_frames"] = (
                    context.selected_frames if hasattr(context, "selected_frames") else []
                )
            self.progress_callback("phase_completed", classification_data)

    def _refine_frame_selection(
        self,
        context: PipelineContext,
        selected_frames: list[str],
    ) -> list[str]:
        """
        Refine frame selection based on context (Tier 2: Adaptive Frame Selection).

        Args:
            context: Pipeline context with findings and learned patterns
            selected_frames: Originally selected frames from classification

        Returns:
            Refined list of frame IDs
        """
        if not selected_frames:
            return selected_frames

        findings = context.findings
        learned_patterns = context.learned_patterns

        # Analyze findings to identify patterns
        has_sql_issues = any(
            "sql" in str(f.get("message", "") if isinstance(f, dict) else getattr(f, "message", "")).lower()
            for f in findings
        )

        any(
            "auth" in str(f.get("message", "") if isinstance(f, dict) else getattr(f, "message", "")).lower()
            or "password" in str(f.get("message", "") if isinstance(f, dict) else getattr(f, "message", "")).lower()
            for f in findings
        )

        has_xss_issues = any(
            "xss" in str(f.get("message", "") if isinstance(f, dict) else getattr(f, "message", "")).lower()
            or "injection" in str(f.get("message", "") if isinstance(f, dict) else getattr(f, "message", "")).lower()
            for f in findings
        )

        # Refine based on patterns
        refined_frames = list(selected_frames)

        # If SQL issues found, prioritize security frame
        if has_sql_issues and "security" not in refined_frames:
            refined_frames.append("security")
            logger.debug("adaptive_selection_added_frame", frame="security", reason="sql_issues_detected")

        # If no XSS issues and no web patterns, consider skipping certain frames
        # (This is conservative - we keep frames unless we're sure)
        if not has_xss_issues and not learned_patterns:
            # Could add logic to skip certain frames, but be careful not to miss issues
            pass

        # Remove duplicates and return
        return list(set(refined_frames))
