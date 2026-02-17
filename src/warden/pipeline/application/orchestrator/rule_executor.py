"""
Rule execution and conversion for validation frames.

Handles custom rule execution and conversion to findings.
"""

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
        """Execute custom rules on code files."""
        if not self.rule_validator:
            return []

        violations = []
        for code_file in code_files:
            file_violations = await self.rule_validator.validate_file_async(
                code_file,
                rules,
            )
            violations.extend(file_violations)

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
