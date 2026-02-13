"""
Suppression filtering for validation frames.

Handles configuration-based suppression of findings.
"""

import fnmatch
from typing import Any, Dict, List

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class SuppressionFilter:
    """Handles suppression of findings based on configuration."""

    @staticmethod
    def apply_config_suppressions(findings: list[Any], suppressions: list[dict[str, Any]]) -> list[Any]:
        """
        Apply configuration-based suppression rules.

        Args:
           findings: List of finding objects
           suppressions: List of suppression dicts (from config.yaml)

        Returns:
           Filtered list of findings
        """
        if not findings or not suppressions:
            return findings

        filtered_findings = []

        for finding in findings:
            is_suppressed = False

            f_id = getattr(finding, 'id', getattr(finding, 'rule', ''))

            f_path = ""
            if hasattr(finding, 'file_path'):
                f_path = finding.file_path
            elif hasattr(finding, 'location'):
                f_path = finding.location.split(':')[0]

            for rule_cfg in suppressions:
                rule_pattern = rule_cfg.get('rule')
                file_patterns = rule_cfg.get('files', [])
                if isinstance(file_patterns, str):
                    file_patterns = [file_patterns]

                if rule_pattern != '*' and rule_pattern != f_id:
                    continue

                matched_file = False
                if not file_patterns:
                    continue

                if f_path:
                    for pattern in file_patterns:
                        if fnmatch.fnmatch(f_path, pattern):
                            matched_file = True
                            break

                if not matched_file:
                    continue

                logger.debug("suppressing_finding_by_config",
                            finding=f_id,
                            file=f_path)
                is_suppressed = True
                break

            if not is_suppressed:
                filtered_findings.append(finding)

        return filtered_findings
