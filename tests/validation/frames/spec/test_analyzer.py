"""
Tests for GapAnalyzer - Contract Comparison.

Tests gap detection between consumer and provider contracts.
"""

import pytest

from warden.validation.frames.spec import (
    Contract,
    OperationDefinition,
    ModelDefinition,
    FieldDefinition,
    EnumDefinition,
    OperationType,
    GapSeverity,
    GapAnalyzer,
    GapAnalyzerConfig,
    analyze_contracts,
)


class TestGapAnalyzerOperations:
    """Tests for operation matching and gap detection."""

    def test_exact_operation_match(self):
        """Test exact operation name matching."""
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="getUsers",
                    operation_type=OperationType.QUERY,
                ),
                OperationDefinition(
                    name="createUser",
                    operation_type=OperationType.COMMAND,
                ),
            ],
        )

        provider = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="getUsers",
                    operation_type=OperationType.QUERY,
                ),
                OperationDefinition(
                    name="createUser",
                    operation_type=OperationType.COMMAND,
                ),
            ],
        )

        result = analyze_contracts(consumer, provider)

        assert result.matched_operations == 2
        assert result.missing_operations == 0
        assert result.unused_operations == 0

    def test_missing_operation_detection(self):
        """Test detection of missing operations."""
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="getUsers",
                    operation_type=OperationType.QUERY,
                ),
                OperationDefinition(
                    name="deleteUser",
                    operation_type=OperationType.COMMAND,
                ),
            ],
        )

        provider = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="getUsers",
                    operation_type=OperationType.QUERY,
                ),
            ],
        )

        result = analyze_contracts(consumer, provider)

        assert result.matched_operations == 1
        assert result.missing_operations == 1

        # Check gap details
        missing_gaps = [g for g in result.gaps if g.gap_type == "missing_operation"]
        assert len(missing_gaps) == 1
        assert missing_gaps[0].severity == GapSeverity.CRITICAL
        assert "deleteUser" in missing_gaps[0].message

    def test_unused_operation_detection(self):
        """Test detection of unused operations."""
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="getUsers",
                    operation_type=OperationType.QUERY,
                ),
            ],
        )

        provider = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="getUsers",
                    operation_type=OperationType.QUERY,
                ),
                OperationDefinition(
                    name="getProducts",
                    operation_type=OperationType.QUERY,
                ),
                OperationDefinition(
                    name="getOrders",
                    operation_type=OperationType.QUERY,
                ),
            ],
        )

        result = analyze_contracts(consumer, provider)

        assert result.matched_operations == 1
        assert result.unused_operations == 2

        # Unused operations should be LOW severity
        unused_gaps = [g for g in result.gaps if g.gap_type == "unused_operation"]
        assert len(unused_gaps) == 2
        assert all(g.severity == GapSeverity.LOW for g in unused_gaps)

    def test_fuzzy_operation_matching(self):
        """Test fuzzy matching of similar operation names."""
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="fetchUsers",  # Different prefix
                    operation_type=OperationType.QUERY,
                ),
                OperationDefinition(
                    name="loadUserList",  # Different suffix
                    operation_type=OperationType.QUERY,
                ),
            ],
        )

        provider = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="getUsers",
                    operation_type=OperationType.QUERY,
                ),
                OperationDefinition(
                    name="getUserList",
                    operation_type=OperationType.QUERY,
                ),
            ],
        )

        config = GapAnalyzerConfig(
            enable_fuzzy_matching=True,
            fuzzy_match_threshold=0.7,
        )
        result = analyze_contracts(consumer, provider, config)

        # Should match through fuzzy matching
        assert result.matched_operations >= 1

    def test_fuzzy_matching_disabled(self):
        """Test that fuzzy matching can be disabled."""
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="fetchUsers",
                    operation_type=OperationType.QUERY,
                ),
            ],
        )

        provider = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="getUsers",
                    operation_type=OperationType.QUERY,
                ),
            ],
        )

        config = GapAnalyzerConfig(enable_fuzzy_matching=False)
        result = analyze_contracts(consumer, provider, config)

        # Without fuzzy matching, these shouldn't match
        assert result.matched_operations == 0
        assert result.missing_operations == 1


class TestGapAnalyzerTypes:
    """Tests for type compatibility checking."""

    def test_input_type_mismatch(self):
        """Test detection of input type mismatches."""
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="createUser",
                    operation_type=OperationType.COMMAND,
                    input_type="CreateUserInput",
                ),
            ],
        )

        provider = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="createUser",
                    operation_type=OperationType.COMMAND,
                    input_type="UserDto",
                ),
            ],
        )

        result = analyze_contracts(consumer, provider)

        type_gaps = [g for g in result.gaps if "type" in g.gap_type]
        assert len(type_gaps) >= 1
        assert any(g.severity == GapSeverity.HIGH for g in type_gaps)

    def test_output_type_mismatch(self):
        """Test detection of output type mismatches."""
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="getUser",
                    operation_type=OperationType.QUERY,
                    output_type="UserResponse",
                ),
            ],
        )

        provider = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="getUser",
                    operation_type=OperationType.QUERY,
                    output_type="UserEntity",
                ),
            ],
        )

        result = analyze_contracts(consumer, provider)

        type_gaps = [g for g in result.gaps if "type" in g.gap_type]
        assert len(type_gaps) >= 1

    def test_compatible_primitive_types(self):
        """Test that compatible primitive types match."""
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="getCount",
                    operation_type=OperationType.QUERY,
                    output_type="int",
                ),
            ],
        )

        provider = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="getCount",
                    operation_type=OperationType.QUERY,
                    output_type="integer",  # Should be compatible with int
                ),
            ],
        )

        result = analyze_contracts(consumer, provider)

        # int and integer should be compatible
        type_gaps = [g for g in result.gaps if "type" in g.gap_type]
        assert len(type_gaps) == 0


