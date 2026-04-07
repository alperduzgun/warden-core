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
from warden.validation.domain.frame import CodeFile, Finding

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

        # --- PATTERN rules: fast in-memory evaluation per file ---
        for code_file in code_files:
            file_path = code_file.path
            content = code_file.content or ""

            for rule in pattern_rules:
                if not rule.enabled:
                    continue

                if rule.file_pattern:
                    if not fnmatch.fnmatch(Path(file_path).name, rule.file_pattern):
                        continue

                if not rule.pattern:
                    continue

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

        # --- Non-pattern rules via CustomRuleValidator ---
        if other_rules and self.rule_validator:
            ai_rules = [r for r in other_rules if r.type == "ai"]
            det_rules = [r for r in other_rules if r.type != "ai"]

            # Deterministic rules: per-file (fast, no LLM)
            for code_file in code_files:
                file_path_obj = Path(code_file.path)
                if det_rules and file_path_obj.exists():
                    file_violations = await self.rule_validator.validate_file_async(
                        file_path_obj, det_rules
                    )
                    violations.extend(file_violations)

            # AI rules: batch all files at once → concurrent execution with budget cap
            if ai_rules:
                all_paths = [Path(cf.path) for cf in code_files if Path(cf.path).exists()]
                batch_violations = await self.rule_validator.validate_batch_async(
                    all_paths, ai_rules
                )
                violations.extend(batch_violations)

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
            remediation=None,  # Populated by Fortification phase when replacement code is available
        )
