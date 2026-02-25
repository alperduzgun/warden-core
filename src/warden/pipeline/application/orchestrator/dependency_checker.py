"""
Dependency checking for validation frames.

Handles frame dependency validation and context attribute checking.
"""

from typing import Any

from warden.pipeline.domain.models import FrameResult
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import ValidationFrame


class DependencyChecker:
    """Handles frame dependency validation."""

    @staticmethod
    def check_frame_dependencies(
        context: PipelineContext,
        frame: ValidationFrame,
    ) -> FrameResult | None:
        """
        Check if frame dependencies are satisfied.

        Returns FrameResult with status='skipped' if dependencies not met,
        otherwise returns None to continue execution.

        Checks:
        1. requires_frames: Required frames must have executed
        2. requires_config: Required config paths must be set
        3. requires_context: Required context attributes must exist
        """
        required_frames = getattr(frame, "requires_frames", [])
        for req_frame_id in required_frames:
            if req_frame_id not in context.frame_results:
                return FrameResult(
                    frame_id=frame.frame_id,
                    frame_name=frame.name,
                    status="skipped",
                    duration=0.0,
                    issues_found=0,
                    is_blocker=False,
                    findings=[],
                    metadata={
                        "skip_reason": f"Required frame '{req_frame_id}' has not been executed",
                        "dependency_type": "frame",
                        "missing_dependency": req_frame_id,
                    },
                )

        required_configs = getattr(frame, "requires_config", [])
        for config_path in required_configs:
            if not DependencyChecker._config_path_exists(frame.config, config_path):
                return FrameResult(
                    frame_id=frame.frame_id,
                    frame_name=frame.name,
                    status="skipped",
                    duration=0.0,
                    issues_found=0,
                    is_blocker=False,
                    findings=[],
                    metadata={
                        "skip_reason": f"Required config '{config_path}' is not set",
                        "dependency_type": "config",
                        "missing_dependency": config_path,
                        "help": f"Add '{config_path}' to .warden/config.yaml",
                    },
                )

        required_context = getattr(frame, "requires_context", [])
        for ctx_attr in required_context:
            if not DependencyChecker._context_attr_exists(context, ctx_attr):
                return FrameResult(
                    frame_id=frame.frame_id,
                    frame_name=frame.name,
                    status="skipped",
                    duration=0.0,
                    issues_found=0,
                    is_blocker=False,
                    findings=[],
                    metadata={
                        "skip_reason": f"Required context '{ctx_attr}' is not available",
                        "dependency_type": "context",
                        "missing_dependency": ctx_attr,
                        "help": "Ensure prerequisite phases/frames have run",
                    },
                )

        return None

    @staticmethod
    def _config_path_exists(config: dict[str, Any] | None, path: str) -> bool:
        """
        Check if a config path exists and has a value.

        Args:
            config: Frame configuration dictionary
            path: Dot-separated path (e.g., "spec.platforms")

        Returns:
            True if path exists and has a non-empty value
        """
        if not config:
            return False

        parts = path.split(".")
        current = config

        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]

        if current is None:
            return False
        return not (isinstance(current, (list, dict, str)) and len(current) == 0)

    @staticmethod
    def _context_attr_exists(context: PipelineContext, attr: str) -> bool:
        """
        Check if a context attribute exists and has a value.

        Args:
            context: Pipeline context
            attr: Attribute name (e.g., "project_context", "service_abstractions")

        Returns:
            True if attribute exists and is not None/empty
        """
        parts = attr.split(".")
        current: Any = context

        for part in parts:
            if hasattr(current, part):
                current = getattr(current, part)
            elif isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return False

        return current is not None
