"""
Rule execution and conversion for validation frames.

Handles custom rule execution and conversion to findings.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from warden.rules.application.rule_validator import CustomRuleValidator
from warden.rules.domain.models import CustomRule, CustomRuleViolation
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile, Finding, Remediation

logger = get_logger(__name__)


class RuleExecutor:
    """Handles rule execution and conversion."""

    def __init__(self, rule_validator: CustomRuleValidator | None = None):
        self.rule_validator = rule_validator

    async def execute_rules_async(
        self,
        rules: list[CustomRule],
        code_files: list[CodeFile],
    ) -> list[CustomRuleViolation]:
        """Execute custom rules on code files.

        PATTERN rules are evaluated in-memory against the file path and content.
        Other rule types are delegated to the file-based validator when the file exists.
        """
        violations: list[CustomRuleViolation] = []

        pattern_rules = [r for r in rules if r.type == "pattern"]
        other_rules = [r for r in rules if r.type != "pattern"]

        for code_file in code_files:
            file_path = code_file.path
            content = code_file.content or ""

            # Evaluate PATTERN rules in-memory (no disk access needed)
            for rule in pattern_rules:
                if not rule.enabled:
                    continue

                # file_pattern filter (glob match on filename)
                if rule.file_pattern:
                    if not fnmatch.fnmatch(Path(file_path).name, rule.file_pattern):
                        continue

                if not rule.pattern:
                    continue

                # Match against file path first, then content
                matched = bool(re.search(rule.pattern, file_path)) or bool(
                    re.search(rule.pattern, content, re.MULTILINE)
                )
                if matched:
                    from warden.rules.domain.enums import RuleCategory

                    violations.append(
                        CustomRuleViolation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            category=rule.category or RuleCategory.CUSTOM,
                            severity=rule.severity,
                            is_blocker=rule.is_blocker,
                            file=file_path,
                            line=1,
                            message=rule.message or f"Rule '{rule.name}' violated",
                            suggestion=None,
                            code_snippet=None,
                        )
                    )

            # Delegate non-pattern rules to the file-based validator (if file exists)
            if other_rules and self.rule_validator:
                file_path_obj = Path(file_path)
                if file_path_obj.exists():
                    file_violations = await self.rule_validator.validate_file_async(
                        file_path_obj,
                        other_rules,
                    )
                    violations.extend(file_violations)
                else:
                    logger.debug(
                        "rule_executor_file_not_found_skipping_non_pattern_rules",
                        file=file_path,
                        rule_count=len(other_rules),
                    )

        return violations

    @staticmethod
    def has_blocker_violations(violations: list[CustomRuleViolation]) -> bool:
        """Check if any violations are blockers."""
        return any(v.is_blocker for v in violations)

    @staticmethod
    def convert_to_finding(violation: CustomRuleViolation) -> Finding:
        """Convert CustomRuleViolation to Finding."""
        return Finding(
            id=violation.rule_id,
            severity=violation.severity.value if hasattr(violation.severity, "value") else str(violation.severity),
            message=violation.message,
            location=f"{violation.file}:{violation.line}",
            detail=violation.suggestion,
            code=violation.code_snippet,
            line=violation.line,
            is_blocker=violation.is_blocker,
            remediation=Remediation(description=violation.suggestion, code="") if violation.suggestion else None,
        )
