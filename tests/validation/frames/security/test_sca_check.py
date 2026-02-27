"""
Tests for SCA (Software Composition Analysis) OSV Vulnerability Check.

Covers:
- Version specifier stripping
- OSV query building
- OSV response parsing
- Vulnerability finding model
- Cache key computation
- SCA cache read/write
- Full SCA check integration (with mocked OSV API)
- Skip-SCA flag behavior
- Error handling on network failures
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.build_context.models import (
    BuildContext,
    BuildSystem,
    Dependency,
    DependencyType,
)
from warden.validation.frames.security._internal.sca_check import (
    SCACache,
    VulnerabilityFinding,
    _build_osv_query,
    _build_system_to_ecosystem,
    _compute_cache_key,
    _extract_affected_range,
    _extract_fix_version,
    _extract_reference_url,
    _extract_severity,
    _strip_version_specifier,
    parse_osv_response,
    run_sca_check,
)


# ============================================================================
# Version specifier stripping tests
# ============================================================================


class TestStripVersionSpecifier:
    """Tests for version specifier stripping."""

    def test_plain_version(self):
        assert _strip_version_specifier("1.2.3") == "1.2.3"

    def test_gte_specifier(self):
        assert _strip_version_specifier(">=1.2.3") == "1.2.3"

    def test_caret_specifier(self):
        assert _strip_version_specifier("^18.2.0") == "18.2.0"

    def test_tilde_specifier(self):
        assert _strip_version_specifier("~=3.0") == "3.0"

    def test_exact_specifier(self):
        assert _strip_version_specifier("==2.1.0") == "2.1.0"

    def test_wildcard(self):
        assert _strip_version_specifier("*") == ""

    def test_latest(self):
        assert _strip_version_specifier("latest") == ""

    def test_empty(self):
        assert _strip_version_specifier("") == ""

    def test_complex_specifier(self):
        assert _strip_version_specifier(">=1.0") == "1.0"


# ============================================================================
# Ecosystem mapping tests
# ============================================================================


class TestBuildSystemToEcosystem:
    """Tests for build system to OSV ecosystem mapping."""

    def test_pip_maps_to_pypi(self):
        assert _build_system_to_ecosystem(BuildSystem.PIP) == "PyPI"

    def test_poetry_maps_to_pypi(self):
        assert _build_system_to_ecosystem(BuildSystem.POETRY) == "PyPI"

    def test_npm_maps_to_npm(self):
        assert _build_system_to_ecosystem(BuildSystem.NPM) == "npm"

    def test_yarn_maps_to_npm(self):
        assert _build_system_to_ecosystem(BuildSystem.YARN) == "npm"

    def test_cargo_maps_to_crates(self):
        assert _build_system_to_ecosystem(BuildSystem.CARGO) == "crates.io"

    def test_unknown_returns_none(self):
        assert _build_system_to_ecosystem(BuildSystem.UNKNOWN) is None


# ============================================================================
# OSV query building tests
# ============================================================================


class TestBuildOsvQuery:
    """Tests for OSV query construction."""

    def test_query_with_version(self):
        dep = Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION)
        query = _build_osv_query(dep, "PyPI")
        assert query["package"]["name"] == "requests"
        assert query["package"]["ecosystem"] == "PyPI"
        assert query["version"] == "2.31.0"

    def test_query_strips_specifier(self):
        dep = Dependency(name="flask", version=">=3.0.0", type=DependencyType.PRODUCTION)
        query = _build_osv_query(dep, "PyPI")
        assert query["version"] == "3.0.0"

    def test_query_wildcard_version(self):
        dep = Dependency(name="react", version="*", type=DependencyType.PRODUCTION)
        query = _build_osv_query(dep, "npm")
        assert "version" not in query  # No version sent for wildcard


# ============================================================================
# OSV response parsing tests
# ============================================================================


class TestParseOsvResponse:
    """Tests for OSV response parsing."""

    def _make_osv_vuln(
        self,
        vuln_id: str = "GHSA-test-1234",
        summary: str = "Test vulnerability",
        package_name: str = "requests",
        introduced: str = "0",
        fixed: str = "2.32.0",
    ) -> dict[str, Any]:
        return {
            "id": vuln_id,
            "aliases": ["CVE-2024-12345"],
            "summary": summary,
            "severity": [{"type": "ECOSYSTEM", "score": "high"}],
            "affected": [
                {
                    "package": {"name": package_name, "ecosystem": "PyPI"},
                    "ranges": [
                        {
                            "type": "ECOSYSTEM",
                            "events": [
                                {"introduced": introduced},
                                {"fixed": fixed},
                            ],
                        }
                    ],
                }
            ],
            "references": [
                {"type": "ADVISORY", "url": "https://github.com/advisories/GHSA-test-1234"},
                {"type": "WEB", "url": "https://nvd.nist.gov/vuln/detail/CVE-2024-12345"},
            ],
        }

    def test_parse_single_vulnerability(self):
        deps = [Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION)]
        response = {
            "results": [
                {"vulns": [self._make_osv_vuln()]}
            ]
        }
        findings = parse_osv_response(response, deps)
        assert len(findings) == 1
        assert findings[0].dependency_name == "requests"
        assert findings[0].vuln_id == "GHSA-test-1234"
        assert "CVE-2024-12345" in findings[0].aliases
        assert findings[0].fix_version == "2.32.0"

    def test_parse_no_vulnerabilities(self):
        deps = [Dependency(name="flask", version="3.0.0", type=DependencyType.PRODUCTION)]
        response = {"results": [{"vulns": []}]}
        findings = parse_osv_response(response, deps)
        assert len(findings) == 0

    def test_parse_multiple_deps(self):
        deps = [
            Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION),
            Dependency(name="flask", version="2.0.0", type=DependencyType.PRODUCTION),
        ]
        response = {
            "results": [
                {"vulns": [self._make_osv_vuln()]},
                {"vulns": []},
            ]
        }
        findings = parse_osv_response(response, deps)
        assert len(findings) == 1
        assert findings[0].dependency_name == "requests"

    def test_parse_multiple_vulns_per_dep(self):
        deps = [Dependency(name="requests", version="2.20.0", type=DependencyType.PRODUCTION)]
        response = {
            "results": [
                {
                    "vulns": [
                        self._make_osv_vuln(vuln_id="GHSA-0001"),
                        self._make_osv_vuln(vuln_id="GHSA-0002"),
                    ]
                }
            ]
        }
        findings = parse_osv_response(response, deps)
        assert len(findings) == 2

    def test_empty_results(self):
        deps = [Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION)]
        response = {"results": []}
        findings = parse_osv_response(response, deps)
        assert len(findings) == 0


# ============================================================================
# Severity extraction tests
# ============================================================================


class TestExtractSeverity:
    """Tests for severity extraction from OSV vulnerability objects."""

    def test_ecosystem_severity(self):
        vuln = {"severity": [{"type": "ECOSYSTEM", "score": "high"}]}
        assert _extract_severity(vuln) == "high"

    def test_database_specific_severity(self):
        vuln = {"database_specific": {"severity": "CRITICAL"}}
        assert _extract_severity(vuln) == "critical"

    def test_cvss_vector(self):
        vuln = {"severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]}
        severity = _extract_severity(vuln)
        assert severity in ("critical", "high")

    def test_no_severity_info(self):
        vuln = {}
        assert _extract_severity(vuln) == "unknown"


# ============================================================================
# Affected range extraction tests
# ============================================================================


class TestExtractAffectedRange:
    """Tests for affected range extraction."""

    def test_introduced_and_fixed(self):
        vuln = {
            "affected": [
                {
                    "package": {"name": "requests"},
                    "ranges": [
                        {
                            "type": "ECOSYSTEM",
                            "events": [
                                {"introduced": "2.0.0"},
                                {"fixed": "2.32.0"},
                            ],
                        }
                    ],
                }
            ]
        }
        range_str = _extract_affected_range(vuln, "requests")
        assert ">= 2.0.0" in range_str
        assert "< 2.32.0" in range_str

    def test_no_affected_info(self):
        vuln = {}
        assert _extract_affected_range(vuln, "requests") == "unknown"


# ============================================================================
# Fix version extraction tests
# ============================================================================


class TestExtractFixVersion:
    """Tests for fix version extraction."""

    def test_fix_version_present(self):
        vuln = {
            "affected": [
                {
                    "package": {"name": "requests"},
                    "ranges": [
                        {
                            "type": "ECOSYSTEM",
                            "events": [
                                {"introduced": "0"},
                                {"fixed": "2.32.0"},
                            ],
                        }
                    ],
                }
            ]
        }
        assert _extract_fix_version(vuln, "requests") == "2.32.0"

    def test_no_fix_version(self):
        vuln = {
            "affected": [
                {
                    "package": {"name": "requests"},
                    "ranges": [
                        {
                            "type": "ECOSYSTEM",
                            "events": [{"introduced": "0"}],
                        }
                    ],
                }
            ]
        }
        assert _extract_fix_version(vuln, "requests") is None


# ============================================================================
# Reference URL extraction tests
# ============================================================================


class TestExtractReferenceUrl:
    """Tests for reference URL extraction."""

    def test_advisory_preferred(self):
        vuln = {
            "references": [
                {"type": "WEB", "url": "https://example.com"},
                {"type": "ADVISORY", "url": "https://github.com/advisories/GHSA-test"},
            ]
        }
        assert _extract_reference_url(vuln) == "https://github.com/advisories/GHSA-test"

    def test_fallback_to_web(self):
        vuln = {
            "references": [
                {"type": "WEB", "url": "https://example.com"},
            ]
        }
        assert _extract_reference_url(vuln) == "https://example.com"

    def test_no_references(self):
        vuln = {}
        assert _extract_reference_url(vuln) is None


# ============================================================================
# Cache key computation tests
# ============================================================================


class TestComputeCacheKey:
    """Tests for deterministic cache key computation."""

    def test_same_input_same_key(self):
        deps = [Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION)]
        key1 = _compute_cache_key(deps, "PyPI")
        key2 = _compute_cache_key(deps, "PyPI")
        assert key1 == key2

    def test_different_input_different_key(self):
        deps1 = [Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION)]
        deps2 = [Dependency(name="flask", version="3.0.0", type=DependencyType.PRODUCTION)]
        key1 = _compute_cache_key(deps1, "PyPI")
        key2 = _compute_cache_key(deps2, "PyPI")
        assert key1 != key2

    def test_order_independent(self):
        """Cache key should be order-independent."""
        dep_a = Dependency(name="flask", version="3.0.0", type=DependencyType.PRODUCTION)
        dep_b = Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION)
        key1 = _compute_cache_key([dep_a, dep_b], "PyPI")
        key2 = _compute_cache_key([dep_b, dep_a], "PyPI")
        assert key1 == key2


# ============================================================================
# SCA Cache tests
# ============================================================================


class TestSCACache:
    """Tests for the SCA file-based cache."""

    def test_get_missing_cache(self, tmp_path: Path):
        cache = SCACache(str(tmp_path))
        assert cache.get("nonexistent") is None

    def test_set_and_get(self, tmp_path: Path):
        cache = SCACache(str(tmp_path))
        result = {"passed": True, "findings": []}
        cache.set("test-key", result)
        retrieved = cache.get("test-key")
        assert retrieved is not None
        assert retrieved["passed"] is True

    def test_expired_cache(self, tmp_path: Path):
        cache = SCACache(str(tmp_path))
        cache_dir = tmp_path / ".warden" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "sca_cache.json"

        # Write expired entry
        entry = {
            "expired-key": {
                "cached_at": time.time() - 100000,  # well past TTL
                "result": {"passed": True, "findings": []},
            }
        }
        cache_file.write_text(json.dumps(entry), encoding="utf-8")

        assert cache.get("expired-key") is None

    def test_corrupted_cache_file(self, tmp_path: Path):
        cache = SCACache(str(tmp_path))
        cache_dir = tmp_path / ".warden" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "sca_cache.json"
        cache_file.write_text("not valid json!!!", encoding="utf-8")

        assert cache.get("any-key") is None


# ============================================================================
# VulnerabilityFinding model tests
# ============================================================================


class TestVulnerabilityFinding:
    """Tests for the VulnerabilityFinding data class."""

    def test_to_dict(self):
        finding = VulnerabilityFinding(
            dependency_name="requests",
            dependency_version="2.31.0",
            vuln_id="GHSA-test-1234",
            aliases=["CVE-2024-12345"],
            summary="Test vulnerability",
            severity="high",
            affected_range=">= 0, < 2.32.0",
            fix_version="2.32.0",
            reference_url="https://example.com",
        )
        d = finding.to_dict()
        assert d["dependency"] == "requests"
        assert d["version"] == "2.31.0"
        assert d["vulnId"] == "GHSA-test-1234"
        assert d["severity"] == "high"
        assert d["fixVersion"] == "2.32.0"
        assert d["referenceUrl"] == "https://example.com"


# ============================================================================
# Full SCA check integration tests (mocked OSV API)
# ============================================================================


class TestRunSCACheck:
    """Integration tests for run_sca_check with mocked HTTP."""

    def _make_context(
        self,
        build_system: BuildSystem = BuildSystem.PIP,
        deps: list[Dependency] | None = None,
    ) -> BuildContext:
        return BuildContext(
            build_system=build_system,
            project_path="/tmp/test-project",
            project_name="test-project",
            dependencies=deps or [],
        )

    @pytest.mark.asyncio
    async def test_skip_sca_flag(self):
        """--skip-sca should return immediately."""
        ctx = self._make_context(deps=[
            Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION),
        ])
        result = await run_sca_check(ctx, skip_sca=True)
        assert result["skipped"] is True
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_no_dependencies(self):
        """No deps should pass immediately."""
        ctx = self._make_context(deps=[])
        result = await run_sca_check(ctx)
        assert result["passed"] is True
        assert result["total_checked"] == 0

    @pytest.mark.asyncio
    async def test_unknown_ecosystem_skipped(self):
        """Unknown build system should be skipped."""
        ctx = self._make_context(
            build_system=BuildSystem.UNKNOWN,
            deps=[Dependency(name="foo", version="1.0.0", type=DependencyType.PRODUCTION)],
        )
        result = await run_sca_check(ctx)
        assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_clean_dependencies(self, tmp_path: Path):
        """All clean dependencies should pass."""
        deps = [
            Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION),
            Dependency(name="flask", version="3.0.0", type=DependencyType.PRODUCTION),
        ]
        ctx = self._make_context(deps=deps)

        osv_response = {"results": [{"vulns": []}, {"vulns": []}]}

        with patch(
            "warden.validation.frames.security._internal.sca_check.query_osv_batch",
            new_callable=AsyncMock,
            return_value=osv_response,
        ):
            result = await run_sca_check(
                ctx,
                project_path=str(tmp_path),
                use_cache=False,
            )
        assert result["passed"] is True
        assert result["vulnerabilities_found"] == 0

    @pytest.mark.asyncio
    async def test_vulnerable_dependency(self, tmp_path: Path):
        """A vulnerable dependency should be flagged."""
        deps = [
            Dependency(name="requests", version="2.25.0", type=DependencyType.PRODUCTION),
        ]
        ctx = self._make_context(deps=deps)

        osv_response = {
            "results": [
                {
                    "vulns": [
                        {
                            "id": "GHSA-test-vuln",
                            "aliases": ["CVE-2024-99999"],
                            "summary": "HTTP request smuggling in requests",
                            "severity": [{"type": "ECOSYSTEM", "score": "high"}],
                            "affected": [
                                {
                                    "package": {"name": "requests", "ecosystem": "PyPI"},
                                    "ranges": [
                                        {
                                            "type": "ECOSYSTEM",
                                            "events": [
                                                {"introduced": "2.0.0"},
                                                {"fixed": "2.31.0"},
                                            ],
                                        }
                                    ],
                                }
                            ],
                            "references": [
                                {"type": "ADVISORY", "url": "https://example.com/advisory"},
                            ],
                        }
                    ]
                }
            ]
        }

        with patch(
            "warden.validation.frames.security._internal.sca_check.query_osv_batch",
            new_callable=AsyncMock,
            return_value=osv_response,
        ):
            result = await run_sca_check(
                ctx,
                project_path=str(tmp_path),
                use_cache=False,
            )
        assert result["passed"] is False
        assert result["vulnerabilities_found"] == 1
        assert result["findings"][0]["vulnId"] == "GHSA-test-vuln"
        assert result["findings"][0]["fixVersion"] == "2.31.0"

    @pytest.mark.asyncio
    async def test_network_error_does_not_fail(self, tmp_path: Path):
        """Network errors should not cause the check to fail."""
        deps = [
            Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION),
        ]
        ctx = self._make_context(deps=deps)

        with patch(
            "warden.validation.frames.security._internal.sca_check.query_osv_batch",
            new_callable=AsyncMock,
            side_effect=Exception("Network timeout"),
        ):
            result = await run_sca_check(
                ctx,
                project_path=str(tmp_path),
                use_cache=False,
            )
        assert result["passed"] is True  # Graceful degradation
        assert "error" in result

    @pytest.mark.asyncio
    async def test_cache_is_used(self, tmp_path: Path):
        """Results should be cached and reused."""
        deps = [
            Dependency(name="flask", version="3.0.0", type=DependencyType.PRODUCTION),
        ]
        ctx = self._make_context(deps=deps)

        osv_response = {"results": [{"vulns": []}]}

        call_count = 0

        async def mock_query(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return osv_response

        with patch(
            "warden.validation.frames.security._internal.sca_check.query_osv_batch",
            side_effect=mock_query,
        ):
            # First call: should hit API
            result1 = await run_sca_check(
                ctx, project_path=str(tmp_path), use_cache=True,
            )
            assert call_count == 1
            assert result1["cached"] is False

            # Second call: should use cache
            result2 = await run_sca_check(
                ctx, project_path=str(tmp_path), use_cache=True,
            )
            assert call_count == 1  # No additional API call
            assert result2["cached"] is True

    @pytest.mark.asyncio
    async def test_result_structure(self, tmp_path: Path):
        """Verify the result dict has all expected keys."""
        deps = [
            Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION),
        ]
        ctx = self._make_context(deps=deps)

        with patch(
            "warden.validation.frames.security._internal.sca_check.query_osv_batch",
            new_callable=AsyncMock,
            return_value={"results": [{"vulns": []}]},
        ):
            result = await run_sca_check(
                ctx, project_path=str(tmp_path), use_cache=False,
            )

        expected_keys = {
            "passed", "findings", "total_checked",
            "vulnerabilities_found", "ecosystem", "skipped", "cached",
        }
        assert expected_keys.issubset(set(result.keys()))
