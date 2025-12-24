"""
Tests for CodeCharacteristics model.

Tests characteristic detection, risk assessment, and serialization.
"""

import pytest

from warden.validation.domain.code_characteristics import CodeCharacteristics


class TestCodeCharacteristicsCreation:
    """Test CodeCharacteristics creation and defaults."""

    def test_default_characteristics(self):
        """Test default characteristics (all False)."""
        chars = CodeCharacteristics()

        assert chars.has_async_operations is False
        assert chars.has_external_api_calls is False
        assert chars.has_network_operations is False
        assert chars.has_user_input is False
        assert chars.has_database_operations is False
        assert chars.has_file_operations is False
        assert chars.has_collection_processing is False
        assert chars.has_financial_calculations is False
        assert chars.has_authentication_logic is False
        assert chars.has_cryptographic_operations is False
        assert chars.complexity_score == 0
        assert chars.additional_characteristics == []

    def test_empty_characteristics(self):
        """Test empty() factory method."""
        chars = CodeCharacteristics.empty()

        assert chars.has_async_operations is False
        assert chars.has_user_input is False
        assert chars.complexity_score == 0

    def test_custom_characteristics(self):
        """Test creating characteristics with custom values."""
        chars = CodeCharacteristics(
            has_async_operations=True,
            has_database_operations=True,
            has_user_input=True,
            complexity_score=8,
            additional_characteristics=["uses_redis", "has_websockets"],
        )

        assert chars.has_async_operations is True
        assert chars.has_database_operations is True
        assert chars.has_user_input is True
        assert chars.complexity_score == 8
        assert "uses_redis" in chars.additional_characteristics
        assert "has_websockets" in chars.additional_characteristics


class TestRiskAssessment:
    """Test risk assessment properties."""

    def test_is_high_risk_with_authentication(self):
        """Test high risk detection with authentication logic."""
        chars = CodeCharacteristics(has_authentication_logic=True)
        assert chars.is_high_risk is True

    def test_is_high_risk_with_cryptography(self):
        """Test high risk detection with cryptographic operations."""
        chars = CodeCharacteristics(has_cryptographic_operations=True)
        assert chars.is_high_risk is True

    def test_is_high_risk_with_financial(self):
        """Test high risk detection with financial calculations."""
        chars = CodeCharacteristics(has_financial_calculations=True)
        assert chars.is_high_risk is True

    def test_is_high_risk_with_user_input_and_database(self):
        """Test high risk detection with user input + database."""
        chars = CodeCharacteristics(
            has_user_input=True, has_database_operations=True
        )
        assert chars.is_high_risk is True

    def test_not_high_risk_with_only_user_input(self):
        """Test that user input alone is not high risk."""
        chars = CodeCharacteristics(has_user_input=True)
        assert chars.is_high_risk is False

    def test_not_high_risk_with_only_database(self):
        """Test that database alone is not high risk."""
        chars = CodeCharacteristics(has_database_operations=True)
        assert chars.is_high_risk is False

    def test_not_high_risk_default(self):
        """Test default characteristics are not high risk."""
        chars = CodeCharacteristics()
        assert chars.is_high_risk is False


class TestSecurityFrameRequirement:
    """Test security frame requirement detection."""

    def test_requires_security_with_user_input(self):
        """Test security frame required with user input."""
        chars = CodeCharacteristics(has_user_input=True)
        assert chars.requires_security_frame is True

    def test_requires_security_with_authentication(self):
        """Test security frame required with authentication."""
        chars = CodeCharacteristics(has_authentication_logic=True)
        assert chars.requires_security_frame is True

    def test_requires_security_with_crypto(self):
        """Test security frame required with cryptography."""
        chars = CodeCharacteristics(has_cryptographic_operations=True)
        assert chars.requires_security_frame is True

    def test_requires_security_with_database(self):
        """Test security frame required with database."""
        chars = CodeCharacteristics(has_database_operations=True)
        assert chars.requires_security_frame is True

    def test_no_security_required_default(self):
        """Test security frame not required by default."""
        chars = CodeCharacteristics()
        assert chars.requires_security_frame is False


