"""Build PipelineResult DTO from PipelineContext after pipeline execution."""

from datetime import datetime
from typing import Any

from warden.pipeline.domain.models import PipelineConfig, PipelineResult, ValidationPipeline
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.utils.finding_utils import get_finding_severity
from warden.validation.domain.frame import ValidationFrame


class PipelineResultBuilder:
    """Transforms PipelineContext into PipelineResult for CLI/reporting."""

    def __init__(
        self,
        config: PipelineConfig,
        frames: list[ValidationFrame],
    ):
        self.config = config
        self.frames = frames

    def build(
        self,
        context: PipelineContext,
        pipeline: ValidationPipeline,
        scan_id: str | None = None,
    ) -> PipelineResult:
        """Build PipelineResult from context for compatibility."""
        frame_results = []

        # Convert context frame results to FrameResult objects
        if hasattr(context, "frame_results") and context.frame_results:
            for _frame_id, frame_data in context.frame_results.items():
                result = frame_data.get("result")
                if result:
                    frame_results.append(result)

        # Collect findings from context or frame results
        findings = self._collect_findings(context, frame_results)

        # Count by severity
        critical_findings = sum(1 for f in findings if get_finding_severity(f) == "critical")
        high_findings = sum(1 for f in findings if get_finding_severity(f) == "high")
        medium_findings = sum(1 for f in findings if get_finding_severity(f) == "medium")
        low_findings = sum(1 for f in findings if get_finding_severity(f) == "low")
        manual_review_count = sum(1 for f in findings if self._is_review_required(f))
        total_findings = len(findings)

        # Calculate quality score: findings penalty applied to analysis base score.
        # Analysis phase already produces an objective base score from linter metrics
        # when LLM is unavailable, so we only guard against truly invalid values here.
        from warden.shared.utils.quality_calculator import calculate_base_score, calculate_quality_score

        base_score = getattr(context, "quality_score_before", None)
        if not base_score or base_score <= 0.0:
            base_score = calculate_base_score(getattr(context, "linter_metrics", None))

        quality_score = calculate_quality_score(findings, base_score)
        context.quality_score_after = quality_score

        # Count blocker violations from pre/post custom rules
        blocker_violations = 0
        if hasattr(context, "frame_results") and context.frame_results:
            for frame_data in context.frame_results.values():
                for violations_key in ("pre_violations", "post_violations"):
                    for v in frame_data.get(violations_key, []):
                        if getattr(v, "is_blocker", False):
                            blocker_violations += 1

        # Calculate frame counts
        frames_passed = getattr(pipeline, "frames_passed", 0)
        frames_failed = getattr(pipeline, "frames_failed", 0)
        frames_skipped = 0

        actual_total = frames_passed + frames_failed + frames_skipped
        planned_total = len(getattr(context, "selected_frames", [])) or len(self.frames)
        executed_count = len(frame_results)
        total_frames = max(actual_total, planned_total, executed_count)

        return PipelineResult(
            pipeline_id=context.pipeline_id,
            pipeline_name="Validation Pipeline",
            status=pipeline.status,
            duration=(datetime.now() - context.started_at).total_seconds() if context.started_at else 0.0,
            total_frames=total_frames,
            frames_passed=frames_passed,
            frames_failed=frames_failed,
            frames_skipped=frames_skipped,
            total_findings=total_findings,
            critical_findings=critical_findings,
            high_findings=high_findings,
            medium_findings=medium_findings,
            low_findings=low_findings,
            manual_review_findings=manual_review_count,
            blocker_violations=blocker_violations,
            findings=[f if isinstance(f, dict) else f.to_dict() for f in findings],
            frame_results=frame_results,
            metadata={
                "strategy": self.config.strategy.value,
                "fail_fast": self.config.fail_fast,
                "scan_id": scan_id,
                "advisories": getattr(context, "advisories", []),
                "frame_executions": [
                    {
                        "frame_id": fe.frame_id,
                        "status": fe.status,
                        "duration": fe.duration,
                    }
                    for fe in getattr(pipeline, "frame_executions", [])
                ],
            },
            artifacts=getattr(context, "artifacts", []),
            quality_score=quality_score,
            total_tokens=getattr(context, "total_tokens", 0),
            prompt_tokens=getattr(context, "prompt_tokens", 0),
            completion_tokens=getattr(context, "completion_tokens", 0),
        )

    @staticmethod
    def _collect_findings(context: PipelineContext, frame_results: list) -> list:
        """Collect findings from context and aggregate rule violations from frame results."""
        findings: list = []

        # Start with pipeline-level findings (from SecurityFrame, ResilienceFrame, etc.)
        if hasattr(context, "findings") and context.findings:
            findings.extend(context.findings)
        else:
            for frame_res in frame_results:
                if hasattr(frame_res, "findings") and frame_res.findings:
                    findings.extend(frame_res.findings)

        # Also include custom rule violations (pre/post) as findings
        for frame_res in frame_results:
            for attr in ("pre_rule_violations", "post_rule_violations"):
                violations = getattr(frame_res, attr, None)
                if violations:
                    from warden.pipeline.application.orchestrator.rule_executor import RuleExecutor

                    findings.extend([RuleExecutor.convert_to_finding(v) for v in violations])

        return findings

    @staticmethod
    def _is_review_required(f: Any) -> bool:
        """Check if a finding requires manual review."""
        if isinstance(f, dict):
            return f.get("verification_metadata", {}).get("review_required", False)
        v = getattr(f, "verification_metadata", {})
        return v.get("review_required", False) if isinstance(v, dict) else False
