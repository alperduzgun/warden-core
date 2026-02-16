"""
Result aggregator module for validation results.

Handles result storage, aggregation, and false positive detection.
"""

from typing import Any

from warden.pipeline.domain.models import ValidationPipeline
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.logging import get_logger
from warden.shared.utils.finding_utils import get_finding_attribute
from warden.validation.domain.frame import Finding

logger = get_logger(__name__)


def normalize_finding_to_dict(finding: Any) -> dict[str, Any]:
    """
    Convert Finding (object or dict) to normalized dict with safe defaults.

    Handles:
    - Finding objects with .to_json()
    - Plain dicts
    - None values
    - Missing fields

    Returns consistent dict structure for pipeline.
    """
    if finding is None:
        logger.warning("normalize_finding_received_none")
        return {
            "id": "unknown",
            "type": "unknown",
            "message": "Malformed finding",
            "location": "unknown:0",
            "severity": "low",
            "file_context": "",
            "code_snippet": "",
            "file_path": "unknown",
        }

    if isinstance(finding, dict):
        # Normalize dict: ensure all required fields exist
        location = finding.get("location", "") or "unknown:0"
        return {
            "id": finding.get("id", "unknown"),
            "type": finding.get("type", "unknown"),
            "message": finding.get("message", ""),
            "location": location,
            "severity": (finding.get("severity", "low") or "low").lower(),
            "file_context": finding.get("file_context", ""),
            "code_snippet": finding.get("code_snippet", ""),
            "file_path": location.split(":")[0] if ":" in location else location,
        }

    # Finding object
    try:
        location = getattr(finding, "location", "") or "unknown:0"
        return {
            "id": getattr(finding, "id", "unknown"),
            "type": getattr(finding, "type", "unknown"),
            "message": getattr(finding, "message", ""),
            "location": location,
            "severity": (getattr(finding, "severity", "low") or "low").lower(),
            "file_context": getattr(finding, "file_context", ""),
            "code_snippet": getattr(finding, "code_snippet", ""),
            "file_path": location.split(":")[0] if ":" in location else location,
        }
    except Exception as e:
        logger.error("normalize_finding_failed", error=str(e), finding_type=type(finding).__name__)
        # Return safe default
        return normalize_finding_to_dict(None)


