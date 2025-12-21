"""
Unit tests for False Positive Detection - Issue Validator.

Tests all validation rules, IssueValidator orchestrator, and edge cases.
Ensures 80%+ code coverage and Panel JSON compatibility.
"""

import pytest
from datetime import datetime
from typing import List

from warden.core.validation.issue_validator import (
    IssueValidator,
    ValidationResult,
    ValidationRule,
    BaseValidationRule,
    ConfidenceThresholdRule,
    LineNumberRangeRule,
    create_default_validator,
)
from warden.issues.domain.models import WardenIssue, StateTransition
from warden.issues.domain.enums import IssueSeverity, IssueState


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_issue() -> WardenIssue:
    """Create a mock WardenIssue for testing."""
    issue = WardenIssue(
        id="W001",
        type="Security Analysis",
        severity=IssueSeverity.HIGH,
        file_path="src/user_service.py:45",
        message="SQL injection vulnerability detected",
        code_snippet="query = f'SELECT * FROM users WHERE id = {user_id}'",
        code_hash="abc123def456",
        state=IssueState.OPEN,
        first_detected=datetime.now(),
        last_updated=datetime.now(),
        reopen_count=0,
        state_history=[],
    )
    # Add confidence attribute (not in base model yet)
    setattr(issue, "confidence", 0.8)
    return issue


@pytest.fixture
def mock_issue_with_line_number() -> WardenIssue:
    """Create a mock issue with explicit line_number attribute."""
    issue = WardenIssue(
        id="W002",
        type="Code Quality",
        severity=IssueSeverity.MEDIUM,
        file_path="src/utils.py",
        message="Function too complex",
        code_snippet="def complex_function():\n    # ...",
        code_hash="xyz789",
        state=IssueState.OPEN,
        first_detected=datetime.now(),
        last_updated=datetime.now(),
        reopen_count=0,
        state_history=[],
    )
    setattr(issue, "confidence", 0.7)
    setattr(issue, "line_number", 100)
    return issue


# ============================================================================
# TEST VALIDATION RESULT MODEL
# ============================================================================


class TestValidationResult:
    """Test ValidationResult model."""

    def test_create_valid_result(self):
        """Test creating a valid ValidationResult."""
        result = ValidationResult(
            is_valid=True,
            original_confidence=0.8,
            adjusted_confidence=0.7,
            failed_rules=["Rule1"],
        )

        assert result.is_valid is True
        assert result.original_confidence == 0.8
        assert result.adjusted_confidence == 0.7
        assert result.failed_rules == ["Rule1"]

    def test_validation_result_post_init_clamps_confidence(self):
        """Test that __post_init__ clamps adjusted_confidence to [0.0, 1.0]."""
        result = ValidationResult(
            is_valid=False,
            original_confidence=0.8,
            adjusted_confidence=-0.2,  # Negative value
            failed_rules=[],
        )

        assert result.adjusted_confidence == 0.0  # Clamped to 0.0

    def test_validation_result_invalid_original_confidence(self):
        """Test that invalid original_confidence raises ValueError."""
        with pytest.raises(ValueError, match="original_confidence must be in"):
            ValidationResult(
                is_valid=True,
                original_confidence=1.5,  # Invalid
                adjusted_confidence=0.5,
                failed_rules=[],
            )

    def test_validation_result_to_json(self):
        """Test Panel JSON serialization (camelCase)."""
        result = ValidationResult(
            is_valid=True,
            original_confidence=0.8,
            adjusted_confidence=0.7,
            failed_rules=["ConfidenceThreshold"],
        )

        json_data = result.to_json()

        # Check camelCase keys
        assert json_data["isValid"] is True
        assert json_data["originalConfidence"] == 0.8
        assert json_data["adjustedConfidence"] == 0.7
        assert json_data["failedRules"] == ["ConfidenceThreshold"]


# ============================================================================
# TEST BASE VALIDATION RULE
# ============================================================================