class TestGapAnalyzerModels:
    """Tests for model field comparison."""

    def test_missing_field_detection(self):
        """Test detection of missing fields in models."""
        consumer = Contract(
            name="consumer",
            models=[
                ModelDefinition(
                    name="User",
                    fields=[
                        FieldDefinition(name="id", type_name="string"),
                        FieldDefinition(name="name", type_name="string"),
                        FieldDefinition(name="email", type_name="string"),
                        FieldDefinition(name="avatar", type_name="string"),  # Extra field
                    ],
                ),
            ],
        )

        provider = Contract(
            name="provider",
            models=[
                ModelDefinition(
                    name="User",
                    fields=[
                        FieldDefinition(name="id", type_name="string"),
                        FieldDefinition(name="name", type_name="string"),
                        FieldDefinition(name="email", type_name="string"),
                        # Missing 'avatar' field
                    ],
                ),
            ],
        )

        result = analyze_contracts(consumer, provider)

        missing_field_gaps = [g for g in result.gaps if g.gap_type == "missing_field"]
        assert len(missing_field_gaps) == 1
        assert "avatar" in missing_field_gaps[0].message

    def test_field_type_mismatch(self):
        """Test detection of field type mismatches."""
        consumer = Contract(
            name="consumer",
            models=[
                ModelDefinition(
                    name="Product",
                    fields=[
                        FieldDefinition(name="id", type_name="string"),
                        FieldDefinition(name="price", type_name="float"),
                    ],
                ),
            ],
        )

        provider = Contract(
            name="provider",
            models=[
                ModelDefinition(
                    name="Product",
                    fields=[
                        FieldDefinition(name="id", type_name="string"),
                        FieldDefinition(name="price", type_name="string"),  # Wrong type
                    ],
                ),
            ],
        )

        result = analyze_contracts(consumer, provider)

        field_type_gaps = [g for g in result.gaps if g.gap_type == "field_type_mismatch"]
        assert len(field_type_gaps) == 1
        assert "price" in field_type_gaps[0].message

    def test_nullable_mismatch(self):
        """Test detection of nullable/optional mismatches."""
        consumer = Contract(
            name="consumer",
            models=[
                ModelDefinition(
                    name="User",
                    fields=[
                        FieldDefinition(name="id", type_name="string", is_optional=False),
                        FieldDefinition(name="name", type_name="string", is_optional=False),
                    ],
                ),
            ],
        )

        provider = Contract(
            name="provider",
            models=[
                ModelDefinition(
                    name="User",
                    fields=[
                        FieldDefinition(name="id", type_name="string", is_optional=False),
                        FieldDefinition(name="name", type_name="string", is_optional=True),  # Provider says optional
                    ],
                ),
            ],
        )

        result = analyze_contracts(consumer, provider)

        nullable_gaps = [g for g in result.gaps if g.gap_type == "nullable_mismatch"]
        assert len(nullable_gaps) == 1
        assert nullable_gaps[0].severity == GapSeverity.MEDIUM


