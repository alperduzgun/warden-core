"""
False Positive Detection Module - Issue Validator.

Validates issues to reduce false positives through rule-based confidence adjustment.
Each rule applies a penalty to the confidence score, and issues below the minimum
threshold are rejected as likely false positives.

C# Legacy Pattern:
    adjustedConfidence = originalConfidence;
    foreach (var failedRule in failedRules) {
        adjustedConfidence -= rule.ConfidencePenalty;  // -0.2 to -1.0
    }
    if (adjustedConfidence < MinimumConfidence) → REJECT (False Positive)

Architecture:
    - IssueValidator: Main orchestrator
    - ValidationRule: Protocol for validation rules
    - ValidationResult: Result with adjusted confidence
    - Built-in rules: ConfidenceThreshold, LineNumberRange

Panel JSON: All models serialize to camelCase for Panel compatibility.
Reporter-only: This module only reports, never modifies code.
Fail-safe: On validation error, pass issue with low confidence (0.3).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Protocol

from warden.issues.domain.models import WardenIssue
from warden.shared.domain.base_model import BaseDomainModel

logger = logging.getLogger(__name__)


# ============================================================================
# VALIDATION RESULT MODEL
# ============================================================================


@dataclass
class ValidationResult(BaseDomainModel):
    """
    Result of issue validation with confidence adjustment.

    Panel TypeScript equivalent:
    ```typescript
    export interface ValidationResult {
      isValid: boolean;
      originalConfidence: number;
      adjustedConfidence: number;
      failedRules: string[];
    }
    ```

    Attributes:
        is_valid: Whether issue passes validation (adjusted_confidence >= 0.5)
        original_confidence: Original confidence before rule penalties
        adjusted_confidence: Confidence after applying rule penalties
        failed_rules: List of rule names that failed (applied penalties)
    """

    is_valid: bool
    original_confidence: float
    adjusted_confidence: float
    failed_rules: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate confidence values."""
        if not 0.0 <= self.original_confidence <= 1.0:
            raise ValueError(
                f"original_confidence must be in [0.0, 1.0], got {self.original_confidence}"
            )
        # adjusted_confidence can go negative during calculation
        self.adjusted_confidence = max(0.0, min(1.0, self.adjusted_confidence))


# ============================================================================
# VALIDATION RULE PROTOCOL
# ============================================================================


class ValidationRule(Protocol):
    """
    Protocol for all validation rules.

    Each rule implements:
    - validate(issue): Returns True if rule passes, False if it fails
    - confidence_penalty: Penalty to apply when rule fails (-0.2 to -1.0)
    - name: Human-readable rule name
    """

    @property
    def name(self) -> str:
        """Human-readable rule name."""
        ...

    @property
    def confidence_penalty(self) -> float:
        """
        Confidence penalty when rule fails.

        Range: -0.2 to -1.0
        - -0.2 to -0.5: Minor issues (e.g., formatting, style)
        - -0.6 to -0.8: Moderate issues (e.g., missing context, questionable evidence)
        - -0.9 to -1.0: Critical issues (e.g., no confidence, invalid data)
        """
        ...

    @abstractmethod
    def validate(self, issue: WardenIssue) -> bool:
        """
        Validate the issue.

        Args:
            issue: Issue to validate

        Returns:
            True if validation passes, False if it fails
        """
        ...


# ============================================================================
# BASE VALIDATION RULE
# ============================================================================


class BaseValidationRule(ABC):
    """
    Base class for validation rules.

    Provides common functionality and enforces Protocol contract.
    """

    def __init__(self, name: str, confidence_penalty: float) -> None:
        """
        Initialize rule.

        Args:
            name: Human-readable rule name
            confidence_penalty: Penalty to apply (-0.2 to -1.0)

        Raises:
            ValueError: If penalty is not in valid range
        """
        if not -1.0 <= confidence_penalty <= -0.2:
            raise ValueError(
                f"confidence_penalty must be in [-1.0, -0.2], got {confidence_penalty}"
            )

        self._name = name
        self._confidence_penalty = confidence_penalty

    @property
    def name(self) -> str:
        """Human-readable rule name."""
        return self._name

    @property
    def confidence_penalty(self) -> float:
        """Confidence penalty when rule fails."""
        return self._confidence_penalty

    @abstractmethod
    def validate(self, issue: WardenIssue) -> bool:
        """
        Validate the issue.

        Args:
            issue: Issue to validate

        Returns:
            True if validation passes, False if it fails
        """
        ...


# ============================================================================
# BUILT-IN VALIDATION RULES
# ============================================================================


