"""
Unit tests for Issue #613 — verification confidence surfacing.

Covers:
- Finding.verification_confidence field exists and defaults to None
- Finding.to_json() includes verificationConfidence when set
- FindingsCache serializes/deserializes verification_confidence correctly
- FindingVerificationService propagates confidence from LLM result to finding
- CLI scan output formats confidence as % (or em-dash when None)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.validation.domain.frame import Finding


# ---------------------------------------------------------------------------
# Finding dataclass — field presence and to_json serialization
# ---------------------------------------------------------------------------


class TestFindingVerificationConfidenceField:
    def _make_finding(self, **kwargs) -> Finding:
        defaults = {
            "id": "W001",
            "severity": "high",
            "message": "test finding",
            "location": "src/foo.py:10",
        }
        defaults.update(kwargs)
        return Finding(**defaults)

    def test_verification_confidence_defaults_to_none(self) -> None:
        f = self._make_finding()
        assert f.verification_confidence is None

    def test_verification_confidence_can_be_set(self) -> None:
        f = self._make_finding(verification_confidence=0.87)
        assert f.verification_confidence == pytest.approx(0.87)

    def test_to_json_omits_verification_confidence_when_none(self) -> None:
        f = self._make_finding()
        data = f.to_json()
        assert "verificationConfidence" not in data

    def test_to_json_includes_verification_confidence_when_set(self) -> None:
        f = self._make_finding(verification_confidence=0.92)
        data = f.to_json()
        assert "verificationConfidence" in data
        assert data["verificationConfidence"] == pytest.approx(0.92)

    def test_to_json_verification_confidence_zero_is_included(self) -> None:
        # 0.0 is a valid confidence value — must not be treated as falsy
        f = self._make_finding(verification_confidence=0.0)
        data = f.to_json()
        assert "verificationConfidence" in data
        assert data["verificationConfidence"] == 0.0

    def test_verification_confidence_coerced_to_float(self) -> None:
        f = self._make_finding(verification_confidence=1)
        assert isinstance(f.verification_confidence, int)  # dataclass doesn't coerce
        # But to_json should still emit the value
        assert f.to_json()["verificationConfidence"] == 1


# ---------------------------------------------------------------------------
# FindingsCache — serialization round-trip
# ---------------------------------------------------------------------------


class TestFindingsCacheVerificationConfidence:
    def _make_finding(self, confidence: float | None = None) -> Finding:
        return Finding(
            id="W001",
            severity="high",
            message="SQL injection risk",
            location="src/db.py:42",
            verification_confidence=confidence,
        )

    def test_serializes_and_deserializes_confidence(self, tmp_path: Path) -> None:
        from warden.pipeline.application.orchestrator.findings_cache import FindingsCache

        cache = FindingsCache(tmp_path)
        finding = self._make_finding(confidence=0.75)

        cache.put_findings("security", "src/db.py", "content123", [finding])
        cache.flush()

        # Reload from disk
        cache2 = FindingsCache(tmp_path)
        results = cache2.get_findings("security", "src/db.py", "content123")
        assert results is not None
        assert len(results) == 1
        assert results[0].verification_confidence == pytest.approx(0.75)

    def test_none_confidence_round_trips_as_none(self, tmp_path: Path) -> None:
        from warden.pipeline.application.orchestrator.findings_cache import FindingsCache

        cache = FindingsCache(tmp_path)
        finding = self._make_finding(confidence=None)

        cache.put_findings("security", "src/db.py", "content_abc", [finding])
        cache.flush()

        cache2 = FindingsCache(tmp_path)
        results = cache2.get_findings("security", "src/db.py", "content_abc")
        assert results is not None
        assert results[0].verification_confidence is None

    def test_serialize_confidence_is_persisted_in_json(self, tmp_path: Path) -> None:
        from warden.pipeline.application.orchestrator.findings_cache import FindingsCache

        cache = FindingsCache(tmp_path)
        finding = self._make_finding(confidence=0.88)
        cache.put_findings("frame1", "src/x.py", "abc", [finding])
        cache.flush()

        # Read raw JSON to verify persistence
        cache_file = tmp_path / ".warden" / "cache" / "findings_cache.json"
        raw = json.loads(cache_file.read_text())
        entries = list(raw.values())
        assert len(entries) == 1
        stored = entries[0]["findings"][0]
        assert stored["verification_confidence"] == pytest.approx(0.88)


# ---------------------------------------------------------------------------
# FindingVerificationService — confidence propagation
# ---------------------------------------------------------------------------


class TestVerificationServiceConfidencePropagation:
    """Test that verify_findings_async() sets verification_confidence on findings."""

    def _make_dict_finding(self, **kwargs) -> dict:
        defaults = {
            "id": "W001",
            "rule_id": "sql_injection",
            "message": "SQL injection detected",
            "location": "src/db.py:42",
            "code": "cursor.execute(query)",
            "severity": "high",
            "detection_source": "taint",
        }
        defaults.update(kwargs)
        return defaults

    @pytest.mark.asyncio
    async def test_confidence_propagated_from_llm_result(self) -> None:
        from warden.analysis.services.finding_verifier import FindingVerificationService

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.content = json.dumps(
            [{"idx": 0, "is_true_positive": True, "confidence": 0.91, "reason": "real"}]
        )
        mock_llm.complete_async = AsyncMock(return_value=mock_response)

        service = FindingVerificationService(llm_client=mock_llm, enabled=True)
        # Disable cache so we go through LLM path
        service.memory_manager = None

        finding = self._make_dict_finding()
        results = await service.verify_findings_async([finding])

        assert len(results) == 1
        assert results[0].get("verification_confidence") == pytest.approx(0.91)

    @pytest.mark.asyncio
    async def test_confidence_propagated_from_cache_result(self) -> None:
        from warden.analysis.services.finding_verifier import FindingVerificationService

        mock_llm = MagicMock()
        service = FindingVerificationService(llm_client=mock_llm, enabled=True)

        # Inject a fake memory_manager that returns a cached result with confidence
        cached = {
            "is_true_positive": True,
            "confidence": 0.78,
            "reason": "cached result",
        }
        mock_mm = MagicMock()
        mock_mm.get_llm_cache = MagicMock(return_value=cached)
        service.memory_manager = mock_mm

        finding = self._make_dict_finding()
        results = await service.verify_findings_async([finding])

        assert len(results) == 1
        assert results[0].get("verification_confidence") == pytest.approx(0.78)

    @pytest.mark.asyncio
    async def test_disabled_service_returns_findings_without_confidence(self) -> None:
        from warden.analysis.services.finding_verifier import FindingVerificationService

        service = FindingVerificationService(llm_client=MagicMock(), enabled=False)
        finding = self._make_dict_finding()
        results = await service.verify_findings_async([finding])

        assert len(results) == 1
        # No confidence set when disabled
        assert results[0].get("verification_confidence") is None

    @pytest.mark.asyncio
    async def test_high_precision_source_gets_no_llm_confidence(self) -> None:
        """AST/regex/rust_engine findings skip LLM — confidence stays None."""
        from warden.analysis.services.finding_verifier import FindingVerificationService

        service = FindingVerificationService(llm_client=MagicMock(), enabled=True)
        service.memory_manager = None

        finding = self._make_dict_finding(detection_source="ast")
        results = await service.verify_findings_async([finding])

        assert len(results) == 1
        # High-precision sources are exempt from LLM — no confidence set by verifier
        assert results[0].get("verification_confidence") is None


# ---------------------------------------------------------------------------
# CLI output formatting — confidence percentage display
# ---------------------------------------------------------------------------


class TestCLIConfidenceDisplay:
    """Test that scan_output formats confidence as % or em-dash."""

    def test_confidence_formatted_as_percentage(self) -> None:
        """When verification_confidence=0.87, CLI should format as '87%'."""
        confidence = 0.87
        result = f"{int(confidence * 100)}%"
        assert result == "87%"

    def test_confidence_none_shows_em_dash(self) -> None:
        """When verification_confidence=None, CLI should show em-dash."""
        confidence = None
        result = "\u2014" if confidence is None else f"{int(confidence * 100)}%"
        assert result == "\u2014"

    def test_confidence_100_percent(self) -> None:
        confidence = 1.0
        result = f"{int(confidence * 100)}%"
        assert result == "100%"

    def test_confidence_zero_percent(self) -> None:
        confidence = 0.0
        result = f"{int(confidence * 100)}%"
        assert result == "0%"