class TestChaosTestingRequirement:
    """Test chaos testing requirement detection."""

    def test_requires_chaos_with_async(self):
        """Test chaos testing required with async operations."""
        chars = CodeCharacteristics(has_async_operations=True)
        assert chars.requires_chaos_testing is True

    def test_requires_chaos_with_api_calls(self):
        """Test chaos testing required with external API calls."""
        chars = CodeCharacteristics(has_external_api_calls=True)
        assert chars.requires_chaos_testing is True

    def test_requires_chaos_with_network(self):
        """Test chaos testing required with network operations."""
        chars = CodeCharacteristics(has_network_operations=True)
        assert chars.requires_chaos_testing is True

    def test_no_chaos_required_default(self):
        """Test chaos testing not required by default."""
        chars = CodeCharacteristics()
        assert chars.requires_chaos_testing is False


class TestSerialization:
    """Test serialization and deserialization."""

    def test_to_dict(self):
        """Test to_dict() serialization."""
        chars = CodeCharacteristics(
            has_async_operations=True,
            has_user_input=True,
            complexity_score=7,
            additional_characteristics=["test"],
        )

        data = chars.to_dict()

        assert data["has_async_operations"] is True
        assert data["has_user_input"] is True
        assert data["complexity_score"] == 7
        assert data["additional_characteristics"] == ["test"]
        assert data["is_high_risk"] is False
        assert data["requires_security_frame"] is True
        assert data["requires_chaos_testing"] is True

    def test_from_dict(self):
        """Test from_dict() deserialization."""
        data = {
            "has_async_operations": True,
            "has_database_operations": True,
            "complexity_score": 5,
            "additional_characteristics": ["custom"],
        }

        chars = CodeCharacteristics.from_dict(data)

        assert chars.has_async_operations is True
        assert chars.has_database_operations is True
        assert chars.complexity_score == 5
        assert chars.additional_characteristics == ["custom"]

    def test_from_dict_with_defaults(self):
        """Test from_dict() with missing fields uses defaults."""
        data = {"has_user_input": True}

        chars = CodeCharacteristics.from_dict(data)

        assert chars.has_user_input is True
        assert chars.has_async_operations is False
        assert chars.complexity_score == 0

    def test_roundtrip_serialization(self):
        """Test serialization roundtrip (to_dict -> from_dict)."""
        original = CodeCharacteristics(
            has_authentication_logic=True,
            has_cryptographic_operations=True,
            complexity_score=9,
            additional_characteristics=["special"],
        )

        data = original.to_dict()
        restored = CodeCharacteristics.from_dict(data)

        assert restored.has_authentication_logic is True
        assert restored.has_cryptographic_operations is True
        assert restored.complexity_score == 9
        assert restored.additional_characteristics == ["special"]


class TestComplexScenarios:
    """Test complex characteristic combinations."""

    def test_fintech_application_characteristics(self):
        """Test characteristics for fintech application."""
        chars = CodeCharacteristics(
            has_user_input=True,
            has_database_operations=True,
            has_financial_calculations=True,
            has_authentication_logic=True,
            has_cryptographic_operations=True,
            has_network_operations=True,
            complexity_score=9,
        )

        # Should be high risk
        assert chars.is_high_risk is True

        # Should require security frame
        assert chars.requires_security_frame is True

        # Should require chaos testing
        assert chars.requires_chaos_testing is True

    def test_simple_utility_script(self):
        """Test characteristics for simple utility script."""
        chars = CodeCharacteristics(
            has_file_operations=True,
            complexity_score=2,
        )

        # Should not be high risk
        assert chars.is_high_risk is False

        # Should not require security frame
        assert chars.requires_security_frame is False

        # Should not require chaos testing
        assert chars.requires_chaos_testing is False

    def test_api_service_characteristics(self):
        """Test characteristics for API service."""
        chars = CodeCharacteristics(
            has_async_operations=True,
            has_external_api_calls=True,
            has_network_operations=True,
            has_user_input=True,
            has_database_operations=True,
            has_authentication_logic=True,
            complexity_score=7,
        )

        assert chars.is_high_risk is True
        assert chars.requires_security_frame is True
        assert chars.requires_chaos_testing is True
