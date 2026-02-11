"""
Result aggregator module for validation results.

Handles result storage, aggregation, and false positive detection.
"""

from typing import Any, Dict, List

from warden.pipeline.domain.models import ValidationPipeline
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.logging import get_logger
from warden.shared.utils.finding_utils import get_finding_attribute
from warden.validation.domain.frame import Finding

logger = get_logger(__name__)


class ResultAggregator:
    """Aggregates and processes validation results."""

    def store_validation_results(
        self,
        context: PipelineContext,
        pipeline: ValidationPipeline
    ) -> None:
        """
        Store validation results in context.

        Args:
            context: Pipeline context to store results in
            pipeline: Validation pipeline with execution stats
        """
        if not hasattr(context, 'frame_results'):
            # Initialize empty results if no frame results
            context.findings = []
            context.validated_issues = []
            return

        # Aggregate findings from all frames
        all_findings = []
        for frame_id, frame_data in context.frame_results.items():
            frame_result = frame_data.get('result')
            if frame_result and hasattr(frame_result, 'findings'):
                all_findings.extend(frame_result.findings)

            # Aggregate custom rule violations as findings
            for violation in frame_data.get('pre_violations', []):
                all_findings.append(self._violation_to_finding(violation, frame_id, "pre"))
            for violation in frame_data.get('post_violations', []):
                all_findings.append(self._violation_to_finding(violation, frame_id, "post"))

        # Replace context.findings with aggregated results (single source of truth)
        context.findings = all_findings

        # Ensure validated_issues is always set, even if empty
        validated_issues = []
        for finding in all_findings:
            # Safely extract values regardless of type (Chaos/Pareto Lens)
            finding_dict = {
                "id": get_finding_attribute(finding, "id"),
                "type": get_finding_attribute(finding, "type"),
                "message": get_finding_attribute(finding, "message"),
                "location": get_finding_attribute(finding, "location"),
                "file_context": get_finding_attribute(finding, "file_context"),
                "severity": get_finding_attribute(finding, "severity"),
                "code_snippet": get_finding_attribute(finding, "code_snippet"),
            }

            # Check if it's a false positive
            is_fp = self._is_false_positive(
                finding_dict,
                getattr(context, 'suppression_rules', [])
            )

            if not is_fp:
                validated_issues.append(finding_dict)
            else:
                logger.info(
                    "finding_suppressed",
                    finding_id=finding_dict.get("id"),
                    reason="suppression_rule_match",
                    file_path=finding_dict.get("file_path")
                )

        context.validated_issues = validated_issues

        # Add phase result
        context.add_phase_result("VALIDATION", {
            "total_findings": len(all_findings),
            "validated_issues": len(context.validated_issues),
            "frames_executed": pipeline.frames_executed,
            "frames_passed": pipeline.frames_passed,
            "frames_failed": pipeline.frames_failed,
        })

    def _is_false_positive(
        self,
        finding: dict[str, Any],
        suppression_rules: list[dict[str, Any]],
    ) -> bool:
        """
        Check if a finding is a false positive based on suppression rules.

        Args:
            finding: Finding to check
            suppression_rules: List of suppression rules

        Returns:
            True if finding is a false positive
        """
        if not suppression_rules:
            return False

        for rule in suppression_rules:
            # Handle both dict and string rules
            if isinstance(rule, dict):
                # Ensure safe access for rule and finding (Pareto Lens)
                rule_type = rule.get("issue_type")
                finding_type = get_finding_attribute(finding, "type")
                rule_context = rule.get("file_context")
                finding_context = get_finding_attribute(finding, "file_context")

                if rule_type == finding_type and rule_context == finding_context:
                    return True
            elif isinstance(rule, str):
                # Simple string rule matching
                finding_type = get_finding_attribute(finding, "type")
                finding_msg = get_finding_attribute(finding, "message", "")
                if (finding_type == rule or finding_msg.find(rule) != -1):
                    return True
        return False

    @staticmethod
    def _violation_to_finding(violation, frame_id: str, phase: str) -> Finding:
        """Convert a CustomRuleViolation to a Finding for unified aggregation."""
        severity = getattr(violation, 'severity', 'medium')
        if hasattr(severity, 'value'):
            severity = severity.value
        return Finding(
            id=f"rule/{frame_id}/{phase}/{getattr(violation, 'rule_id', 'unknown')}",
            severity=str(severity).lower(),
            message=getattr(violation, 'message', str(violation)),
            location=f"{getattr(violation, 'file', 'unknown')}:{getattr(violation, 'line', 0)}",
            detail=getattr(violation, 'suggestion', None),
            code=getattr(violation, 'code_snippet', None),
            line=getattr(violation, 'line', 0),
            is_blocker=getattr(violation, 'is_blocker', False),
        )

    def aggregate_frame_results(
        self,
        context: PipelineContext
    ) -> dict[str, Any]:
        """
        Aggregate results from all executed frames.

        Args:
            context: Pipeline context with frame results

        Returns:
            Aggregated statistics
        """
        if not hasattr(context, 'frame_results'):
            return {
                "total_frames": 0,
                "total_findings": 0,
                "frames_passed": 0,
                "frames_failed": 0,
                "frames_skipped": 0,
            }

        stats = {
            "total_frames": len(context.frame_results),
            "total_findings": 0,
            "frames_passed": 0,
            "frames_failed": 0,
            "frames_skipped": 0,
            "findings_by_frame": {},
        }

        for frame_id, frame_data in context.frame_results.items():
            frame_result = frame_data.get('result')
            if not frame_result:
                stats["frames_skipped"] += 1
                continue

            # Count findings
            findings_count = (
                len(frame_result.findings)
                if hasattr(frame_result, 'findings')
                else 0
            )
            stats["total_findings"] += findings_count
            stats["findings_by_frame"][frame_id] = findings_count

            # Count pass/fail
            status = getattr(frame_result, 'status', 'unknown')
            if status in ['passed', 'warning']:
                stats["frames_passed"] += 1
            elif status in ['failed', 'error', 'timeout']:
                stats["frames_failed"] += 1
            else:
                stats["frames_skipped"] += 1

        return stats
