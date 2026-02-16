"""
File filtering and triage routing for validation frames.

Handles file context filtering and triage lane routing.
"""

from typing import Any

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile, ValidationFrame

logger = get_logger(__name__)


class FileFilter:
    """Handles file filtering based on context and triage decisions."""

    @staticmethod
    def filter_by_context(
        code_files: list[CodeFile],
        file_contexts: dict[str, Any],
        include_test_files: bool = False,
    ) -> list[CodeFile]:
        """Filter files based on PRE-ANALYSIS context."""
        filtered = []
        for code_file in code_files:
            file_context_info = file_contexts.get(code_file.path)

            if not file_context_info:
                filtered.append(code_file)
                continue

            if hasattr(file_context_info, "context"):
                context_type = (
                    file_context_info.context.value
                    if hasattr(file_context_info.context, "value")
                    else str(file_context_info.context)
                )
            else:
                context_type = "PRODUCTION"

            if context_type in ["TEST", "EXAMPLE", "DOCUMENTATION"] and not include_test_files:
                logger.info("skipping_non_production_file", file=code_file.path, context=context_type)
                continue

            filtered.append(code_file)

        return filtered

    @staticmethod
    def apply_triage_routing(
        context: PipelineContext, frame: ValidationFrame, code_files: list[CodeFile]
    ) -> list[CodeFile]:
        """
        Filter files based on Triage Lane and Frame cost.

        Logic:
        - Fast Lane: Skip expensive/LLM frames
        - Middle/Deep Lane: Execute everything
        """
        if not hasattr(context, "triage_decisions") or not context.triage_decisions:
            return code_files

        is_expensive = False

        if hasattr(frame, "config") and frame.config.get("use_llm") is True:
            is_expensive = True
        else:
            expensive_keywords = ["security", "complex", "architecture", "design", "refactor", "llm", "deep"]
            if any(k in frame.frame_id.lower() for k in expensive_keywords):
                is_expensive = True

        if not is_expensive:
            return code_files

        filtered = []
        skipped_count = 0

        for cf in code_files:
            decision_data = context.triage_decisions.get(cf.path)
            if not decision_data:
                filtered.append(cf)
                continue

            lane = decision_data.get("lane")

            if cf.metadata is None:
                cf.metadata = {}
            cf.metadata["triage_lane"] = lane

            if lane == "fast_lane":
                skipped_count += 1
                continue

            filtered.append(cf)

        if skipped_count > 0:
            logger.info("triage_routing_applied", frame=frame.frame_id, skipped=skipped_count, remaining=len(filtered))

        return filtered