class ConfidenceThresholdRule(BaseValidationRule):
    """
    Validates that issue confidence meets minimum threshold.

    This is a critical rule that immediately rejects issues with very low confidence.
    Default minimum: 0.5 (50%)
    Penalty: -1.0 (immediate rejection)

    Example:
        >>> rule = ConfidenceThresholdRule(minimum_confidence=0.5)
        >>> issue = WardenIssue(..., confidence=0.3)
        >>> rule.validate(issue)
        False  # Confidence too low
    """

    def __init__(self, minimum_confidence: float = 0.5) -> None:
        """
        Initialize confidence threshold rule.

        Args:
            minimum_confidence: Minimum confidence threshold (default: 0.5)

        Raises:
            ValueError: If minimum_confidence not in [0.0, 1.0]
        """
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError(
                f"minimum_confidence must be in [0.0, 1.0], got {minimum_confidence}"
            )

        super().__init__(
            name=f"ConfidenceThreshold(>={minimum_confidence})",
            confidence_penalty=-1.0,  # Critical rule - immediate rejection
        )
        self._minimum_confidence = minimum_confidence

    def validate(self, issue: WardenIssue) -> bool:
        """
        Validate issue confidence >= minimum threshold.

        Args:
            issue: Issue to validate (must have confidence attribute)

        Returns:
            True if confidence >= minimum, False otherwise
        """
        # Check if issue has confidence attribute
        if not hasattr(issue, "confidence"):
            # Issue model doesn't have confidence yet - assume it needs to be added
            logger.warning(
                f"Issue {issue.id} missing 'confidence' attribute. "
                "WardenIssue model may need to be extended."
            )
            return False

        confidence = getattr(issue, "confidence", 0.0)
        return confidence >= self._minimum_confidence


class LineNumberRangeRule(BaseValidationRule):
    """
    Validates that line_number is valid and within file bounds.

    Checks:
    1. line_number > 0 (positive integer)
    2. line_number <= file_line_count (if available)

    Penalty: -0.3 (moderate issue)

    Example:
        >>> rule = LineNumberRangeRule()
        >>> issue = WardenIssue(..., line_number=0)
        >>> rule.validate(issue)
        False  # Line number must be > 0
    """

    def __init__(self) -> None:
        """Initialize line number range rule."""
        super().__init__(
            name="LineNumberRange(>0)",
            confidence_penalty=-0.3,  # Moderate penalty
        )

    def validate(self, issue: WardenIssue) -> bool:
        """
        Validate line number is positive and within bounds.

        Args:
            issue: Issue to validate (must have line_number or extract from file_path)

        Returns:
            True if line number is valid, False otherwise
        """
        line_number = self._extract_line_number(issue)

        if line_number is None:
            logger.warning(
                f"Issue {issue.id} has no line number information in file_path: {issue.file_path}"
            )
            return False

        # Check line number is positive
        if line_number <= 0:
            logger.debug(f"Issue {issue.id} has invalid line number: {line_number}")
            return False

        # TODO: Optionally check line_number <= file_line_count
        # This would require reading the file, which adds I/O overhead.
        # For now, we only validate line_number > 0.

        return True

    def _extract_line_number(self, issue: WardenIssue) -> Optional[int]:
        """
        Extract line number from issue.

        Checks:
        1. issue.line_number attribute (if exists)
        2. Parse from file_path (e.g., "file.py:45")

        Args:
            issue: Issue to extract line number from

        Returns:
            Line number or None if not found
        """
        # Check for direct attribute
        if hasattr(issue, "line_number"):
            return getattr(issue, "line_number", None)

        # Parse from file_path (e.g., "user_service.py:45")
        if ":" in issue.file_path:
            try:
                parts = issue.file_path.split(":")
                if len(parts) >= 2:
                    return int(parts[1])
            except (ValueError, IndexError):
                pass

        return None


# ============================================================================
# ISSUE VALIDATOR ORCHESTRATOR
# ============================================================================


