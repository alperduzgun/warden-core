"""
Tests for PhantomPackageCheck - Phantom Package Detection.

Covers:
- Known/stdlib Python packages → no finding (no network call)
- Phantom Python package (404 from PyPI) → HIGH severity finding
- Phantom JS package (404 from npm) → HIGH severity finding
- Network timeout → graceful skip (no crash, no finding)
- Relative imports → skipped
- Unsupported language → skipped
- Max-package cap (> 20 candidates) → only first 20 checked
- Session-level cache hit → single HTTP call per package
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from warden.validation.domain.check import CheckSeverity
from warden.validation.domain.frame import CodeFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_code_file(content: str, language: str = "python", path: str = "test.py") -> CodeFile:
    return CodeFile(path=path, content=content, language=language)


def _phantom_findings(result):
    return [f for f in result.findings if f.check_id == "phantom-package"]


def _make_response(status_code: int) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    return resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def check():
    """Return a fresh PhantomPackageCheck instance."""
    # Import here so the module path manipulation in frame.py doesn't matter
    import sys
    from pathlib import Path

    internal_dir = str(
        Path(__file__).resolve().parents[4]
        / "src/warden/validation/frames/security"
    )
    if internal_dir not in sys.path:
        sys.path.insert(0, internal_dir)

    from _internal.phantom_package_check import PhantomPackageCheck, _REGISTRY_CACHE

    # Clear session cache between tests
    _REGISTRY_CACHE.clear()

    return PhantomPackageCheck()


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the module-level registry cache before every test."""
    import sys
    from pathlib import Path

    internal_dir = str(
        Path(__file__).resolve().parents[4]
        / "src/warden/validation/frames/security"
    )
    if internal_dir not in sys.path:
        sys.path.insert(0, internal_dir)

    from _internal.phantom_package_check import _REGISTRY_CACHE
    _REGISTRY_CACHE.clear()
    yield
    _REGISTRY_CACHE.clear()


# ---------------------------------------------------------------------------
# stdlib / known packages → no network, no finding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stdlib_import_skipped(check):
    """Python stdlib imports must not produce findings."""
    code = "import os\nimport sys\nimport re\n"
    result = await check.execute_async(_make_code_file(code))
    assert result.passed
    assert _phantom_findings(result) == []


@pytest.mark.asyncio
async def test_known_python_package_skipped(check):
    """Well-known packages like 'requests' must not trigger network calls."""
    code = "import requests\nimport numpy\nimport flask\n"

    # If a network call is made the test will fail with a real HTTP error
    # (or the mock won't be called). We patch to guarantee isolation.
    with patch("_internal.phantom_package_check._package_exists", new_callable=AsyncMock) as mock_exists:
        result = await check.execute_async(_make_code_file(code))

    # _package_exists must NOT have been called for known packages
    mock_exists.assert_not_called()
    assert result.passed
    assert _phantom_findings(result) == []


@pytest.mark.asyncio
async def test_known_js_package_skipped(check):
    """Well-known JS packages like 'react' must not trigger network calls."""
    code = "import React from 'react';\nconst axios = require('axios');\n"

    with patch("_internal.phantom_package_check._package_exists", new_callable=AsyncMock) as mock_exists:
        result = await check.execute_async(_make_code_file(
            code, language="javascript", path="app.js"
        ))

    mock_exists.assert_not_called()
    assert result.passed


# ---------------------------------------------------------------------------
# Phantom Python package → HIGH finding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_phantom_python_package_flagged(check):
    """A package that returns 404 from PyPI must be reported as HIGH severity."""
    code = "import nonexistent_hallucinated_pkg_xyz\n"

    async def fake_exists(ecosystem, package):
        return False  # 404 simulation

    with patch("_internal.phantom_package_check._package_exists", side_effect=fake_exists):
        result = await check.execute_async(_make_code_file(code))

    findings = _phantom_findings(result)
    assert not result.passed
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == CheckSeverity.HIGH
    assert "nonexistent_hallucinated_pkg_xyz" in finding.message
    assert "pypi" in finding.message.lower() or "PyPI" in finding.message


@pytest.mark.asyncio
async def test_phantom_python_package_location(check):
    """Finding location must point to the correct file and line number."""
    code = "import os\nimport ghost_package_abc\n"

    async def fake_exists(ecosystem, package):
        return False

    with patch("_internal.phantom_package_check._package_exists", side_effect=fake_exists):
        result = await check.execute_async(_make_code_file(code, path="src/app.py"))

    findings = _phantom_findings(result)
    assert len(findings) == 1
    assert "src/app.py" in findings[0].location
    assert ":2" in findings[0].location  # Line 2


@pytest.mark.asyncio
async def test_existing_python_package_no_finding(check):
    """A package that exists on PyPI must not be reported."""
    code = "import some_real_package\n"

    async def fake_exists(ecosystem, package):
        return True  # 200 simulation

    with patch("_internal.phantom_package_check._package_exists", side_effect=fake_exists):
        result = await check.execute_async(_make_code_file(code))

    assert result.passed
    assert _phantom_findings(result) == []


# ---------------------------------------------------------------------------
# Phantom JS package → HIGH finding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_phantom_js_package_flagged(check):
    """A JS package that 404s on npm must be reported."""
    code = "import something from 'ghost-package-xyz-hallucinated';\n"

    async def fake_exists(ecosystem, package):
        return False

    with patch("_internal.phantom_package_check._package_exists", side_effect=fake_exists):
        result = await check.execute_async(_make_code_file(
            code, language="javascript", path="index.js"
        ))

    findings = _phantom_findings(result)
    assert not result.passed
    assert len(findings) == 1
    assert findings[0].severity == CheckSeverity.HIGH
    assert "ghost-package-xyz-hallucinated" in findings[0].message