class TestBaseValidationRule:
    """Test BaseValidationRule abstract class."""

    def test_base_rule_initialization(self):
        """Test BaseValidationRule can be initialized via subclass."""

        class TestRule(BaseValidationRule):
            def validate(self, issue: WardenIssue) -> bool:
                return True

        rule = TestRule(name="TestRule", confidence_penalty=-0.5)

        assert rule.name == "TestRule"
        assert rule.confidence_penalty == -0.5

    def test_base_rule_invalid_penalty_too_low(self):
        """Test that penalty < -1.0 raises ValueError."""

        class TestRule(BaseValidationRule):
            def validate(self, issue: WardenIssue) -> bool:
                return True

        with pytest.raises(ValueError, match="confidence_penalty must be in"):
            TestRule(name="TestRule", confidence_penalty=-1.5)

    def test_base_rule_invalid_penalty_too_high(self):
        """Test that penalty > -0.2 raises ValueError."""

        class TestRule(BaseValidationRule):
            def validate(self, issue: WardenIssue) -> bool:
                return True

        with pytest.raises(ValueError, match="confidence_penalty must be in"):
            TestRule(name="TestRule", confidence_penalty=-0.1)


# ============================================================================
# TEST CONFIDENCE THRESHOLD RULE
# ============================================================================


class TestConfidenceThresholdRule:
    """Test ConfidenceThresholdRule."""

    def test_rule_initialization(self):
        """Test rule initialization with default threshold."""
        rule = ConfidenceThresholdRule()

        assert rule.name == "ConfidenceThreshold(>=0.5)"
        assert rule.confidence_penalty == -1.0

    def test_rule_custom_threshold(self):
        """Test rule with custom minimum confidence."""
        rule = ConfidenceThresholdRule(minimum_confidence=0.7)

        assert rule.name == "ConfidenceThreshold(>=0.7)"

    def test_rule_invalid_threshold(self):
        """Test that invalid threshold raises ValueError."""
        with pytest.raises(ValueError, match="minimum_confidence must be in"):
            ConfidenceThresholdRule(minimum_confidence=1.5)

    def test_validate_passes_with_sufficient_confidence(self, mock_issue):
        """Test validation passes when confidence >= threshold."""
        rule = ConfidenceThresholdRule(minimum_confidence=0.5)
        setattr(mock_issue, "confidence", 0.8)

        assert rule.validate(mock_issue) is True

    def test_validate_fails_with_insufficient_confidence(self, mock_issue):
        """Test validation fails when confidence < threshold."""
        rule = ConfidenceThresholdRule(minimum_confidence=0.5)
        setattr(mock_issue, "confidence", 0.3)

        assert rule.validate(mock_issue) is False

    def test_validate_exact_threshold(self, mock_issue):
        """Test validation passes when confidence == threshold."""
        rule = ConfidenceThresholdRule(minimum_confidence=0.5)
        setattr(mock_issue, "confidence", 0.5)

        assert rule.validate(mock_issue) is True

    def test_validate_missing_confidence_attribute(self, mock_issue):
        """Test validation fails when issue lacks confidence attribute."""
        rule = ConfidenceThresholdRule()
        delattr(mock_issue, "confidence")  # Remove confidence

        assert rule.validate(mock_issue) is False


# ============================================================================
# TEST LINE NUMBER RANGE RULE
# ============================================================================


class TestLineNumberRangeRule:
    """Test LineNumberRangeRule."""

    def test_rule_initialization(self):
        """Test rule initialization."""
        rule = LineNumberRangeRule()

        assert rule.name == "LineNumberRange(>0)"
        assert rule.confidence_penalty == -0.3

    def test_validate_passes_with_valid_line_number(self, mock_issue_with_line_number):
        """Test validation passes with positive line_number."""
        rule = LineNumberRangeRule()

        assert rule.validate(mock_issue_with_line_number) is True

    def test_validate_passes_with_line_number_from_file_path(self, mock_issue):
        """Test extraction of line number from file_path (e.g., 'file.py:45')."""
        rule = LineNumberRangeRule()

        assert rule.validate(mock_issue) is True

    def test_validate_fails_with_zero_line_number(self, mock_issue_with_line_number):
        """Test validation fails when line_number is 0."""
        rule = LineNumberRangeRule()
        setattr(mock_issue_with_line_number, "line_number", 0)

        assert rule.validate(mock_issue_with_line_number) is False

    def test_validate_fails_with_negative_line_number(self, mock_issue_with_line_number):
        """Test validation fails when line_number is negative."""
        rule = LineNumberRangeRule()
        setattr(mock_issue_with_line_number, "line_number", -10)

        assert rule.validate(mock_issue_with_line_number) is False

    def test_validate_fails_with_no_line_number(self, mock_issue):
        """Test validation fails when no line number found."""
        rule = LineNumberRangeRule()
        mock_issue.file_path = "src/utils.py"  # No line number

        assert rule.validate(mock_issue) is False

    def test_validate_invalid_file_path_format(self, mock_issue):
        """Test validation handles invalid file_path format gracefully."""
        rule = LineNumberRangeRule()
        mock_issue.file_path = "src/utils.py:not_a_number"

        assert rule.validate(mock_issue) is False


