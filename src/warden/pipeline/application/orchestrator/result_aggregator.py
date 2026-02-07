"""
Result aggregator module for validation results.

Handles result storage, aggregation, and false positive detection.
"""

from typing import Dict, Any, List
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.pipeline.domain.models import ValidationPipeline
from warden.validation.domain.frame import Finding
from warden.shared.infrastructure.logging import get_logger

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
            # Convert finding to dict if it has to_dict method
            if hasattr(finding, 'to_dict'):
                finding_dict = finding.to_dict()
            elif isinstance(finding, dict):
                finding_dict = finding
            else:
                # If it's neither, skip it (shouldn't happen but be safe)
                logger.warning(
                    "Unexpected finding type",
                    finding_type=type(finding).__name__
                )
                continue

            # Check if it's a false positive
            if not self._is_false_positive(
                finding_dict,
                getattr(context, 'suppression_rules', [])
            ):
                validated_issues.append(finding_dict)

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
        finding: Dict[str, Any],
        suppression_rules: List[Dict[str, Any]],
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
                if (
                    rule.get("issue_type") == finding.get("type") and
                    rule.get("file_context") == finding.get("file_context")
                ):
                    return True
            elif isinstance(rule, str):
                # Simple string rule matching
                if (finding.get("type") == rule or
                    finding.get("message", "").find(rule) != -1):
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
    ) -> Dict[str, Any]:
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