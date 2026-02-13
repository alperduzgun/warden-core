"""
Cross-Repo Contract Drift E2E Tests.

End-to-end tests that simulate real-world cross-repository contract drift
scenarios between a FastAPI provider and an httpx consumer project.

Tests cover:
1. Missing consumer operations (provider has DELETE, consumer doesn't use it)
2. Type mismatches between provider and consumer contracts
3. Identical contracts produce zero gaps
4. Empty consumer projects handle gracefully
5. Malformed source files don't crash analysis
6. Extraction timeout handling

Fixture approach:
- Provider: A FastAPI app with GET/POST/DELETE /api/users endpoints
- Consumer: An httpx client that only uses GET/POST (no DELETE)
- All fixtures are written as Python source strings into tmp_path
- No running servers needed -- extraction is purely static analysis

Issue: #28
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.validation.frames.spec import (
    Contract,
    ContractGap,
    FieldDefinition,
    GapAnalyzerConfig,
    GapSeverity,
    ModelDefinition,
    OperationDefinition,
    OperationType,
    PlatformConfig,
    PlatformRole,
    PlatformType,
    SpecAnalysisResult,
    analyze_contracts,
)
from warden.validation.frames.spec.analyzer import GapAnalyzer
from warden.validation.frames.spec.extractors.base import (
    ExtractorResilienceConfig,
    get_extractor,
)
from warden.validation.frames.spec.spec_frame import SpecFrame
from warden.shared.infrastructure.resilience import OperationTimeoutError
from warden.validation.domain.frame import CodeFile, Finding, FrameResult


# ---------------------------------------------------------------------------
# Fixture source code strings
# ---------------------------------------------------------------------------

PROVIDER_FASTAPI_SOURCE = '''\
"""FastAPI provider with GET, POST, DELETE /api/users endpoints."""
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    age: int


class CreateUserRequest(BaseModel):
    name: str
    email: str
    age: int


@app.get("/api/users", response_model=List[UserResponse])
async def get_users():
    """List all users."""
    return []


@app.post("/api/users", response_model=UserResponse)
async def create_user(request: CreateUserRequest):
    """Create a new user."""
    return UserResponse(id=1, name=request.name, email=request.email, age=request.age)


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int):
    """Delete a user by ID."""
    pass
'''

CONSUMER_HTTPX_SOURCE = '''\
"""httpx consumer that only uses GET and POST (no DELETE)."""
import httpx

BASE_URL = "http://localhost:8000"


async def fetch_users() -> list:
    """Fetch all users from the API."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/api/users")
        return response.json()