class IssueValidator:
    """
    Main orchestrator for issue validation.

    Applies all registered validation rules and calculates adjusted confidence.
    Issues with adjusted_confidence < minimum_confidence are rejected as false positives.

    Architecture:
        1. Start with original confidence
        2. Apply each validation rule
        3. Deduct penalty for each failed rule
        4. Reject if adjusted_confidence < minimum_confidence

    Example:
        >>> validator = IssueValidator(minimum_confidence=0.5)
        >>> validator.add_rule(ConfidenceThresholdRule(0.5))
        >>> validator.add_rule(LineNumberRangeRule())
        >>> result = validator.validate(issue)
        >>> if not result.is_valid:
        ...     print(f"Rejected: {result.failed_rules}")

    Fail-safe: If validation raises an exception, returns ValidationResult
    with is_valid=True but low confidence (0.3) to avoid blocking pipeline.
    """

    def __init__(
        self,
        minimum_confidence: float = 0.5,
        default_confidence: float = 0.7,
    ) -> None:
        """
        Initialize issue validator.

        Args:
            minimum_confidence: Minimum confidence threshold (default: 0.5)
            default_confidence: Default confidence if issue has none (default: 0.7)

        Raises:
            ValueError: If thresholds not in [0.0, 1.0]
        """
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError(
                f"minimum_confidence must be in [0.0, 1.0], got {minimum_confidence}"
            )
        if not 0.0 <= default_confidence <= 1.0:
            raise ValueError(
                f"default_confidence must be in [0.0, 1.0], got {default_confidence}"
            )

        self._minimum_confidence = minimum_confidence
        self._default_confidence = default_confidence
        self._rules: List[ValidationRule] = []

        logger.info(
            f"IssueValidator initialized (min_confidence={minimum_confidence}, "
            f"default_confidence={default_confidence})"
        )

    def add_rule(self, rule: ValidationRule) -> None:
        """
        Register a validation rule.

        Args:
            rule: Validation rule to add
        """
        self._rules.append(rule)
        logger.debug(f"Added validation rule: {rule.name}")

    def validate(self, issue: WardenIssue) -> ValidationResult:
        """
        Validate issue and calculate adjusted confidence.

        Process:
        1. Extract original confidence (or use default)
        2. Apply each validation rule
        3. Deduct penalty for each failed rule
        4. Determine is_valid based on adjusted confidence

        Args:
            issue: Issue to validate

        Returns:
            ValidationResult with adjusted confidence and failed rules

        Fail-safe:
            If exception occurs, returns is_valid=True with low confidence (0.3)
            to avoid blocking the pipeline.
        """
        try:
            # Extract original confidence
            original_confidence = self._get_confidence(issue)

            # Apply validation rules
            adjusted_confidence = original_confidence
            failed_rules: List[str] = []

            for rule in self._rules:
                try:
                    if not rule.validate(issue):
                        # Rule failed - apply penalty
                        adjusted_confidence += rule.confidence_penalty
                        failed_rules.append(rule.name)
                        logger.debug(
                            f"Rule '{rule.name}' failed for issue {issue.id}. "
                            f"Penalty: {rule.confidence_penalty}"
                        )
                except Exception as e:
                    # Rule execution failed - log and skip
                    logger.error(
                        f"Error executing rule '{rule.name}' for issue {issue.id}: {e}",
                        exc_info=True,
                    )
                    # Don't fail the entire validation - continue with other rules

            # Clamp adjusted confidence to [0.0, 1.0]
            adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))

            # Determine validity
            is_valid = adjusted_confidence >= self._minimum_confidence

            result = ValidationResult(
                is_valid=is_valid,
                original_confidence=original_confidence,
                adjusted_confidence=adjusted_confidence,
                failed_rules=failed_rules,
            )

            if not is_valid:
                logger.info(
                    f"Issue {issue.id} REJECTED as false positive. "
                    f"Confidence: {original_confidence:.2f} → {adjusted_confidence:.2f}. "
                    f"Failed rules: {failed_rules}"
                )
            else:
                logger.debug(
                    f"Issue {issue.id} PASSED validation. "
                    f"Confidence: {original_confidence:.2f} → {adjusted_confidence:.2f}"
                )

            return result

        except Exception as e:
            # Fail-safe: On error, pass issue with low confidence
            logger.error(
                f"Critical error validating issue {issue.id}: {e}. "
                "Failing safe: passing issue with low confidence (0.3)",
                exc_info=True,
            )
            return ValidationResult(
                is_valid=True,
                original_confidence=0.3,
                adjusted_confidence=0.3,
                failed_rules=["ValidationError"],
            )

    def _get_confidence(self, issue: WardenIssue) -> float:
        """
        Extract confidence from issue or use default.

        Args:
            issue: Issue to extract confidence from

        Returns:
            Confidence value in [0.0, 1.0]
        """
        if hasattr(issue, "confidence"):
            confidence = getattr(issue, "confidence", self._default_confidence)
            # Ensure in valid range
            return max(0.0, min(1.0, confidence))

        # No confidence attribute - use default
        logger.debug(
            f"Issue {issue.id} has no confidence attribute. Using default: {self._default_confidence}"
        )
        return self._default_confidence


# ============================================================================
# FACTORY FUNCTION
# ============================================================================


def create_default_validator() -> IssueValidator:
    """
    Create issue validator with default rules.

    Default rules:
    1. ConfidenceThresholdRule (>= 0.5) - Penalty: -1.0
    2. LineNumberRangeRule (> 0) - Penalty: -0.3

    Returns:
        IssueValidator with default rules registered
    """
    validator = IssueValidator(minimum_confidence=0.5, default_confidence=0.7)

    # Add default rules
    validator.add_rule(ConfidenceThresholdRule(minimum_confidence=0.5))
    validator.add_rule(LineNumberRangeRule())

    logger.info("Created default IssueValidator with 2 rules")
    return validator