class ResultAggregator:
    """Aggregates and processes validation results."""

    def store_validation_results(self, context: PipelineContext, pipeline: ValidationPipeline) -> None:
        """
        Store validation results in context.

        Args:
            context: Pipeline context to store results in
            pipeline: Validation pipeline with execution stats
        """
        if not hasattr(context, "frame_results"):
            # Initialize empty results if no frame results
            context.findings = []
            context.validated_issues = []
            return

        # BATCH 2: Input validation on frame_results
        if not isinstance(context.frame_results, dict):
            logger.error(
                "invalid_frame_results_type",
                type=type(context.frame_results).__name__,
                action="resetting_to_empty",
            )
            context.findings = []
            context.validated_issues = []
            return

        # Aggregate findings from all frames
        all_findings = []
        for frame_id, frame_data in context.frame_results.items():
            frame_result = frame_data.get("result")
            if frame_result and hasattr(frame_result, "findings"):
                # BATCH 2: Validate findings is a list
                if not isinstance(frame_result.findings, list):
                    logger.warning(
                        "invalid_findings_list_type",
                        frame_id=frame_id,
                        type=type(frame_result.findings).__name__,
                        action="skipping_frame",
                    )
                    continue

                # BATCH 2: Limit findings to prevent memory bombs
                MAX_FINDINGS_PER_FRAME = 1000
                if len(frame_result.findings) > MAX_FINDINGS_PER_FRAME:
                    # BATCH 3: Log detailed truncation info (CRITICAL - prevents silent data loss)
                    truncated_count = len(frame_result.findings) - MAX_FINDINGS_PER_FRAME
                    dropped_findings = frame_result.findings[MAX_FINDINGS_PER_FRAME:]

                    # Calculate severity distribution of dropped findings
                    severity_distribution = {}
                    for f in dropped_findings:
                        sev = get_finding_attribute(f, "severity", "unknown")
                        severity_distribution[sev] = severity_distribution.get(sev, 0) + 1

                    logger.warning(
                        "findings_truncated",
                        frame_id=frame_id,
                        total_findings=len(frame_result.findings),
                        truncated_count=truncated_count,
                        kept_count=MAX_FINDINGS_PER_FRAME,
                        dropped_severity_distribution=severity_distribution,
                        action="keeping_first_1000",
                    )
                    all_findings.extend(frame_result.findings[:MAX_FINDINGS_PER_FRAME])
                else:
                    all_findings.extend(frame_result.findings)

            # Aggregate custom rule violations as findings
            for violation in frame_data.get("pre_violations", []):
                all_findings.append(self._violation_to_finding(violation, frame_id, "pre"))
            for violation in frame_data.get("post_violations", []):
                all_findings.append(self._violation_to_finding(violation, frame_id, "post"))

        # Deduplicate findings across frames (Tier 1: Context-Awareness)
        all_findings = self._deduplicate_findings(all_findings)

        # Replace context.findings with aggregated results (single source of truth)
        context.findings = all_findings

        # Ensure validated_issues is always set, even if empty
        validated_issues = []
        false_positives = []  # Track suppressed findings

        for finding in all_findings:
            # Use normalizer for type-safe conversion (Batch 1: Type Safety)
            finding_dict = normalize_finding_to_dict(finding)

            # Check if it's a false positive
            is_fp = self._is_false_positive(finding_dict, getattr(context, "suppression_rules", []))

            if not is_fp:
                validated_issues.append(finding_dict)
            else:
                # Track suppressed finding as false positive
                false_positives.append(finding_dict.get("id", "unknown"))
                logger.info(
                    "finding_suppressed",
                    finding_id=finding_dict.get("id"),
                    reason="suppression_rule_match",
                    file_path=finding_dict.get("file_path"),
                )

        context.validated_issues = validated_issues
        context.false_positives = false_positives

        # Add phase result
        context.add_phase_result(
            "VALIDATION",
            {
                "total_findings": len(all_findings),
                "validated_issues": len(context.validated_issues),
                "frames_executed": pipeline.frames_executed,
                "frames_passed": pipeline.frames_passed,
                "frames_failed": pipeline.frames_failed,
            },
        )

    def _deduplicate_findings(self, findings: list[Finding]) -> list[Finding]:
        """
        Deduplicate findings across frames.

        Multiple frames may report the same issue at the same location.
        Keep the finding with highest confidence/severity.

        Args:
            findings: List of findings from all frames

        Returns:
            Deduplicated list of findings
        """
        if not findings:
            return []

        # BATCH 3: Track deduplication metrics
        metrics = {
            "total_findings": len(findings),
            "empty_locations": 0,
            "invalid_severity": 0,
            "collision_count": 0,
            "severity_upgraded": 0,
        }

        seen: dict[tuple[str, str], Finding] = {}

        for finding in findings:
            # Extract location for deduplication key (CRITICAL FIX: ensure non-empty)
            location = get_finding_attribute(finding, "location", "") or "unknown:0"

            # CRITICAL FIX: Don't deduplicate findings without valid location
            # Empty location causes multiple distinct findings to map to same key
            if not location or location == "" or location == "unknown:0":
                # BATCH 3: Track empty locations
                metrics["empty_locations"] += 1
                # Treat each finding without location as unique
                unique_key = f"no_location_{len(seen)}"
                seen[unique_key] = finding  # type: ignore
                logger.debug(
                    "finding_without_location_preserved",
                    finding_id=get_finding_attribute(finding, "id", "unknown"),
                )
                continue

            # Extract vulnerability type from ID
            # Examples:
            #   "security-sql-001" -> "sql" (vulnerability type from middle part)
            #   "antipattern-sql-002" -> "sql" (same vulnerability)
            #   "sql-injection" -> "sql-injection" (treat full ID as type)
            #   "RUST-001", "RUST-002" -> "RUST-001", "RUST-002" (different issues, use full ID)
            #   "F1", "F2" -> use message for grouping
            finding_id = get_finding_attribute(finding, "id", "")
            parts = finding_id.split("-")

            if len(parts) >= 3:
                # Three or more parts: assume format "frame-type-number"
                # "security-sql-001" -> "sql", "antipattern-sql-002" -> "sql"
                rule_type = parts[1]
            elif len(parts) == 2:
                # Two parts: could be "RUST-001" or "sql-injection"
                # If second part is numeric, use full ID (different issues)
                # If second part is text, use full ID as type
                if parts[1].isdigit():
                    # "RUST-001" -> "RUST-001" (use full ID, these are different issues)
                    rule_type = finding_id
                else:
                    # "sql-injection" -> "sql-injection" (use full ID as type)
                    rule_type = finding_id
            else:
                # Simple ID without structure: use full ID as type
                # "R1", "G1", "S1" -> each is distinct, use full ID
                # This ensures findings with different IDs are not deduplicated
                rule_type = finding_id

            # Create deduplication key: (location, rule_type)
            key = (location, rule_type)

            if key not in seen:
                seen[key] = finding
            else:
                # BATCH 3: Track collision
                metrics["collision_count"] += 1

                # Keep finding with higher severity
                existing = seen[key]
                # CRITICAL FIX: Normalize severity to lowercase (prevent case sensitivity bugs)
                existing_severity = (get_finding_attribute(existing, "severity", "low") or "low").lower()
                new_severity = (get_finding_attribute(finding, "severity", "low") or "low").lower()

                # Severity ranking: critical > high > medium > low
                severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}

                # Validate severity values (prevent unknown severity from getting rank 0)
                if new_severity not in severity_rank:
                    metrics["invalid_severity"] += 1
                    logger.warning(
                        "invalid_severity_normalized",
                        finding_id=get_finding_attribute(finding, "id", "unknown"),
                        severity=new_severity,
                        normalized_to="low",
                    )
                    new_severity = "low"

                if existing_severity not in severity_rank:
                    metrics["invalid_severity"] += 1
                    logger.warning(
                        "invalid_severity_normalized",
                        finding_id=get_finding_attribute(existing, "id", "unknown"),
                        severity=existing_severity,
                        normalized_to="low",
                    )
                    existing_severity = "low"

                if severity_rank.get(new_severity, 1) > severity_rank.get(existing_severity, 1):
                    seen[key] = finding
                    metrics["severity_upgraded"] += 1
                    logger.debug(
                        "finding_deduplicated",
                        location=location,
                        rule_type=rule_type,
                        kept_severity=new_severity,
                        dropped_severity=existing_severity,
                    )

        deduplicated = list(seen.values())

        # BATCH 3: Log comprehensive deduplication metrics
        dedup_rate = 1.0 - (len(deduplicated) / max(1, metrics["total_findings"]))
        logger.info(
            "deduplication_metrics",
            input_count=metrics["total_findings"],
            output_count=len(deduplicated),
            collision_count=metrics["collision_count"],
            empty_locations=metrics["empty_locations"],
            invalid_severity=metrics["invalid_severity"],
            severity_upgraded=metrics["severity_upgraded"],
            dedup_rate=round(dedup_rate, 3),
        )

        if len(deduplicated) < len(findings):
            logger.info(
                "findings_deduplicated",
                original_count=len(findings),
                deduplicated_count=len(deduplicated),
                duplicates_removed=len(findings) - len(deduplicated),
            )

        return deduplicated

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
                if finding_type == rule or finding_msg.find(rule) != -1:
                    return True
        return False

    @staticmethod
    def _violation_to_finding(violation, frame_id: str, phase: str) -> Finding:
        """Convert a CustomRuleViolation to a Finding for unified aggregation."""
        severity = getattr(violation, "severity", "medium")
        if hasattr(severity, "value"):
            severity = severity.value
        return Finding(
            id=f"rule/{frame_id}/{phase}/{getattr(violation, 'rule_id', 'unknown')}",
            severity=str(severity).lower(),
            message=getattr(violation, "message", str(violation)),
            location=f"{getattr(violation, 'file', 'unknown')}:{getattr(violation, 'line', 0)}",
            detail=getattr(violation, "suggestion", None),
            code=getattr(violation, "code_snippet", None),
            line=getattr(violation, "line", 0),
            is_blocker=getattr(violation, "is_blocker", False),
        )

    def aggregate_frame_results(self, context: PipelineContext) -> dict[str, Any]:
        """
        Aggregate results from all executed frames.

        Args:
            context: Pipeline context with frame results

        Returns:
            Aggregated statistics
        """
        if not hasattr(context, "frame_results"):
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
            frame_result = frame_data.get("result")
            if not frame_result:
                stats["frames_skipped"] += 1
                continue

            # Count findings
            findings_count = len(frame_result.findings) if hasattr(frame_result, "findings") else 0
            stats["total_findings"] += findings_count
            stats["findings_by_frame"][frame_id] = findings_count

            # Count pass/fail
            status = getattr(frame_result, "status", "unknown")
            if status in ["passed", "warning"]:
                stats["frames_passed"] += 1
            elif status in ["failed", "error", "timeout"]:
                stats["frames_failed"] += 1
            else:
                stats["frames_skipped"] += 1

        return stats
