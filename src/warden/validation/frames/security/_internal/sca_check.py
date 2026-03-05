"""
Software Composition Analysis (SCA) Check - OSV Vulnerability Database.

Queries the OSV (Open Source Vulnerabilities) API to detect known CVEs
in project dependencies.

Features:
- Batch queries against OSV API for efficiency
- Local cache in .warden/cache/sca_cache.json (24h TTL)
- Reports CVE ID, severity, affected range, and fix version
- Supports --skip-sca flag for offline mode

References:
- https://osv.dev/
- https://google.github.io/osv.dev/post-v1-querybatch/
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from warden.build_context.models import BuildContext, BuildSystem, Dependency
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# Constants
# ============================================================================

OSV_QUERYBATCH_URL = "https://api.osv.dev/v1/querybatch"
CACHE_TTL_SECONDS = 86400  # 24 hours
CACHE_DIR_NAME = ".warden/cache"
CACHE_FILE_NAME = "sca_cache.json"
OSV_BATCH_SIZE = 1000  # OSV batch limit


def _build_system_to_ecosystem(build_system: BuildSystem) -> str | None:
    """
    Map BuildSystem enum to OSV ecosystem string.

    Args:
        build_system: Detected build system.

    Returns:
        OSV ecosystem string, or None if not mapped.
    """
    mapping: dict[BuildSystem, str] = {
        BuildSystem.PIP: "PyPI",
        BuildSystem.POETRY: "PyPI",
        BuildSystem.PIPENV: "PyPI",
        BuildSystem.CONDA: "PyPI",  # Conda packages often overlap with PyPI
        BuildSystem.NPM: "npm",
        BuildSystem.YARN: "npm",
        BuildSystem.PNPM: "npm",
        BuildSystem.CARGO: "crates.io",
        BuildSystem.GO_MOD: "Go",
        BuildSystem.MAVEN: "Maven",
        BuildSystem.GRADLE: "Maven",
        BuildSystem.BUNDLE: "RubyGems",
        BuildSystem.COMPOSER: "Packagist",
    }
    return mapping.get(build_system)


def _strip_version_specifier(version: str) -> str:
    """
    Strip version specifiers to extract a clean version string.

    Examples:
        ">=1.2.3" -> "1.2.3"
        "^18.2.0" -> "18.2.0"
        "~=3.0"   -> "3.0"
        "==2.1.0" -> "2.1.0"
        "1.2.3"   -> "1.2.3"
        "*"        -> ""

    Args:
        version: Raw version string with possible specifiers.

    Returns:
        Clean version string.
    """
    if not version or version in ("*", "latest", ""):
        return ""
    # Remove common specifiers
    cleaned = re.sub(r"^[~^>=<!]+", "", version.strip())
    # Remove trailing wildcards
    cleaned = cleaned.rstrip(".*")
    return cleaned.strip()


def _build_osv_query(dep: Dependency, ecosystem: str) -> dict[str, Any]:
    """
    Build a single OSV query object for a dependency.

    Args:
        dep: Dependency to query.
        ecosystem: OSV ecosystem string.

    Returns:
        OSV query dict.
    """
    version = _strip_version_specifier(dep.version)
    query: dict[str, Any] = {
        "package": {
            "name": dep.name,
            "ecosystem": ecosystem,
        }
    }
    if version:
        query["version"] = version
    return query


def _compute_cache_key(dependencies: list[Dependency], ecosystem: str) -> str:
    """
    Compute a deterministic cache key from dependencies list.

    Args:
        dependencies: List of dependencies.
        ecosystem: OSV ecosystem string.

    Returns:
        SHA256 hex digest as cache key.
    """
    key_parts = sorted(f"{dep.name}@{dep.version}" for dep in dependencies)
    key_string = f"{ecosystem}:" + "|".join(key_parts)
    return hashlib.sha256(key_string.encode()).hexdigest()


# ============================================================================
# Cache Management
# ============================================================================


class SCACache:
    """Local file-based cache for SCA results."""

    def __init__(self, project_path: str) -> None:
        """
        Initialize SCA cache.

        Args:
            project_path: Project root directory path.
        """
        self.cache_dir = Path(project_path) / CACHE_DIR_NAME
        self.cache_file = self.cache_dir / CACHE_FILE_NAME

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """
        Retrieve cached results if valid.

        Args:
            cache_key: Cache key string.

        Returns:
            Cached result dict or None if expired/missing.
        """
        if not self.cache_file.exists():
            return None

        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            entry = data.get(cache_key)
            if entry is None:
                return None

            # Check TTL
            cached_at = entry.get("cached_at", 0)
            if time.time() - cached_at > CACHE_TTL_SECONDS:
                logger.debug("sca_cache_expired", cache_key=cache_key[:12])
                return None

            logger.info("sca_cache_hit", cache_key=cache_key[:12])
            return entry.get("result")
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("sca_cache_read_error", error=str(exc))
            return None

    def set(self, cache_key: str, result: dict[str, Any]) -> None:
        """
        Store results in cache.

        Args:
            cache_key: Cache key string.
            result: Result dict to cache.
        """
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

            # Load existing cache data
            existing: dict[str, Any] = {}
            if self.cache_file.exists():
                try:
                    existing = json.loads(self.cache_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, TypeError):
                    existing = {}

            existing[cache_key] = {
                "cached_at": time.time(),
                "result": result,
            }

            self.cache_file.write_text(
                json.dumps(existing, indent=2, default=str),
                encoding="utf-8",
            )
            logger.debug("sca_cache_written", cache_key=cache_key[:12])
        except OSError as exc:
            logger.warning("sca_cache_write_error", error=str(exc))


# ============================================================================
# Vulnerability Finding
# ============================================================================


class VulnerabilityFinding:
    """A single known vulnerability finding from OSV."""

    def __init__(
        self,
        dependency_name: str,
        dependency_version: str,
        vuln_id: str,
        aliases: list[str],
        summary: str,
        severity: str,
        affected_range: str,
        fix_version: str | None,
        reference_url: str | None,
    ) -> None:
        self.dependency_name = dependency_name
        self.dependency_version = dependency_version
        self.vuln_id = vuln_id
        self.aliases = aliases
        self.summary = summary
        self.severity = severity
        self.affected_range = affected_range
        self.fix_version = fix_version
        self.reference_url = reference_url

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "dependency": self.dependency_name,
            "version": self.dependency_version,
            "vulnId": self.vuln_id,
            "aliases": self.aliases,
            "summary": self.summary,
            "severity": self.severity,
            "affectedRange": self.affected_range,
            "fixVersion": self.fix_version,
            "referenceUrl": self.reference_url,
        }


# ============================================================================
# OSV Response Parsing
# ============================================================================


def _extract_severity(vuln: dict[str, Any]) -> str:
    """
    Extract severity from an OSV vulnerability object.

    Falls back through severity fields in priority order.

    Args:
        vuln: OSV vulnerability dict.

    Returns:
        Severity string: "critical", "high", "medium", "low", or "unknown".
    """
    # Try database_specific severity first
    db_specific = vuln.get("database_specific", {})
    if isinstance(db_specific, dict):
        severity = db_specific.get("severity")
        if severity:
            return severity.lower()

    # Try CVSS from severity array
    severity_list = vuln.get("severity", [])
    if severity_list:
        for sev in severity_list:
            if isinstance(sev, dict):
                score_str = sev.get("score", "")
                # Parse CVSS vector for score if present
                if "CVSS:" in str(score_str):
                    # Rough severity mapping from CVSS score
                    return _cvss_vector_to_severity(str(score_str))
                sev_type = sev.get("type", "")
                if sev_type == "ECOSYSTEM":
                    return str(sev.get("score", "unknown")).lower()

    return "unknown"


def _cvss_vector_to_severity(vector: str) -> str:
    """
    Approximate severity from a CVSS vector string.

    This is a heuristic; for precise scoring use a CVSS library.

    Args:
        vector: CVSS vector string (e.g., "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H").

    Returns:
        Severity string.
    """
    # Very rough heuristic: count HIGH (H) impact values
    high_count = vector.upper().count("/C:H") + vector.upper().count("/I:H") + vector.upper().count("/A:H")
    if high_count >= 2:
        return "critical"
    elif high_count >= 1:
        return "high"
    elif "/C:L" in vector.upper() or "/I:L" in vector.upper():
        return "medium"
    return "low"


def _extract_affected_range(vuln: dict[str, Any], package_name: str) -> str:
    """
    Extract the affected version range from an OSV vulnerability.

    Args:
        vuln: OSV vulnerability dict.
        package_name: Name of the package to match.

    Returns:
        Human-readable affected range string.
    """
    affected_list = vuln.get("affected", [])
    for affected in affected_list:
        pkg = affected.get("package", {})
        if pkg.get("name", "").lower() == package_name.lower():
            ranges = affected.get("ranges", [])
            for r in ranges:
                events = r.get("events", [])
                parts = []
                for event in events:
                    if "introduced" in event:
                        parts.append(f">= {event['introduced']}")
                    elif "fixed" in event:
                        parts.append(f"< {event['fixed']}")
                    elif "last_affected" in event:
                        parts.append(f"<= {event['last_affected']}")
                if parts:
                    return ", ".join(parts)
            # Fallback to versions list
            versions = affected.get("versions", [])
            if versions:
                if len(versions) <= 5:
                    return ", ".join(versions)
                return f"{versions[0]} ... {versions[-1]} ({len(versions)} versions)"
    return "unknown"


def _extract_fix_version(vuln: dict[str, Any], package_name: str) -> str | None:
    """
    Extract the fix version from an OSV vulnerability.

    Args:
        vuln: OSV vulnerability dict.
        package_name: Name of the package to match.

    Returns:
        Fix version string, or None if not available.
    """
    affected_list = vuln.get("affected", [])
    for affected in affected_list:
        pkg = affected.get("package", {})
        if pkg.get("name", "").lower() == package_name.lower():
            ranges = affected.get("ranges", [])
            for r in ranges:
                events = r.get("events", [])
                for event in events:
                    if "fixed" in event:
                        return event["fixed"]
    return None


def _extract_reference_url(vuln: dict[str, Any]) -> str | None:
    """
    Extract the most relevant reference URL from an OSV vulnerability.

    Args:
        vuln: OSV vulnerability dict.

    Returns:
        URL string, or None.
    """
    references = vuln.get("references", [])
    # Prefer ADVISORY type, then WEB
    for ref in references:
        if ref.get("type") == "ADVISORY":
            return ref.get("url")
    for ref in references:
        if ref.get("type") == "WEB":
            return ref.get("url")
    if references:
        return references[0].get("url")
    return None


def parse_osv_response(
    response_data: dict[str, Any],
    dependencies: list[Dependency],
) -> list[VulnerabilityFinding]:
    """
    Parse the OSV querybatch response into VulnerabilityFinding objects.

    Args:
        response_data: Raw JSON response from OSV querybatch API.
        dependencies: Original list of dependencies (same order as queries).

    Returns:
        List of VulnerabilityFinding objects.
    """
    findings: list[VulnerabilityFinding] = []
    results = response_data.get("results", [])

    for idx, result in enumerate(results):
        if idx >= len(dependencies):
            break

        dep = dependencies[idx]
        vulns = result.get("vulns", [])

        for vuln in vulns:
            vuln_id = vuln.get("id", "UNKNOWN")
            aliases = vuln.get("aliases", [])
            summary = vuln.get("summary", vuln.get("details", "No description available"))

            # Truncate long summaries
            if len(summary) > 300:
                summary = summary[:297] + "..."

            findings.append(
                VulnerabilityFinding(
                    dependency_name=dep.name,
                    dependency_version=dep.version,
                    vuln_id=vuln_id,
                    aliases=aliases,
                    summary=summary,
                    severity=_extract_severity(vuln),
                    affected_range=_extract_affected_range(vuln, dep.name),
                    fix_version=_extract_fix_version(vuln, dep.name),
                    reference_url=_extract_reference_url(vuln),
                )
            )

    return findings


# ============================================================================
# Main SCA Check
# ============================================================================


async def query_osv_batch(
    dependencies: list[Dependency],
    ecosystem: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """
    Query the OSV querybatch API for vulnerabilities.

    Args:
        dependencies: List of dependencies to check.
        ecosystem: OSV ecosystem string (e.g., "PyPI", "npm").
        timeout: HTTP timeout in seconds.

    Returns:
        Raw OSV API response dict.

    Raises:
        httpx.HTTPError: On network/API errors.
    """
    import httpx

    queries = [_build_osv_query(dep, ecosystem) for dep in dependencies]

    # OSV supports batch queries up to 1000
    all_results: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        for batch_start in range(0, len(queries), OSV_BATCH_SIZE):
            batch = queries[batch_start : batch_start + OSV_BATCH_SIZE]
            payload = {"queries": batch}

            logger.info(
                "osv_query_batch",
                batch_start=batch_start,
                batch_size=len(batch),
                ecosystem=ecosystem,
            )

            response = await client.post(OSV_QUERYBATCH_URL, json=payload)
            response.raise_for_status()

            data = response.json()
            batch_results = data.get("results", [])
            all_results.extend(batch_results)

    return {"results": all_results}


async def run_sca_check(
    build_context: BuildContext,
    skip_sca: bool = False,
    project_path: str | None = None,
    use_cache: bool = True,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """
    Run SCA vulnerability check against the OSV database.

    This is the top-level entry point for the SCA check.

    Args:
        build_context: Parsed build context with dependencies.
        skip_sca: If True, skip the check entirely (offline mode / --skip-sca flag).
        project_path: Project root path (for cache storage). Defaults to build_context.project_path.
        use_cache: Whether to use local cache.
        timeout: HTTP timeout in seconds.

    Returns:
        Dictionary with check results:
        {
            "passed": bool,
            "findings": list[dict],
            "total_checked": int,
            "vulnerabilities_found": int,
            "ecosystem": str,
            "skipped": bool,
            "cached": bool,
        }
    """
    ecosystem = _build_system_to_ecosystem(build_context.build_system)
    proj_path = project_path or build_context.project_path

    # --skip-sca flag
    if skip_sca:
        logger.info("sca_check_skipped", reason="skip_sca_flag")
        return {
            "passed": True,
            "findings": [],
            "total_checked": 0,
            "vulnerabilities_found": 0,
            "ecosystem": build_context.build_system.name,
            "skipped": True,
            "cached": False,
        }

    all_deps = build_context.get_all_dependencies()

    if not all_deps:
        logger.info("sca_check_skipped", reason="no_dependencies")
        return {
            "passed": True,
            "findings": [],
            "total_checked": 0,
            "vulnerabilities_found": 0,
            "ecosystem": build_context.build_system.name,
            "skipped": False,
            "cached": False,
        }

    if ecosystem is None:
        logger.warning(
            "sca_check_skipped",
            reason="unsupported_ecosystem",
            build_system=build_context.build_system.name,
        )
        return {
            "passed": True,
            "findings": [],
            "total_checked": len(all_deps),
            "vulnerabilities_found": 0,
            "ecosystem": build_context.build_system.name,
            "skipped": True,
            "cached": False,
        }

    # Check cache
    cache = SCACache(proj_path)
    cache_key = _compute_cache_key(all_deps, ecosystem)

    if use_cache:
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            cached_result["cached"] = True
            return cached_result

    # Query OSV API
    try:
        osv_response = await query_osv_batch(
            dependencies=all_deps,
            ecosystem=ecosystem,
            timeout=timeout,
        )
    except Exception as exc:
        logger.error("osv_query_failed", error=str(exc))
        return {
            "passed": True,  # Do not fail on network errors
            "findings": [],
            "total_checked": len(all_deps),
            "vulnerabilities_found": 0,
            "ecosystem": build_context.build_system.name,
            "skipped": False,
            "cached": False,
            "error": str(exc),
        }

    findings = parse_osv_response(osv_response, all_deps)

    result: dict[str, Any] = {
        "passed": len(findings) == 0,
        "findings": [f.to_dict() for f in findings],
        "total_checked": len(all_deps),
        "vulnerabilities_found": len(findings),
        "ecosystem": build_context.build_system.name,
        "skipped": False,
        "cached": False,
    }

    # Store in cache
    if use_cache:
        cache.set(cache_key, result)

    logger.info(
        "sca_check_complete",
        total_deps=len(all_deps),
        vulnerabilities=len(findings),
        ecosystem=ecosystem,
    )

    return result
