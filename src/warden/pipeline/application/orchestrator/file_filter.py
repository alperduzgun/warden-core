"""
File filtering and triage routing for validation frames.

Handles file context filtering and triage lane routing.
"""

from typing import Any

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile, ValidationFrame

logger = get_logger(__name__)

_LANE_ORDER: dict[str, int] = {
    "fast_lane": 0,
    "middle_lane": 1,
    "deep_lane": 2,
}


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
        Filter files based on triage lane and frame's declared minimum lane.

        Frames declare their minimum_triage_lane:
        - "fast_lane" (default): process all files
        - "middle_lane": skip FAST files
        - "deep_lane": skip FAST+MIDDLE files (future use)
        """
        if not hasattr(context, "triage_decisions") or not context.triage_decisions:
            return code_files

        min_lane = getattr(frame, "minimum_triage_lane", "fast_lane")
        min_order = _LANE_ORDER.get(str(min_lane), 0)

        if min_order == 0:
            return code_files  # frame accepts all lanes

        filtered = []
        skipped_count = 0

        for cf in code_files:
            decision_data = context.triage_decisions.get(cf.path)
            if not decision_data:
                filtered.append(cf)
                continue

            lane = decision_data.get("lane", "middle_lane")
            if cf.metadata is None:
                cf.metadata = {}
            cf.metadata["triage_lane"] = lane

            if _LANE_ORDER.get(str(lane), 1) < min_order:
                skipped_count += 1
                continue

            filtered.append(cf)

        if skipped_count:
            logger.info(
                "triage_routing_applied",
                frame=frame.frame_id,
                min_lane=min_lane,
                skipped=skipped_count,
                remaining=len(filtered),
            )

        return filtered
