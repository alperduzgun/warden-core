"""
Unit tests for SpecFrame suppression support.

Tests suppression loading, matching, and filtering of contract gaps.
"""

import pytest
from warden.validation.frames.spec.models import ContractGap, GapSeverity
from warden.validation.frames.spec.spec_frame import SpecFrame


class TestContractGapSuppressionKey:
    """Test ContractGap.get_suppression_key() method."""

    def test_suppression_key_with_operation_name(self):
        """Test suppression key generation with operation name."""
        gap = ContractGap(
            gap_type="missing_operation",
            severity=GapSeverity.CRITICAL,
            message="Operation missing",
            operation_name="createUser",
        )
        assert gap.get_suppression_key() == "spec:missing_operation:createUser"

    def test_suppression_key_type_mismatch(self):
        """Test suppression key for type mismatch."""
        gap = ContractGap(
            gap_type="type_mismatch",
            severity=GapSeverity.HIGH,
            message="Type mismatch",
            operation_name="getUserById",
        )
        assert gap.get_suppression_key() == "spec:type_mismatch:getUserById"

    def test_suppression_key_without_operation_name(self):
        """Test suppression key generation when operation_name is None."""
        gap = ContractGap(
            gap_type="nullable_mismatch",
            severity=GapSeverity.MEDIUM,
            message="Nullable mismatch",
            operation_name=None,
        )
        assert gap.get_suppression_key() == "spec:nullable_mismatch:unknown"

    def test_suppression_key_various_gap_types(self):
        """Test suppression key for various gap types."""
        gap_types = [
            "missing_operation",
            "type_mismatch",
            "nullable_mismatch",
            "unused",
            "custom_gap_type",
        ]

        for gap_type in gap_types:
            gap = ContractGap(
                gap_type=gap_type,
                severity=GapSeverity.LOW,
                message="Test",
                operation_name="testOp",
            )
            expected = f"spec:{gap_type}:testOp"
            assert gap.get_suppression_key() == expected


class TestSpecFrameSuppressionLoading:
    """Test SpecFrame suppression loading from config."""

    def test_load_suppressions_from_config(self):
        """Test loading suppressions from frame config."""
        config = {
            "platforms": [],
            "suppressions": [
                {
                    "rule": "spec:missing_operation:createUser",
                    "reason": "Legacy endpoint",
                },
                {
                    "rule": "spec:type_mismatch:*",
                    "files": ["src/*.py"],
                    "reason": "Type migration in progress",
                },
            ],
        }

        frame = SpecFrame(config=config)
        assert len(frame.suppressions) == 2
        assert frame.suppressions[0]["rule"] == "spec:missing_operation:createUser"
        assert frame.suppressions[1]["rule"] == "spec:type_mismatch:*"

    def test_load_suppressions_empty_config(self):
        """Test loading suppressions with no suppressions in config."""
        config = {"platforms": []}
        frame = SpecFrame(config=config)
        assert frame.suppressions == []

    def test_load_suppressions_no_config(self):
        """Test loading suppressions with None config."""
        frame = SpecFrame(config=None)
        assert frame.suppressions == []