# ============================================================================
# TEST ISSUE VALIDATOR ORCHESTRATOR
# ============================================================================


class TestIssueValidator:
    """Test IssueValidator orchestrator."""

    def test_validator_initialization(self):
        """Test validator initialization with default values."""
        validator = IssueValidator()

        assert validator._minimum_confidence == 0.5
        assert validator._default_confidence == 0.7
        assert len(validator._rules) == 0

    def test_validator_custom_thresholds(self):
        """Test validator with custom thresholds."""
        validator = IssueValidator(minimum_confidence=0.6, default_confidence=0.8)

        assert validator._minimum_confidence == 0.6
        assert validator._default_confidence == 0.8

    def test_validator_invalid_minimum_confidence(self):
        """Test that invalid minimum_confidence raises ValueError."""
        with pytest.raises(ValueError, match="minimum_confidence must be in"):
            IssueValidator(minimum_confidence=1.5)

    def test_validator_invalid_default_confidence(self):
        """Test that invalid default_confidence raises ValueError."""
        with pytest.raises(ValueError, match="default_confidence must be in"):
            IssueValidator(default_confidence=-0.5)

    def test_add_rule(self):
        """Test adding validation rules."""
        validator = IssueValidator()
        rule = ConfidenceThresholdRule()

        validator.add_rule(rule)

        assert len(validator._rules) == 1
        assert validator._rules[0] == rule

    def test_validate_passes_all_rules(self, mock_issue):
        """Test validation passes when all rules pass."""
        validator = IssueValidator(minimum_confidence=0.5)
        validator.add_rule(ConfidenceThresholdRule(minimum_confidence=0.5))
        validator.add_rule(LineNumberRangeRule())

        setattr(mock_issue, "confidence", 0.8)

        result = validator.validate(mock_issue)

        assert result.is_valid is True
        assert result.original_confidence == 0.8
        assert result.adjusted_confidence == 0.8
        assert len(result.failed_rules) == 0

    def test_validate_fails_single_rule(self, mock_issue):
        """Test validation when one rule fails."""
        validator = IssueValidator(minimum_confidence=0.5)
        validator.add_rule(ConfidenceThresholdRule(minimum_confidence=0.5))
        validator.add_rule(LineNumberRangeRule())

        setattr(mock_issue, "confidence", 0.8)
        mock_issue.file_path = "src/utils.py"  # No line number

        result = validator.validate(mock_issue)

        # Original: 0.8, Penalty: -0.3, Adjusted: 0.5
        assert result.is_valid is True  # Still passes (>= 0.5)
        assert result.original_confidence == 0.8
        assert result.adjusted_confidence == 0.5
        assert len(result.failed_rules) == 1
        assert "LineNumberRange(>0)" in result.failed_rules

    def test_validate_fails_multiple_rules(self, mock_issue):
        """Test validation when multiple rules fail."""
        validator = IssueValidator(minimum_confidence=0.5)
        validator.add_rule(ConfidenceThresholdRule(minimum_confidence=0.9))
        validator.add_rule(LineNumberRangeRule())

        setattr(mock_issue, "confidence", 0.6)
        mock_issue.file_path = "src/utils.py"  # No line number

        result = validator.validate(mock_issue)

        # Original: 0.6, Penalties: -1.0 + -0.3 = -1.3, Adjusted: 0.0 (clamped)
        assert result.is_valid is False
        assert result.original_confidence == 0.6
        assert result.adjusted_confidence == 0.0
        assert len(result.failed_rules) == 2

    def test_validate_issue_rejected_as_false_positive(self, mock_issue):
        """Test issue rejected when adjusted_confidence < minimum."""
        validator = IssueValidator(minimum_confidence=0.5)
        validator.add_rule(ConfidenceThresholdRule(minimum_confidence=0.5))

        setattr(mock_issue, "confidence", 0.3)  # Below threshold

        result = validator.validate(mock_issue)

        # Original: 0.3, Penalty: -1.0, Adjusted: 0.0 (clamped)
        assert result.is_valid is False
        assert result.adjusted_confidence == 0.0

    def test_validate_uses_default_confidence(self, mock_issue):
        """Test validator uses default_confidence when issue has no confidence."""
        validator = IssueValidator(minimum_confidence=0.5, default_confidence=0.7)
        validator.add_rule(LineNumberRangeRule())

        delattr(mock_issue, "confidence")  # Remove confidence

        result = validator.validate(mock_issue)

        # Should use default_confidence (0.7)
        assert result.original_confidence == 0.7
        assert result.adjusted_confidence == 0.7

    def test_validate_fail_safe_on_exception(self, mock_issue):
        """Test fail-safe behavior when validation raises exception."""

        class BrokenRule(BaseValidationRule):
            def validate(self, issue: WardenIssue) -> bool:
                raise RuntimeError("Intentional error")

        validator = IssueValidator()
        validator.add_rule(BrokenRule(name="BrokenRule", confidence_penalty=-0.5))

        setattr(mock_issue, "confidence", 0.8)

        result = validator.validate(mock_issue)

        # Should continue despite rule error
        assert result.is_valid is True
        assert result.original_confidence == 0.8

    def test_validate_fail_safe_on_critical_error(self, mock_issue):
        """Test fail-safe when entire validation fails."""
        validator = IssueValidator()

        # Force an error by passing invalid issue
        invalid_issue = None

        result = validator.validate(invalid_issue)

        # Should fail safe with low confidence
        assert result.is_valid is True
        assert result.adjusted_confidence == 0.3
        assert "ValidationError" in result.failed_rules


