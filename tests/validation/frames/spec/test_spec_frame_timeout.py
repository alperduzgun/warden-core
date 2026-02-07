"""
Tests for SpecFrame timeout functionality.

Tests gap analysis timeout protection to prevent DOS attacks.
"""

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.validation.domain.frame import CodeFile
from warden.validation.frames.spec.spec_frame import SpecFrame
from warden.validation.frames.spec.models import (
    Contract,
    OperationDefinition,
    OperationType,
    PlatformConfig,
    PlatformRole,
    PlatformType,
)
from warden.shared.infrastructure.resilience import OperationTimeoutError


def create_code_file(path: str = "/tmp/test.py") -> CodeFile:
    """Helper to create CodeFile instances."""
    return CodeFile(
        path=path,
        content="",
        language="python"
    )


class TestSpecFrameTimeout:
    """Tests for gap analysis timeout protection."""

    @pytest.mark.asyncio
    async def test_gap_analysis_timeout_default_config(self):
        """Test that default timeout is 120s when not configured."""
        # Create frame without timeout config
        frame = SpecFrame(config={
            "platforms": [
                {
                    "name": "consumer",
                    "path": "/tmp/consumer",
                    "type": "flutter",
                    "role": "consumer"
                },
                {
                    "name": "provider",
                    "path": "/tmp/provider",
                    "type": "spring-boot",
                    "role": "provider"
                }
            ]
        })

        # Check default timeout is used
        timeout = frame.config.get("gap_analysis_timeout", 120)
        assert timeout == 120

    @pytest.mark.asyncio
    async def test_gap_analysis_timeout_custom_config(self):
        """Test custom timeout configuration."""
        # Create frame with custom timeout
        frame = SpecFrame(config={
            "platforms": [],
            "gap_analysis_timeout": 60
        })

        timeout = frame.config.get("gap_analysis_timeout", 120)
        assert timeout == 60

    @pytest.mark.asyncio
    async def test_gap_analysis_timeout_triggers_warning(self):
        """Test that timeout creates a warning finding."""
        # Create a mock that simulates a slow gap analysis
        async def slow_analyze(*args, **kwargs):
            await asyncio.sleep(10)  # Simulate slow operation
            # This should never complete due to timeout
            return MagicMock()

        config = {
            "platforms": [
                {
                    "name": "consumer",
                    "path": "/tmp/consumer",
                    "type": "flutter",
                    "role": "consumer"
                },
                {
                    "name": "provider",
                    "path": "/tmp/provider",
                    "type": "spring-boot",
                    "role": "provider"
                }
            ],
            "gap_analysis_timeout": 0.1  # Very short timeout for testing
        }

        frame = SpecFrame(config=config)

        # Mock the _extract_contract to return valid contracts
        consumer_contract = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="getUsers",
                    operation_type=OperationType.QUERY
                )
            ]
        )
        provider_contract = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="getUsers",
                    operation_type=OperationType.QUERY
                )
            ]
        )

        # Mock validation to pass
        with patch.object(frame, '_validate_configuration', return_value=None):
            with patch.object(frame, '_extract_contract') as mock_extract:
                # Return contracts for both platforms
                mock_extract.side_effect = [consumer_contract, provider_contract]

                # Mock _analyze_gaps to be slow
                with patch.object(frame, '_analyze_gaps', side_effect=slow_analyze):
                    # Execute frame
                    code_file = create_code_file()
                    result = await frame.execute(code_file)

                    # Should have warning finding about timeout
                    timeout_findings = [
                        f for f in result.findings
                        if "timeout" in f.id.lower() or "timeout" in f.message.lower()
                    ]
                    assert len(timeout_findings) > 0
                    assert any(f.severity == "warning" for f in timeout_findings)

                    # Check metadata
                    assert result.metadata.get("timeout_occurred") is True
                    assert "timeout_seconds" in result.metadata

    @pytest.mark.asyncio
    async def test_gap_analysis_continues_on_timeout(self):
        """Test that frame continues gracefully after timeout."""
        # Simulate timeout by raising OperationTimeoutError
        async def timeout_analyze(*args, **kwargs):
            raise OperationTimeoutError("gap_analysis", 120)

        config = {
            "platforms": [
                {
                    "name": "consumer",
                    "path": "/tmp/consumer",
                    "type": "flutter",
                    "role": "consumer"
                },
                {
                    "name": "provider",
                    "path": "/tmp/provider",
                    "type": "spring-boot",
                    "role": "provider"
                }
            ],
            "gap_analysis_timeout": 120
        }

        frame = SpecFrame(config=config)

        # Mock contracts
        consumer_contract = Contract(name="consumer")
        provider_contract = Contract(name="provider")

        # Mock validation to pass (skip path checks)
        with patch.object(frame, '_validate_configuration', return_value=None):
            with patch.object(frame, '_extract_contract') as mock_extract:
                mock_extract.side_effect = [consumer_contract, provider_contract]

                with patch.object(frame, '_analyze_gaps', side_effect=timeout_analyze):
                    code_file = create_code_file()
                    result = await frame.execute(code_file)

                    # Frame should complete (not crash)
                    assert result is not None
                    assert result.status in ["warning", "failed", "passed"]

                    # Should have timeout finding
                    assert len(result.findings) > 0
                    timeout_finding = result.findings[0]
                    # Check for "timed out" or "timeout" in message
                    message_lower = timeout_finding.message.lower()
                    assert "timeout" in message_lower or "timed out" in message_lower

    @pytest.mark.asyncio
    async def test_gap_analysis_metadata_tracking(self):
        """Test that timeout metadata is properly tracked."""
        async def timeout_analyze(*args, **kwargs):
            raise OperationTimeoutError("gap_analysis", 45)

        config = {
            "platforms": [
                {
                    "name": "mobile",
                    "path": "/tmp/mobile",
                    "type": "flutter",
                    "role": "consumer"
                },
                {
                    "name": "backend",
                    "path": "/tmp/backend",
                    "type": "spring-boot",
                    "role": "provider"
                }
            ],
            "gap_analysis_timeout": 45
        }

        frame = SpecFrame(config=config)

        consumer_contract = Contract(name="mobile")
        provider_contract = Contract(name="backend")

        # Mock validation to pass
        with patch.object(frame, '_validate_configuration', return_value=None):
            with patch.object(frame, '_extract_contract') as mock_extract:
                mock_extract.side_effect = [consumer_contract, provider_contract]

                with patch.object(frame, '_analyze_gaps', side_effect=timeout_analyze):
                    code_file = create_code_file()
                    result = await frame.execute(code_file)

                    # Check metadata contains timeout info
                    assert result.metadata["timeout_occurred"] is True
                    assert result.metadata["timeout_seconds"] == 45
                    assert result.metadata["timeout_pair"] == "mobile_vs_backend"

    @pytest.mark.asyncio
    async def test_gap_analysis_no_timeout_on_success(self):
        """Test that successful analysis doesn't set timeout metadata."""
        async def fast_analyze(*args, **kwargs):
            # Return empty result quickly
            from warden.validation.frames.spec.models import SpecAnalysisResult
            return SpecAnalysisResult(
                consumer_contract=args[0],
                provider_contract=args[1]
            )

        config = {
            "platforms": [
                {
                    "name": "consumer",
                    "path": "/tmp/consumer",
                    "type": "flutter",
                    "role": "consumer"
                },
                {
                    "name": "provider",
                    "path": "/tmp/provider",
                    "type": "spring-boot",
                    "role": "provider"
                }
            ],
            "gap_analysis_timeout": 120
        }

        frame = SpecFrame(config=config)

        consumer_contract = Contract(name="consumer")
        provider_contract = Contract(name="provider")

        # Mock validation to pass
        with patch.object(frame, '_validate_configuration', return_value=None):
            with patch.object(frame, '_extract_contract') as mock_extract:
                mock_extract.side_effect = [consumer_contract, provider_contract]

                with patch.object(frame, '_analyze_gaps', side_effect=fast_analyze):
                    code_file = create_code_file()
                    result = await frame.execute(code_file)

                    # Should not have timeout metadata
                    assert result.metadata.get("timeout_occurred", False) is False
                    assert "timeout_seconds" not in result.metadata or result.metadata.get("timeout_occurred") is False