class TestSpecFrameSuppressionMatching:
    """Test SpecFrame suppression matching logic."""

    def setup_method(self):
        """Setup test fixtures."""
        self.config = {
            "platforms": [],
            "suppressions": [
                # Exact match
                {
                    "rule": "spec:missing_operation:createUser",
                    "reason": "Legacy endpoint",
                },
                # Wildcard for gap type
                {
                    "rule": "spec:type_mismatch:*",
                    "reason": "Type migration",
                },
                # Wildcard for all spec gaps
                {
                    "rule": "spec:*:*",
                    "files": ["legacy/*.py"],
                    "reason": "Legacy code",
                },
                # Global wildcard with file pattern
                {
                    "rule": "*",
                    "files": ["vendor/*.py"],
                    "reason": "Third-party code",
                },
            ],
        }
        self.frame = SpecFrame(config=self.config)

    def test_exact_match_suppression(self):
        """Test exact match suppression."""
        gap = ContractGap(
            gap_type="missing_operation",
            severity=GapSeverity.CRITICAL,
            message="Missing operation",
            operation_name="createUser",
        )
        assert self.frame._is_gap_suppressed(gap) is True

    def test_wildcard_gap_type_match(self):
        """Test wildcard matching for gap type."""
        gap = ContractGap(
            gap_type="type_mismatch",
            severity=GapSeverity.HIGH,
            message="Type mismatch",
            operation_name="getUserById",  # Any operation
        )
        assert self.frame._is_gap_suppressed(gap) is True

    def test_wildcard_all_spec_with_file_match(self):
        """Test wildcard matching all spec gaps with file pattern."""
        gap = ContractGap(
            gap_type="nullable_mismatch",
            severity=GapSeverity.MEDIUM,
            message="Nullable mismatch",
            operation_name="updateUser",
            consumer_file="legacy/api.py",
        )
        assert self.frame._is_gap_suppressed(gap) is True

    def test_wildcard_all_spec_without_file_match(self):
        """Test wildcard matching fails when file doesn't match."""
        gap = ContractGap(
            gap_type="nullable_mismatch",
            severity=GapSeverity.MEDIUM,
            message="Nullable mismatch",
            operation_name="updateUser",
            consumer_file="src/api.py",  # Doesn't match legacy/*.py
        )
        # Should not match spec:*:* because file pattern doesn't match
        # Should match spec:type_mismatch:* if gap_type was type_mismatch
        # But nullable_mismatch doesn't match any rule without file
        assert self.frame._is_gap_suppressed(gap) is False

    def test_global_wildcard_with_file_match(self):
        """Test global wildcard with file pattern match."""
        gap = ContractGap(
            gap_type="unused",
            severity=GapSeverity.LOW,
            message="Unused operation",
            operation_name="deleteUser",
            provider_file="vendor/lib.py",
        )
        assert self.frame._is_gap_suppressed(gap) is True

    def test_no_suppression_match(self):
        """Test gap that doesn't match any suppression."""
        gap = ContractGap(
            gap_type="unused",
            severity=GapSeverity.LOW,
            message="Unused operation",
            operation_name="deleteUser",
            consumer_file="src/api.py",
        )
        assert self.frame._is_gap_suppressed(gap) is False

    def test_suppression_with_no_file_matches_all_files(self):
        """Test suppression without file pattern matches all files."""
        gap = ContractGap(
            gap_type="type_mismatch",
            severity=GapSeverity.HIGH,
            message="Type mismatch",
            operation_name="anyOperation",
            consumer_file="anywhere/file.py",
        )
        # Matches "spec:type_mismatch:*" which has no file restrictions
        assert self.frame._is_gap_suppressed(gap) is True

    def test_suppression_file_pattern_glob(self):
        """Test file pattern glob matching."""
        config = {
            "platforms": [],
            "suppressions": [
                {
                    "rule": "spec:*:*",
                    "files": ["tests/**/*.py"],
                    "reason": "Test files",
                },
            ],
        }
        frame = SpecFrame(config=config)

        gap = ContractGap(
            gap_type="missing_operation",
            severity=GapSeverity.CRITICAL,
            message="Missing",
            operation_name="testOp",
            consumer_file="tests/unit/test_api.py",
        )
        assert frame._is_gap_suppressed(gap) is True

    def test_no_suppressions_configured(self):
        """Test gap suppression when no suppressions configured."""
        frame = SpecFrame(config={"platforms": []})
        gap = ContractGap(
            gap_type="missing_operation",
            severity=GapSeverity.CRITICAL,
            message="Missing",
            operation_name="createUser",
        )
        assert frame._is_gap_suppressed(gap) is False


class TestSuppressionRuleMatching:
    """Test _match_suppression_rule helper method."""

    def setup_method(self):
        """Setup test fixtures."""
        self.frame = SpecFrame(config={"platforms": []})

    def test_exact_match(self):
        """Test exact rule match."""
        rule = "spec:missing_operation:createUser"
        gap_key = "spec:missing_operation:createUser"
        assert self.frame._match_suppression_rule(rule, gap_key) is True

    def test_wildcard_all(self):
        """Test wildcard * matches everything."""
        rule = "*"
        gap_keys = [
            "spec:missing_operation:createUser",
            "spec:type_mismatch:getUserById",
            "anything",
        ]
        for gap_key in gap_keys:
            assert self.frame._match_suppression_rule(rule, gap_key) is True

    def test_wildcard_operation(self):
        """Test wildcard for operation name."""
        rule = "spec:missing_operation:*"
        assert self.frame._match_suppression_rule(rule, "spec:missing_operation:createUser") is True
        assert self.frame._match_suppression_rule(rule, "spec:missing_operation:deleteUser") is True
        assert self.frame._match_suppression_rule(rule, "spec:type_mismatch:createUser") is False

    def test_wildcard_gap_type_and_operation(self):
        """Test wildcard for both gap type and operation."""
        rule = "spec:*:*"
        assert self.frame._match_suppression_rule(rule, "spec:missing_operation:createUser") is True
        assert self.frame._match_suppression_rule(rule, "spec:type_mismatch:getUserById") is True
        assert self.frame._match_suppression_rule(rule, "other:type:op") is False

    def test_no_match(self):
        """Test rule that doesn't match."""
        rule = "spec:missing_operation:createUser"
        gap_key = "spec:missing_operation:deleteUser"
        assert self.frame._match_suppression_rule(rule, gap_key) is False


class TestSuppressionIntegration:
    """Integration tests for suppression in execute flow."""

    @pytest.mark.asyncio
    async def test_suppressed_gaps_metadata_tracking(self):
        """Test that suppressed gaps are tracked in metadata."""
        # This would be an integration test that would need:
        # - Mock platforms
        # - Mock contracts with gaps
        # - Verify metadata["suppressed_gaps"] count
        # Skipped for now - requires full pipeline setup
        pass