# ============================================================================
# TEST FACTORY FUNCTION
# ============================================================================


class TestCreateDefaultValidator:
    """Test create_default_validator factory function."""

    def test_creates_validator_with_default_rules(self):
        """Test factory creates validator with 2 default rules."""
        validator = create_default_validator()

        assert validator._minimum_confidence == 0.5
        assert validator._default_confidence == 0.7
        assert len(validator._rules) == 2

    def test_default_rules_are_correct(self):
        """Test default rules are ConfidenceThreshold and LineNumberRange."""
        validator = create_default_validator()

        rule_names = [rule.name for rule in validator._rules]

        assert "ConfidenceThreshold(>=0.5)" in rule_names
        assert "LineNumberRange(>0)" in rule_names

    def test_default_validator_validates_issue(self, mock_issue):
        """Test default validator can validate an issue."""
        validator = create_default_validator()

        setattr(mock_issue, "confidence", 0.8)

        result = validator.validate(mock_issue)

        assert result.is_valid is True
        assert result.original_confidence == 0.8


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestIssueValidatorIntegration:
    """Integration tests for full validation workflow."""

    def test_full_validation_workflow_pass(self, mock_issue):
        """Test complete validation workflow - issue passes."""
        validator = create_default_validator()
        setattr(mock_issue, "confidence", 0.9)

        result = validator.validate(mock_issue)

        assert result.is_valid is True
        assert result.adjusted_confidence >= 0.5

    def test_full_validation_workflow_reject(self, mock_issue):
        """Test complete validation workflow - issue rejected."""
        validator = create_default_validator()
        setattr(mock_issue, "confidence", 0.2)  # Very low confidence

        result = validator.validate(mock_issue)

        assert result.is_valid is False
        assert result.adjusted_confidence < 0.5

    def test_panel_json_roundtrip(self, mock_issue):
        """Test Panel JSON serialization roundtrip."""
        validator = create_default_validator()
        setattr(mock_issue, "confidence", 0.6)

        result = validator.validate(mock_issue)
        json_data = result.to_json()

        # Check camelCase keys
        assert "isValid" in json_data
        assert "originalConfidence" in json_data
        assert "adjustedConfidence" in json_data
        assert "failedRules" in json_data

        # Values should match
        assert json_data["isValid"] == result.is_valid
        assert json_data["originalConfidence"] == result.original_confidence
        assert json_data["adjustedConfidence"] == result.adjusted_confidence