async def create_user(name: str, email: str, age: str) -> dict:
    """Create a new user via the API.

    Note: age is typed as str here but provider returns int -- type mismatch.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/api/users",
            json={"name": name, "email": email, "age": age},
        )
        return response.json()
'''

CONSUMER_HTTPX_IDENTICAL_SOURCE = '''\
"""httpx consumer that uses GET, POST, and DELETE -- identical to provider."""
import httpx

BASE_URL = "http://localhost:8000"


async def fetch_users() -> list:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/api/users")
        return response.json()


async def create_user(name: str, email: str, age: int) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/api/users",
            json={"name": name, "email": email, "age": age},
        )
        return response.json()


async def delete_user(user_id: int) -> None:
    async with httpx.AsyncClient() as client:
        await client.delete(f"{BASE_URL}/api/users/{user_id}")
'''

MALFORMED_PYTHON_SOURCE = '''\
"""This file has syntax errors that should not crash the extractor."""
from fastapi import FastAPI

app = FastAPI()

# Incomplete decorator -- missing closing paren
@app.get("/api/broken"
async def broken_endpoint(
    # Missing closing paren and colon
    return []

# Random garbage
class Incomplete(BaseModel:
    name str
    ===
'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_code_file(path: str = "/tmp/test_project") -> CodeFile:
    """Create a CodeFile instance for SpecFrame execution."""
    return CodeFile(
        path=path,
        content="",
        language="python",
    )


def _write_provider_fixture(base_path: Path) -> Path:
    """Write the provider FastAPI fixture to disk and return the project path."""
    provider_dir = base_path / "provider"
    provider_dir.mkdir(parents=True, exist_ok=True)
    main_file = provider_dir / "main.py"
    main_file.write_text(PROVIDER_FASTAPI_SOURCE, encoding="utf-8")
    return provider_dir


def _write_consumer_fixture(
    base_path: Path,
    source: str = CONSUMER_HTTPX_SOURCE,
    dirname: str = "consumer",
) -> Path:
    """Write a consumer fixture to disk and return the project path."""
    consumer_dir = base_path / dirname
    consumer_dir.mkdir(parents=True, exist_ok=True)
    api_file = consumer_dir / "api.py"
    api_file.write_text(source, encoding="utf-8")
    return consumer_dir


# ---------------------------------------------------------------------------
# Contract-level E2E tests (using GapAnalyzer directly)
# ---------------------------------------------------------------------------

class TestCrossRepoDriftDetection:
    """
    E2E tests that extract contracts from fixture source files via the
    FastAPI extractor and then run gap analysis to detect drift.
    """

    @pytest.mark.asyncio
    async def test_detects_missing_consumer_operation(self, tmp_path):
        """
        Provider has DELETE /api/users/{user_id}, consumer doesn't use it.

        Expected: An 'unused_operation' gap is detected for delete_user
        because the provider offers it but the consumer never calls it.
        """
        provider_dir = _write_provider_fixture(tmp_path)

        # Extract provider contract via FastAPI extractor
        provider_extractor = get_extractor(
            PlatformType.FASTAPI,
            provider_dir,
            PlatformRole.PROVIDER,
        )
        assert provider_extractor is not None, "FastAPI extractor should be available"
        provider_contract = await provider_extractor.extract()

        # Verify provider has DELETE endpoint
        provider_op_names = [op.name for op in provider_contract.operations]
        assert "delete_user" in provider_op_names, (
            f"Provider should have delete_user operation, found: {provider_op_names}"
        )

        # Build consumer contract manually (httpx calls are not extractable
        # by FastAPI extractor -- they are consumer-side calls).
        # This simulates what a consumer extractor would produce.
        consumer_contract = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="get_users",
                    operation_type=OperationType.QUERY,
                    output_type="UserResponse",
                    source_file="consumer/api.py",
                    source_line=8,
                ),
                OperationDefinition(
                    name="create_user",
                    operation_type=OperationType.COMMAND,
                    input_type="CreateUserRequest",
                    output_type="UserResponse",
                    source_file="consumer/api.py",
                    source_line=15,
                ),
            ],
        )

        # Run gap analysis
        result = await analyze_contracts(consumer_contract, provider_contract)

        # The provider has delete_user which consumer does NOT use
        unused_gaps = [
            g for g in result.gaps if g.gap_type == "unused_operation"
        ]
        assert len(unused_gaps) >= 1, (
            f"Should detect at least 1 unused operation (delete_user), "
            f"got gaps: {[(g.gap_type, g.operation_name) for g in result.gaps]}"
        )

        delete_gap = next(
            (g for g in unused_gaps if "delete_user" in (g.operation_name or "")),
            None,
        )
        assert delete_gap is not None, (
            "Should specifically detect delete_user as unused"
        )
        assert delete_gap.severity == GapSeverity.LOW

    @pytest.mark.asyncio
    async def test_detects_type_mismatch(self, tmp_path):
        """
        Provider returns 'int' for the 'age' field, consumer expects 'str'.

        Expected: A type mismatch gap is detected at the model field level.
        """
        # Build contracts with explicit type mismatch on 'age' field
        consumer_contract = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="create_user",
                    operation_type=OperationType.COMMAND,
                    input_type="CreateUserInput",
                    output_type="UserOutput",
                    source_file="consumer/api.py",
                    source_line=15,
                ),
            ],
            models=[
                ModelDefinition(
                    name="UserOutput",
                    fields=[
                        FieldDefinition(name="id", type_name="int"),
                        FieldDefinition(name="name", type_name="string"),
                        FieldDefinition(name="email", type_name="string"),
                        FieldDefinition(
                            name="age",
                            type_name="string",  # Consumer expects string
                            source_file="consumer/api.py",
                        ),
                    ],
                    source_file="consumer/api.py",
                ),
            ],
        )

        # Extract provider contract from fixture
        provider_dir = _write_provider_fixture(tmp_path)
        provider_extractor = get_extractor(
            PlatformType.FASTAPI,
            provider_dir,
            PlatformRole.PROVIDER,
        )
        provider_contract = await provider_extractor.extract()

        # Also add a matching model to provider for model-level comparison.
        # The FastAPI extractor extracts UserResponse with age: int.
        # We need the consumer model name to match, so use the same name.
        provider_model = provider_contract.get_model("UserResponse")
        if provider_model:
            # Rename consumer model to match provider for comparison
            consumer_contract.models[0].name = "UserResponse"

        # Run gap analysis
        result = await analyze_contracts(consumer_contract, provider_contract)

        # Check for field type mismatch on 'age'
        type_mismatch_gaps = [
            g for g in result.gaps
            if g.gap_type == "field_type_mismatch"
        ]
        assert len(type_mismatch_gaps) >= 1, (
            f"Should detect age field type mismatch (string vs int), "
            f"got gaps: {[(g.gap_type, g.message) for g in result.gaps]}"
        )

        age_gap = next(
            (g for g in type_mismatch_gaps if "age" in (g.field_name or "")),
            None,
        )
        assert age_gap is not None, "Should detect type mismatch on 'age' field"
        assert age_gap.severity == GapSeverity.HIGH

    @pytest.mark.asyncio
    async def test_identical_contracts_zero_gaps(self, tmp_path):
        """
        Same contract on both sides produces zero drift.

        Expected: Matched operations == total operations, zero gaps.
        """
        provider_dir = _write_provider_fixture(tmp_path)
        provider_extractor = get_extractor(
            PlatformType.FASTAPI,
            provider_dir,
            PlatformRole.PROVIDER,
        )
        provider_contract = await provider_extractor.extract()

        # Consumer mirrors provider exactly (same operation names)
        consumer_contract = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name=op.name,
                    operation_type=op.operation_type,
                    input_type=op.input_type,
                    output_type=op.output_type,
                )
                for op in provider_contract.operations
            ],
        )

        result = await analyze_contracts(consumer_contract, provider_contract)

        assert result.matched_operations == len(provider_contract.operations), (
            f"All {len(provider_contract.operations)} operations should match, "
            f"but only {result.matched_operations} matched"
        )
        assert result.missing_operations == 0
        assert result.unused_operations == 0

        # Filter out any LOW-severity informational gaps
        critical_and_high_gaps = [
            g for g in result.gaps
            if g.severity in (GapSeverity.CRITICAL, GapSeverity.HIGH)
        ]
        assert len(critical_and_high_gaps) == 0, (
            f"Identical contracts should have zero critical/high gaps, "
            f"found: {[(g.gap_type, g.severity, g.message) for g in critical_and_high_gaps]}"
        )

    @pytest.mark.asyncio
    async def test_empty_consumer_graceful(self, tmp_path):
        """
        Empty consumer project handles gracefully without crash.

        Expected: All provider operations marked as 'unused', no crash.
        """
        provider_dir = _write_provider_fixture(tmp_path)
        provider_extractor = get_extractor(
            PlatformType.FASTAPI,
            provider_dir,
            PlatformRole.PROVIDER,
        )
        provider_contract = await provider_extractor.extract()

        # Empty consumer -- no operations, no models
        consumer_contract = Contract(name="empty-consumer")

        result = await analyze_contracts(consumer_contract, provider_contract)

        # Should not crash
        assert result is not None
        assert result.consumer_contract.name == "empty-consumer"
        assert result.total_consumer_operations == 0

        # All provider operations should be 'unused'
        assert result.unused_operations == len(provider_contract.operations)
        assert result.missing_operations == 0
        assert result.matched_operations == 0

        # No critical gaps (unused is LOW severity)
        assert result.has_critical_gaps() is False

    @pytest.mark.asyncio
    async def test_malformed_source_files(self, tmp_path):
        """
        Files with syntax errors don't crash the extraction or analysis.

        Expected: Extractor handles malformed files gracefully and returns
        a contract (possibly empty or partial) without raising an exception.
        """
        # Write malformed Python file to provider directory
        malformed_dir = tmp_path / "malformed_provider"
        malformed_dir.mkdir(parents=True, exist_ok=True)
        malformed_file = malformed_dir / "main.py"
        malformed_file.write_text(MALFORMED_PYTHON_SOURCE, encoding="utf-8")

        # FastAPI extractor should not crash on malformed files
        extractor = get_extractor(
            PlatformType.FASTAPI,
            malformed_dir,
            PlatformRole.PROVIDER,
        )
        assert extractor is not None

        # Extraction should complete without raising
        contract = await extractor.extract()
        assert contract is not None
        assert isinstance(contract, Contract)

        # Run gap analysis with malformed provider contract
        consumer_contract = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="getUsers",
                    operation_type=OperationType.QUERY,
                ),
            ],
        )

        # Analysis should not crash even with partial/empty provider contract
        result = await analyze_contracts(consumer_contract, contract)
        assert result is not None
        assert isinstance(result, SpecAnalysisResult)

    @pytest.mark.asyncio
    async def test_extraction_timeout(self, tmp_path):
        """
        Short timeout causes graceful timeout handling in SpecFrame.

        Expected: Frame returns a result with timeout metadata and a
        warning finding instead of crashing.
        """
        provider_dir = _write_provider_fixture(tmp_path)
        consumer_dir = _write_consumer_fixture(tmp_path)

        config = {
            "platforms": [
                {
                    "name": "consumer",
                    "path": str(consumer_dir),
                    "type": "fastapi",
                    "role": "consumer",
                },
                {
                    "name": "provider",
                    "path": str(provider_dir),
                    "type": "fastapi",
                    "role": "provider",
                },
            ],
            "gap_analysis_timeout": 0.001,  # Extremely short timeout
        }

        frame = SpecFrame(config=config)

        # Mock _extract_contract to return valid contracts
        # (we want to test the gap analysis timeout, not extraction)
        provider_contract = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="get_users",
                    operation_type=OperationType.QUERY,
                ),
            ],
        )
        consumer_contract = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="get_users",
                    operation_type=OperationType.QUERY,
                ),
            ],
        )

        # Simulate slow gap analysis that exceeds the timeout
        async def slow_gap_analysis(*args, **kwargs):
            await asyncio.sleep(10)
            return SpecAnalysisResult(
                consumer_contract=consumer_contract,
                provider_contract=provider_contract,
            )

        with patch.object(frame, "_validate_configuration", return_value=None):
            with patch.object(frame, "_extract_contract") as mock_extract:
                mock_extract.side_effect = [consumer_contract, provider_contract]

                with patch.object(
                    frame, "_analyze_gaps", side_effect=slow_gap_analysis
                ):
                    code_file = _create_code_file()
                    result = await frame.execute(code_file)

        # Frame should return a result (not crash)
        assert result is not None
        assert isinstance(result, FrameResult)

        # Should contain timeout-related findings
        timeout_findings = [
            f for f in result.findings
            if "timeout" in f.message.lower() or "timed out" in f.message.lower()
        ]
        assert len(timeout_findings) >= 1, (
            f"Should have timeout warning finding, "
            f"got findings: {[(f.id, f.message) for f in result.findings]}"
        )
        assert any(f.severity == "warning" for f in timeout_findings)

        # Metadata should indicate timeout occurred
        assert result.metadata is not None
        assert result.metadata.get("timeout_occurred") is True


# ---------------------------------------------------------------------------
# SpecFrame integration-level E2E tests
# ---------------------------------------------------------------------------

class TestSpecFrameIntegrationDrift:
    """
    Integration tests that exercise the SpecFrame end-to-end with
    mocked extraction but real gap analysis.
    """

    @pytest.mark.asyncio
    async def test_full_frame_execution_with_drift(self, tmp_path):
        """
        Full SpecFrame execution detects drift between consumer and provider.

        This test exercises the complete frame pipeline:
        extraction -> gap analysis -> finding generation.
        """
        provider_dir = _write_provider_fixture(tmp_path)
        consumer_dir = _write_consumer_fixture(tmp_path)

        config = {
            "platforms": [
                {
                    "name": "consumer",
                    "path": str(consumer_dir),
                    "type": "fastapi",
                    "role": "consumer",
                },
                {
                    "name": "provider",
                    "path": str(provider_dir),
                    "type": "fastapi",
                    "role": "provider",
                },
            ],
        }

        frame = SpecFrame(config=config)

        # Build realistic contracts
        consumer_contract = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="get_users",
                    operation_type=OperationType.QUERY,
                    output_type="UserResponse",
                ),
                OperationDefinition(
                    name="create_user",
                    operation_type=OperationType.COMMAND,
                    input_type="CreateUserRequest",
                    output_type="UserResponse",
                ),
                # Consumer does NOT have delete_user
            ],
        )
        provider_contract = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="get_users",
                    operation_type=OperationType.QUERY,
                    output_type="UserResponse",
                ),
                OperationDefinition(
                    name="create_user",
                    operation_type=OperationType.COMMAND,
                    input_type="CreateUserRequest",
                    output_type="UserResponse",
                ),
                OperationDefinition(
                    name="delete_user",
                    operation_type=OperationType.COMMAND,
                ),
            ],
        )

        with patch.object(frame, "_validate_configuration", return_value=None):
            with patch.object(frame, "_extract_contract") as mock_extract:
                mock_extract.side_effect = [consumer_contract, provider_contract]
                code_file = _create_code_file()
                result = await frame.execute(code_file)

        assert result is not None
        assert result.status in ("passed", "warning", "failed")

        # Should detect that delete_user is unused by consumer
        unused_findings = [
            f for f in result.findings
            if "delete_user" in f.message and "not used" in f.message
        ]
        assert len(unused_findings) >= 1, (
            f"Should detect delete_user as unused, "
            f"findings: {[(f.id, f.message) for f in result.findings]}"
        )

    @pytest.mark.asyncio
    async def test_frame_handles_extraction_failure_gracefully(self, tmp_path):
        """
        SpecFrame handles extraction errors without crashing.

        If one platform extraction fails, the frame should continue
        with a degraded contract rather than failing completely.
        """
        provider_dir = _write_provider_fixture(tmp_path)
        consumer_dir = _write_consumer_fixture(tmp_path)

        config = {
            "platforms": [
                {
                    "name": "consumer",
                    "path": str(consumer_dir),
                    "type": "fastapi",
                    "role": "consumer",
                },
                {
                    "name": "provider",
                    "path": str(provider_dir),
                    "type": "fastapi",
                    "role": "provider",
                },
            ],
        }

        frame = SpecFrame(config=config)

        # Consumer extraction fails, provider succeeds
        provider_contract = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="get_users",
                    operation_type=OperationType.QUERY,
                ),
            ],
        )

        async def extraction_side_effect(platform):
            if platform.role == PlatformRole.CONSUMER:
                raise RuntimeError("Simulated extraction failure")
            return provider_contract

        with patch.object(frame, "_validate_configuration", return_value=None):
            with patch.object(
                frame, "_extract_contract", side_effect=extraction_side_effect
            ) as mock_extract:
                code_file = _create_code_file()
                result = await frame.execute(code_file)

        # Frame should return a result (not crash)
        assert result is not None
        assert isinstance(result, FrameResult)
        # Status should be either passed, error, or warning (not unhandled exception)
        assert result.status in ("passed", "warning", "failed", "error")

    @pytest.mark.asyncio
    async def test_suppression_filters_drift_gaps(self, tmp_path):
        """
        Suppression rules filter out known drift gaps.

        When a gap is suppressed, it should not appear in findings
        but should be counted in metadata.
        """
        provider_dir = _write_provider_fixture(tmp_path)
        consumer_dir = _write_consumer_fixture(tmp_path)

        config = {
            "platforms": [
                {
                    "name": "consumer",
                    "path": str(consumer_dir),
                    "type": "fastapi",
                    "role": "consumer",
                },
                {
                    "name": "provider",
                    "path": str(provider_dir),
                    "type": "fastapi",
                    "role": "provider",
                },
            ],
            "suppressions": [
                {
                    "rule": "spec:unused_operation:delete_user",
                    "reason": "DELETE endpoint not yet implemented in consumer",
                },
            ],
        }

        frame = SpecFrame(config=config)

        consumer_contract = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="get_users",
                    operation_type=OperationType.QUERY,
                ),
            ],
        )
        provider_contract = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="get_users",
                    operation_type=OperationType.QUERY,
                ),
                OperationDefinition(
                    name="delete_user",
                    operation_type=OperationType.COMMAND,
                ),
            ],
        )

        with patch.object(frame, "_validate_configuration", return_value=None):
            with patch.object(frame, "_extract_contract") as mock_extract:
                mock_extract.side_effect = [consumer_contract, provider_contract]
                code_file = _create_code_file()
                result = await frame.execute(code_file)

        assert result is not None

        # The delete_user unused gap should be suppressed
        delete_findings = [
            f for f in result.findings
            if "delete_user" in f.message
        ]
        assert len(delete_findings) == 0, (
            "Suppressed gap should not appear in findings"
        )

        # Metadata should track suppressed count
        assert result.metadata is not None
        assert result.metadata.get("suppressed_gaps", 0) >= 1


# ---------------------------------------------------------------------------
# Extractor resilience E2E tests
# ---------------------------------------------------------------------------

class TestExtractorResilienceE2E:
    """
    Tests for ExtractorResilienceConfig integration with real extractors.
    """

    @pytest.mark.asyncio
    async def test_extractor_with_custom_resilience_config(self, tmp_path):
        """
        Extractor respects custom resilience configuration values.
        """
        provider_dir = _write_provider_fixture(tmp_path)

        resilience_config = ExtractorResilienceConfig(
            parse_timeout=60.0,
            extraction_timeout=120.0,
            retry_max_attempts=1,
            max_concurrent_files=5,
        )

        extractor = get_extractor(
            PlatformType.FASTAPI,
            provider_dir,
            PlatformRole.PROVIDER,
            resilience_config,
        )
        assert extractor is not None
        assert extractor.resilience_config.parse_timeout == 60.0
        assert extractor.resilience_config.extraction_timeout == 120.0
        assert extractor.resilience_config.retry_max_attempts == 1
        assert extractor.resilience_config.max_concurrent_files == 5

        # Extraction should still work with custom config
        contract = await extractor.extract()
        assert contract is not None
        assert len(contract.operations) >= 1

    @pytest.mark.asyncio
    async def test_extractor_stats_tracking(self, tmp_path):
        """
        Extractor tracks extraction statistics for observability.
        """
        provider_dir = _write_provider_fixture(tmp_path)

        extractor = get_extractor(
            PlatformType.FASTAPI,
            provider_dir,
            PlatformRole.PROVIDER,
        )
        assert extractor is not None

        await extractor.extract()

        stats = extractor.get_extraction_stats()
        assert "files_processed" in stats
        assert "files_failed" in stats
        assert "circuit_breaker_state" in stats
        assert stats["files_processed"] >= 0


# ---------------------------------------------------------------------------
# Gap analysis edge cases
# ---------------------------------------------------------------------------

class TestDriftAnalysisEdgeCases:
    """
    Edge case tests for drift detection logic.
    """

    @pytest.mark.asyncio
    async def test_consumer_has_extra_operations_not_in_provider(self):
        """
        Consumer expects operations the provider doesn't have.

        Expected: missing_operation gaps with CRITICAL severity.
        """
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="get_users",
                    operation_type=OperationType.QUERY,
                ),
                OperationDefinition(
                    name="export_users",
                    operation_type=OperationType.COMMAND,
                    source_file="consumer/api.py",
                    source_line=42,
                ),
            ],
        )

        provider = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="get_users",
                    operation_type=OperationType.QUERY,
                ),
            ],
        )

        result = await analyze_contracts(consumer, provider)

        missing_gaps = [
            g for g in result.gaps if g.gap_type == "missing_operation"
        ]
        assert len(missing_gaps) == 1
        assert "export_users" in missing_gaps[0].message
        assert missing_gaps[0].severity == GapSeverity.CRITICAL
        assert missing_gaps[0].consumer_file == "consumer/api.py"
        assert missing_gaps[0].consumer_line == 42

    @pytest.mark.asyncio
    async def test_bidirectional_drift_detection(self):
        """
        Both missing and unused operations detected simultaneously.

        Consumer has op_a and op_b.
        Provider has op_a and op_c.
        Expected: op_b is missing (consumer wants it), op_c is unused.

        Note: Operation names are intentionally dissimilar to avoid
        fuzzy matching (the analyzer normalizes and fuzzy-matches names
        like search_users <-> archive_users because they share 'users').
        """
        consumer = Contract(
            name="consumer",
            operations=[
                OperationDefinition(
                    name="listAllProducts",
                    operation_type=OperationType.QUERY,
                ),
                OperationDefinition(
                    name="generateInvoicePdf",
                    operation_type=OperationType.COMMAND,
                ),
            ],
        )

        provider = Contract(
            name="provider",
            operations=[
                OperationDefinition(
                    name="listAllProducts",
                    operation_type=OperationType.QUERY,
                ),
                OperationDefinition(
                    name="sendBulkNotification",
                    operation_type=OperationType.COMMAND,
                ),
            ],
        )

        config = GapAnalyzerConfig(enable_fuzzy_matching=False)
        result = await analyze_contracts(consumer, provider, config)

        assert result.matched_operations == 1
        assert result.missing_operations == 1
        assert result.unused_operations == 1

        missing = [g for g in result.gaps if g.gap_type == "missing_operation"]
        unused = [g for g in result.gaps if g.gap_type == "unused_operation"]

        assert len(missing) == 1
        assert "generateInvoicePdf" in missing[0].message

        assert len(unused) == 1
        assert "sendBulkNotification" in unused[0].message

    @pytest.mark.asyncio
    async def test_large_contract_drift_performance(self):
        """
        Gap analysis handles large contracts within reasonable time.

        Creates 100 operations on each side with partial overlap to
        ensure the analyzer doesn't degrade with realistic scale.
        """
        # Build large contracts with 50% overlap
        shared_ops = [
            OperationDefinition(
                name=f"operation_{i}",
                operation_type=OperationType.QUERY,
            )
            for i in range(50)
        ]
        consumer_only_ops = [
            OperationDefinition(
                name=f"consumer_op_{i}",
                operation_type=OperationType.QUERY,
            )
            for i in range(50)
        ]
        provider_only_ops = [
            OperationDefinition(
                name=f"provider_op_{i}",
                operation_type=OperationType.QUERY,
            )
            for i in range(50)
        ]

        consumer = Contract(
            name="large-consumer",
            operations=shared_ops + consumer_only_ops,
        )
        provider = Contract(
            name="large-provider",
            operations=shared_ops + provider_only_ops,
        )

        # Should complete without timeout
        config = GapAnalyzerConfig(enable_fuzzy_matching=False)
        result = await analyze_contracts(consumer, provider, config)

        assert result.matched_operations == 50
        assert result.missing_operations == 50
        assert result.unused_operations == 50
        assert result.total_consumer_operations == 100
        assert result.total_provider_operations == 100
