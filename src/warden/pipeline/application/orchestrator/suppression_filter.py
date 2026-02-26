"""
Suppression filtering for validation frames.

Handles configuration-based suppression of findings with full audit trail.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class SuppressionFilter:
    """Handles suppression of findings based on configuration."""

    @staticmethod
    def apply_config_suppressions(
        findings: list[Any],
        suppressions: list[dict[str, Any]],
        context: Any | None = None,
    ) -> list[Any]:
        """
        Apply configuration-based suppression rules.

        Args:
           findings: List of finding objects
           suppressions: List of suppression dicts (from config.yaml)
           context: Optional PipelineContext to record suppressed findings audit trail

        Returns:
           Filtered list of findings
        """
        if not findings or not suppressions:
            return findings

        filtered_findings = []

        for finding in findings:
            is_suppressed = False
            matched_rule_pattern = None
            matched_file_patterns: list[str] = []

            f_id = getattr(finding, "id", getattr(finding, "rule", ""))

            f_path = ""
            if hasattr(finding, "file_path"):
                f_path = finding.file_path
            elif hasattr(finding, "location"):
                f_path = finding.location.split(":")[0]

            for rule_cfg in suppressions:
                rule_pattern = rule_cfg.get("rule")
                file_patterns = rule_cfg.get("files", [])
                if isinstance(file_patterns, str):
                    file_patterns = [file_patterns]

                if rule_pattern != "*" and rule_pattern != f_id:
                    continue

                matched_file = False
                if not file_patterns:
                    continue

                if f_path:
                    for pattern in file_patterns:
                        if Path(f_path).match(pattern):
                            matched_file = True
                            break

                if not matched_file:
                    continue

                matched_rule_pattern = rule_pattern
                matched_file_patterns = file_patterns
                is_suppressed = True
                break

            if is_suppressed:
                # Extract finding details for audit record
                f_title = getattr(finding, "message", getattr(finding, "title", str(f_id)))
                f_severity = getattr(finding, "severity", "unknown")
                if hasattr(f_severity, "value"):
                    f_severity = f_severity.value

                suppression_record = {
                    "id": str(f_id),
                    "file": str(f_path),
                    "title": str(f_title),
                    "severity": str(f_severity),
                    "matched_rule": str(matched_rule_pattern),
                    "matched_files": matched_file_patterns,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                # Log each suppression decision at INFO level
                logger.info(
                    "finding_suppressed_by_config",
                    finding_id=f_id,
                    file=f_path,
                    severity=f_severity,
                    matched_rule=matched_rule_pattern,
                    matched_files=matched_file_patterns,
                )

                # Record in context audit trail if available
                if context is not None and hasattr(context, "add_suppressed_finding"):
                    context.add_suppressed_finding(suppression_record)
                elif context is not None and hasattr(context, "suppressed_findings"):
                    context.suppressed_findings.append(suppression_record)
            else:
                filtered_findings.append(finding)

        suppressed_count = len(findings) - len(filtered_findings)
        if suppressed_count > 0:
            logger.info(
                "suppression_filter_summary",
                total_findings=len(findings),
                suppressed=suppressed_count,
                remaining=len(filtered_findings),
            )

        return filtered_findings