# ============================================================================
# TEST BATCH VALIDATOR
# ============================================================================


class TestBatchValidator:
    """Test BatchValidator for parallel validation."""

    @pytest.mark.asyncio
    async def test_validate_batch_empty_list(self):
        """Test batch validation with empty list."""
        from warden.core.validation.batch_validator import BatchValidator

        validator = BatchValidator()
        result = await validator.validate_batch([])

        assert result.metrics.total_issues == 0
        assert result.metrics.valid_issues == 0
        assert result.metrics.rejected_issues == 0
        assert result.metrics.rejection_rate == 0.0
        assert len(result.valid_issues) == 0
        assert len(result.rejected_issues) == 0

    @pytest.mark.asyncio
    async def test_validate_batch_all_valid(self):
        """Test batch validation with all valid issues."""
        from warden.core.validation.batch_validator import BatchValidator

        # Create 10 valid issues
        issues: List[WardenIssue] = []
        for i in range(10):
            issue = WardenIssue(
                id=f"W{i:03d}",
                type="Test",
                severity=IssueSeverity.MEDIUM,
                file_path=f"src/file{i}.py:10",
                message="Test issue message",
                code_snippet="def test(): pass",
                code_hash=f"hash{i}",
                state=IssueState.OPEN,
                first_detected=datetime.now(),
                last_updated=datetime.now(),
                reopen_count=0,
                state_history=[],
                confidence=0.8,
                line_number=10,
            )
            issues.append(issue)

        validator = BatchValidator()
        result = await validator.validate_batch(issues)

        assert result.metrics.total_issues == 10
        assert result.metrics.valid_issues == 10
        assert result.metrics.rejected_issues == 0
        assert result.metrics.rejection_rate == 0.0
        assert len(result.valid_issues) == 10
        assert len(result.rejected_issues) == 0

    @pytest.mark.asyncio
    async def test_validate_batch_mixed_results(self):
        """Test batch validation with mixed valid/invalid issues."""
        from warden.core.validation.batch_validator import BatchValidator

        # Create 5 valid and 5 invalid issues
        issues: List[WardenIssue] = []
        for i in range(10):
            confidence = 0.8 if i < 5 else 0.2  # First 5 valid, last 5 invalid
            issue = WardenIssue(
                id=f"W{i:03d}",
                type="Test",
                severity=IssueSeverity.MEDIUM,
                file_path=f"src/file{i}.py:10",
                message="Test issue message",
                code_snippet="def test(): pass",
                code_hash=f"hash{i}",
                state=IssueState.OPEN,
                first_detected=datetime.now(),
                last_updated=datetime.now(),
                reopen_count=0,
                state_history=[],
                confidence=confidence,
                line_number=10,
            )
            issues.append(issue)

        validator = BatchValidator()
        result = await validator.validate_batch(issues)

        assert result.metrics.total_issues == 10
        assert result.metrics.valid_issues == 5
        assert result.metrics.rejected_issues == 5
        assert result.metrics.rejection_rate == 50.0
        assert len(result.valid_issues) == 5
        assert len(result.rejected_issues) == 5

    @pytest.mark.asyncio
    async def test_validate_batch_metrics_calculation(self):
        """Test batch metrics are calculated correctly."""
        from warden.core.validation.batch_validator import BatchValidator

        # Create issues with different confidences
        confidences = [0.9, 0.8, 0.7, 0.6, 0.5]
        issues: List[WardenIssue] = []
        for i, conf in enumerate(confidences):
            issue = WardenIssue(
                id=f"W{i:03d}",
                type="Test",
                severity=IssueSeverity.MEDIUM,
                file_path=f"src/file{i}.py:10",
                message="Test issue message",
                code_snippet="def test(): pass",
                code_hash=f"hash{i}",
                state=IssueState.OPEN,
                first_detected=datetime.now(),
                last_updated=datetime.now(),
                reopen_count=0,
                state_history=[],
                confidence=conf,
                line_number=10,
            )
            issues.append(issue)

        validator = BatchValidator()
        result = await validator.validate_batch(issues)

        # Check metrics
        assert result.metrics.total_issues == 5
        assert result.metrics.average_original_confidence == 0.7  # (0.9+0.8+0.7+0.6+0.5)/5
        assert result.metrics.processing_time_ms > 0

    @pytest.mark.asyncio
    async def test_validate_batch_panel_json_compatibility(self):
        """Test batch validation result Panel JSON serialization."""
        from warden.core.validation.batch_validator import BatchValidator

        # Create 2 issues
        issues: List[WardenIssue] = []
        for i in range(2):
            issue = WardenIssue(
                id=f"W{i:03d}",
                type="Test",
                severity=IssueSeverity.MEDIUM,
                file_path=f"src/file{i}.py:10",
                message="Test issue message",
                code_snippet="def test(): pass",
                code_hash=f"hash{i}",
                state=IssueState.OPEN,
                first_detected=datetime.now(),
                last_updated=datetime.now(),
                reopen_count=0,
                state_history=[],
                confidence=0.8,
                line_number=10,
            )
            issues.append(issue)

        validator = BatchValidator()
        result = await validator.validate_batch(issues)
        json_data = result.to_json()

        # Check structure
        assert "results" in json_data
        assert "metrics" in json_data
        assert "validIssues" in json_data
        assert "rejectedIssues" in json_data

        # Check metrics camelCase
        metrics = json_data["metrics"]
        assert "totalIssues" in metrics
        assert "validIssues" in metrics
        assert "rejectedIssues" in metrics
        assert "rejectionRate" in metrics
        assert "averageOriginalConfidence" in metrics
        assert "averageAdjustedConfidence" in metrics
        assert "averageConfidenceDegradation" in metrics
        assert "processingTimeMs" in metrics

    @pytest.mark.asyncio
    async def test_validate_batch_contexts_length_mismatch(self):
        """Test error when contexts length doesn't match issues."""
        from warden.core.validation.batch_validator import BatchValidator

        issue = WardenIssue(
            id="W001",
            type="Test",
            severity=IssueSeverity.MEDIUM,
            file_path="src/file.py:10",
            message="Test issue",
            code_snippet="def test(): pass",
            code_hash="hash",
            state=IssueState.OPEN,
            first_detected=datetime.now(),
            last_updated=datetime.now(),
            reopen_count=0,
            state_history=[],
            confidence=0.8,
            line_number=10,
        )

        validator = BatchValidator()

        with pytest.raises(ValueError, match="Contexts length"):
            await validator.validate_batch([issue], contexts=[{}, {}])  # 2 contexts for 1 issue

    @pytest.mark.asyncio
    async def test_validate_batch_concurrency(self):
        """Test batch validator respects max_concurrency."""
        from warden.core.validation.batch_validator import BatchValidator

        # Create 20 issues
        issues: List[WardenIssue] = []
        for i in range(20):
            issue = WardenIssue(
                id=f"W{i:03d}",
                type="Test",
                severity=IssueSeverity.MEDIUM,
                file_path=f"src/file{i}.py:10",
                message="Test issue message",
                code_snippet="def test(): pass",
                code_hash=f"hash{i}",
                state=IssueState.OPEN,
                first_detected=datetime.now(),
                last_updated=datetime.now(),
                reopen_count=0,
                state_history=[],
                confidence=0.8,
                line_number=10,
            )
            issues.append(issue)

        # Validator with max_concurrency=5
        validator = BatchValidator(max_concurrency=5)
        result = await validator.validate_batch(issues)

        # Should still process all issues
        assert result.metrics.total_issues == 20
        assert len(result.results) == 20