@pytest.mark.asyncio
async def test_require_phantom_js_package_flagged(check):
    """CommonJS require() of a non-existent package must be flagged."""
    code = "const lib = require('phantom-lib-does-not-exist');\n"

    async def fake_exists(ecosystem, package):
        return False

    with patch("_internal.phantom_package_check._package_exists", side_effect=fake_exists):
        result = await check.execute_async(_make_code_file(
            code, language="javascript", path="server.js"
        ))

    findings = _phantom_findings(result)
    assert len(findings) >= 1


# ---------------------------------------------------------------------------
# Network timeout → graceful skip (no crash, no finding)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_produces_no_finding(check):
    """A timeout must be swallowed — the check must not crash or report a finding."""
    code = "import mystery_package_timeout_test\n"

    async def raise_timeout(ecosystem, package):
        raise httpx.TimeoutException("timed out")

    with patch("_internal.phantom_package_check._package_exists", side_effect=raise_timeout):
        result = await check.execute_async(_make_code_file(code))

    # No crash, no finding (graceful degradation)
    assert result.passed
    assert _phantom_findings(result) == []
    assert result.metadata["packages_skipped"] == 1


@pytest.mark.asyncio
async def test_connect_error_produces_no_finding(check):
    """A connection error must be handled gracefully."""
    code = "import mystery_package_connect_error\n"

    async def raise_connect(ecosystem, package):
        raise httpx.ConnectError("connection refused")

    with patch("_internal.phantom_package_check._package_exists", side_effect=raise_connect):
        result = await check.execute_async(_make_code_file(code))

    assert result.passed
    assert result.metadata["packages_skipped"] == 1


# ---------------------------------------------------------------------------
# Relative imports → skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_relative_import_skipped(check):
    """Relative imports (from . import x) must not be checked against the registry."""
    code = "from . import utils\nfrom ..models import User\n"

    with patch("_internal.phantom_package_check._package_exists", new_callable=AsyncMock) as mock_exists:
        result = await check.execute_async(_make_code_file(code))

    mock_exists.assert_not_called()
    assert result.passed


# ---------------------------------------------------------------------------
# Unsupported language → skipped entirely
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unsupported_language_skipped(check):
    """Go / Ruby / etc. files must be skipped — not checked at all."""
    code = 'import "fmt"\nimport "net/http"\n'

    with patch("_internal.phantom_package_check._package_exists", new_callable=AsyncMock) as mock_exists:
        result = await check.execute_async(_make_code_file(code, language="go", path="main.go"))

    mock_exists.assert_not_called()
    assert result.passed
    assert result.metadata.get("skipped") is True


# ---------------------------------------------------------------------------
# Max-package cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_package_cap(check):
    """More than 20 unknown packages must result in at most 20 registry lookups."""
    imports = "\n".join(f"import fake_hallucinated_pkg_{i}" for i in range(30))
    code = imports

    call_count = 0

    async def counting_exists(ecosystem, package):
        nonlocal call_count
        call_count += 1
        return True  # all exist → no findings

    with patch("_internal.phantom_package_check._package_exists", side_effect=counting_exists):
        result = await check.execute_async(_make_code_file(code))

    assert call_count <= 20, f"Expected at most 20 registry calls, got {call_count}"
    assert result.passed


# ---------------------------------------------------------------------------
# Session cache — single HTTP call per unique package
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_cache_hit(check):
    """The same package imported twice in the same scan must only hit the registry once."""
    code = "import ghost_cached_pkg\nimport ghost_cached_pkg\n"

    call_count = 0

    async def counting_exists(ecosystem, package):
        nonlocal call_count
        call_count += 1
        return False  # phantom

    with patch("_internal.phantom_package_check._package_exists", side_effect=counting_exists):
        result = await check.execute_async(_make_code_file(code))

    # Deduplication in extract loop → only one call
    assert call_count == 1
    assert len(_phantom_findings(result)) == 1


# ---------------------------------------------------------------------------
# Metadata sanity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_result_metadata_present(check):
    """CheckResult metadata must contain ecosystem and counts."""
    code = "import os\n"
    result = await check.execute_async(_make_code_file(code))

    assert "ecosystem" in result.metadata
    assert "packages_checked" in result.metadata
    assert "packages_skipped" in result.metadata
    assert "packages_flagged" in result.metadata
    assert result.metadata["ecosystem"] == "pypi"


@pytest.mark.asyncio
async def test_js_metadata_ecosystem(check):
    """JavaScript files must report npm as the ecosystem."""
    code = "import React from 'react';\n"
    result = await check.execute_async(_make_code_file(
        code, language="javascript", path="app.js"
    ))

    assert result.metadata.get("ecosystem") == "npm"


# ---------------------------------------------------------------------------
# Suggestion and documentation URL in findings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finding_has_suggestion_and_url(check):
    """Findings must include a suggestion and a documentation URL."""
    code = "import hallucinated_module_no_exist\n"

    async def fake_exists(ecosystem, package):
        return False

    with patch("_internal.phantom_package_check._package_exists", side_effect=fake_exists):
        result = await check.execute_async(_make_code_file(code))

    findings = _phantom_findings(result)
    assert len(findings) == 1
    assert findings[0].suggestion is not None
    assert "pypi.org" in findings[0].suggestion.lower() or "pypi" in findings[0].suggestion.lower()
    assert findings[0].documentation_url is not None