class TestGapAnalyzerEnums:
    """Tests for enum comparison."""

    def test_missing_enum_value(self):
        """Test detection of missing enum values."""
        consumer = Contract(
            name="consumer",
            enums=[
                EnumDefinition(
                    name="OrderStatus",
                    values=["PENDING", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED"],
                ),
            ],
        )

        provider = Contract(
            name="provider",
            enums=[
                EnumDefinition(
                    name="OrderStatus",
                    values=["PENDING", "PROCESSING", "SHIPPED"],  # Missing values
                ),
            ],
        )

        result = analyze_contracts(consumer, provider)

        enum_gaps = [g for g in result.gaps if g.gap_type == "enum_value_missing"]
        assert len(enum_gaps) == 1
        assert "DELIVERED" in enum_gaps[0].message or "CANCELLED" in enum_gaps[0].message

    def test_extra_enum_value(self):
        """Test detection of extra enum values in provider."""
        consumer = Contract(
            name="consumer",
            enums=[
                EnumDefinition(
                    name="Status",
                    values=["ACTIVE", "INACTIVE"],
                ),
            ],
        )

        provider = Contract(
            name="provider",
            enums=[
                EnumDefinition(
                    name="Status",
                    values=["ACTIVE", "INACTIVE", "SUSPENDED", "ARCHIVED"],
                ),
            ],
        )

        result = analyze_contracts(consumer, provider)

        extra_gaps = [g for g in result.gaps if g.gap_type == "enum_value_extra"]
        assert len(extra_gaps) == 1
        assert extra_gaps[0].severity == GapSeverity.LOW


class TestGapAnalyzerConfig:
    """Tests for analyzer configuration."""

    def test_custom_severity_levels(self):
        """Test custom severity level configuration."""
        config = GapAnalyzerConfig(
            missing_operation_severity=GapSeverity.HIGH,  # Custom: HIGH instead of CRITICAL
            unused_operation_severity=GapSeverity.MEDIUM,  # Custom: MEDIUM instead of LOW
        )

        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(name="getUsers", operation_type=OperationType.QUERY),
            ],
        )

        provider = Contract(
            name="provider",
            operations=[
                OperationDefinition(name="getProducts", operation_type=OperationType.QUERY),
            ],
        )

        result = analyze_contracts(consumer, provider, config)

        missing_gaps = [g for g in result.gaps if g.gap_type == "missing_operation"]
        assert missing_gaps[0].severity == GapSeverity.HIGH

        unused_gaps = [g for g in result.gaps if g.gap_type == "unused_operation"]
        assert unused_gaps[0].severity == GapSeverity.MEDIUM

    def test_disable_field_checks(self):
        """Test disabling field type checks."""
        config = GapAnalyzerConfig(
            check_field_types=False,
            check_field_optionality=False,
        )

        consumer = Contract(
            name="consumer",
            models=[
                ModelDefinition(
                    name="User",
                    fields=[
                        FieldDefinition(name="id", type_name="int", is_optional=False),
                    ],
                ),
            ],
        )

        provider = Contract(
            name="provider",
            models=[
                ModelDefinition(
                    name="User",
                    fields=[
                        FieldDefinition(name="id", type_name="string", is_optional=True),
                    ],
                ),
            ],
        )

        result = analyze_contracts(consumer, provider, config)

        # No field-related gaps should be detected
        field_gaps = [g for g in result.gaps if "field" in g.gap_type]
        assert len(field_gaps) == 0


class TestGapAnalyzerResult:
    """Tests for analysis result structure."""

    def test_result_has_critical_gaps(self):
        """Test has_critical_gaps method."""
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(name="deleteUser", operation_type=OperationType.COMMAND),
            ],
        )

        provider = Contract(name="provider", operations=[])

        result = analyze_contracts(consumer, provider)

        assert result.has_critical_gaps() is True

    def test_result_summary(self):
        """Test result summary generation."""
        consumer = Contract(
            name="test-consumer",
            operations=[
                OperationDefinition(name="op1", operation_type=OperationType.QUERY),
                OperationDefinition(name="op2", operation_type=OperationType.QUERY),
            ],
        )

        provider = Contract(
            name="test-provider",
            operations=[
                OperationDefinition(name="op1", operation_type=OperationType.QUERY),
                OperationDefinition(name="op3", operation_type=OperationType.QUERY),
            ],
        )

        result = analyze_contracts(consumer, provider)

        summary = result.summary()

        assert "test-consumer" in summary
        assert "test-provider" in summary
        assert "Matched" in summary
        assert "Missing" in summary

    def test_gap_to_finding_conversion(self):
        """Test conversion of gaps to finding dictionaries."""
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="getUsers",
                    operation_type=OperationType.QUERY,
                    source_file="src/api.ts",
                    source_line=10,
                ),
            ],
        )

        provider = Contract(name="provider", operations=[])

        result = analyze_contracts(consumer, provider)

        assert len(result.gaps) > 0

        gap = result.gaps[0]
        finding_dict = gap.to_finding_dict()

        assert "severity" in finding_dict
        assert "message" in finding_dict
        assert "gap_type" in finding_dict


class TestGapAnalyzerEdgeCases:
    """Tests for edge cases."""

    def test_empty_contracts(self):
        """Test analysis of empty contracts."""
        consumer = Contract(name="consumer")
        provider = Contract(name="provider")

        result = analyze_contracts(consumer, provider)

        assert result.matched_operations == 0
        assert result.missing_operations == 0
        assert result.unused_operations == 0
        assert len(result.gaps) == 0

    def test_consumer_only(self):
        """Test when provider has no operations."""
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(name="op1", operation_type=OperationType.QUERY),
                OperationDefinition(name="op2", operation_type=OperationType.COMMAND),
            ],
        )

        provider = Contract(name="provider")

        result = analyze_contracts(consumer, provider)

        assert result.missing_operations == 2
        assert result.has_critical_gaps() is True

    def test_provider_only(self):
        """Test when consumer has no operations."""
        consumer = Contract(name="consumer")

        provider = Contract(
            name="provider",
            operations=[
                OperationDefinition(name="op1", operation_type=OperationType.QUERY),
            ],
        )

        result = analyze_contracts(consumer, provider)

        assert result.unused_operations == 1
        assert result.has_critical_gaps() is False  # Unused is LOW severity
