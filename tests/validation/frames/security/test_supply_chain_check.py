"""
Tests for Supply Chain Typosquatting / Slopsquatting Detection.

Covers:
- Levenshtein distance computation
- Package name normalization
- Typosquatting detection for Python (PyPI) ecosystem
- Typosquatting detection for JavaScript (npm) ecosystem
- Prefix/suffix manipulation detection
- Full supply chain check integration
- Edge cases (empty deps, unknown ecosystem)
"""

import pytest

from warden.build_context.models import (
    BuildContext,
    BuildSystem,
    Dependency,
    DependencyType,
)
from warden.validation.frames.security._internal.supply_chain_check import (
    TyposquatFinding,
    _is_common_prefix_suffix_swap,
    _levenshtein_distance,
    _normalize_package_name,
    check_typosquatting,
    run_supply_chain_check,
)


# ============================================================================
# Levenshtein distance tests
# ============================================================================


class TestLevenshteinDistance:
    """Tests for the Levenshtein distance function."""

    def test_identical_strings(self):
        assert _levenshtein_distance("requests", "requests") == 0

    def test_single_substitution(self):
        assert _levenshtein_distance("requests", "reqeusts") == 2

    def test_single_insertion(self):
        assert _levenshtein_distance("flask", "flaask") == 1

    def test_single_deletion(self):
        assert _levenshtein_distance("django", "djano") == 1

    def test_empty_vs_nonempty(self):
        assert _levenshtein_distance("", "abc") == 3

    def test_both_empty(self):
        assert _levenshtein_distance("", "") == 0

    def test_completely_different(self):
        assert _levenshtein_distance("abc", "xyz") == 3

    def test_one_char_off(self):
        # "requets" vs "requests" - missing 's'
        assert _levenshtein_distance("requets", "requests") == 1

    def test_transposition(self):
        # "reqeusts" vs "requests" - 'ue' swapped to 'eu'
        dist = _levenshtein_distance("reqeusts", "requests")
        assert dist == 2  # Two substitutions (not transposition-aware)

    def test_known_typosquat_rqeuests(self):
        # A real-world typosquatting example
        assert _levenshtein_distance("rqeuests", "requests") == 2


# ============================================================================
# Package name normalization tests
# ============================================================================


class TestNormalizePackageName:
    """Tests for package name normalization."""

    def test_lowercase(self):
        assert _normalize_package_name("Flask") == "flask"

    def test_underscore_to_hyphen(self):
        assert _normalize_package_name("python_dateutil") == "python-dateutil"

    def test_npm_scope_stripped(self):
        assert _normalize_package_name("@types/node") == "node"

    def test_already_normalized(self):
        assert _normalize_package_name("requests") == "requests"

    def test_whitespace_stripped(self):
        assert _normalize_package_name("  flask  ") == "flask"


# ============================================================================
# Prefix/suffix swap detection tests
# ============================================================================


class TestPrefixSuffixSwap:
    """Tests for common prefix/suffix manipulation patterns."""

    def test_python_prefix(self):
        assert _is_common_prefix_suffix_swap("python-requests", "requests") is True

    def test_py_prefix(self):
        assert _is_common_prefix_suffix_swap("py-flask", "flask") is True

    def test_js_suffix(self):
        assert _is_common_prefix_suffix_swap("lodash-js", "lodash") is True

    def test_number_suffix(self):
        assert _is_common_prefix_suffix_swap("flask2", "flask") is True

    def test_no_match(self):
        assert _is_common_prefix_suffix_swap("totally-different", "flask") is False

    def test_dev_suffix(self):
        assert _is_common_prefix_suffix_swap("react-dev", "react") is True


# ============================================================================
# Typosquatting detection tests (Python ecosystem)
# ============================================================================


class TestTyposquattingPython:
    """Tests for typosquatting detection in Python ecosystem."""

    def _make_dep(self, name: str, version: str = "1.0.0") -> Dependency:
        return Dependency(
            name=name,
            version=version,
            type=DependencyType.PRODUCTION,
        )

    def test_legitimate_package_not_flagged(self):
        """A real popular package should not be flagged."""
        deps = [self._make_dep("requests")]
        findings = check_typosquatting(deps, BuildSystem.PIP)
        assert len(findings) == 0

    def test_typosquat_reqeusts(self):
        """A classic typosquat with edit distance 2."""
        deps = [self._make_dep("reqeusts")]
        findings = check_typosquatting(deps, BuildSystem.PIP, max_distance=2)
        assert len(findings) == 1
        assert findings[0].similar_to == "requests"
        assert findings[0].distance <= 2

    def test_typosquat_one_char_off(self):
        """Edit distance 1 should be flagged as critical."""
        deps = [self._make_dep("requets")]
        findings = check_typosquatting(deps, BuildSystem.PIP, max_distance=2)
        assert len(findings) == 1
        assert findings[0].severity == "critical"

    def test_unrelated_package_not_flagged(self):
        """A package with a unique name far from any popular one should not be flagged."""
        deps = [self._make_dep("zzz-my-private-internal-lib")]
        findings = check_typosquatting(deps, BuildSystem.PIP)
        assert len(findings) == 0

    def test_multiple_deps_mixed(self):
        """Test with a mix of legitimate and suspicious packages."""
        deps = [
            self._make_dep("requests"),    # legit
            self._make_dep("requets"),     # typo (distance 1)
            self._make_dep("flask"),       # legit
            self._make_dep("my-internal"), # not similar to anything
        ]
        findings = check_typosquatting(deps, BuildSystem.PIP)
        assert len(findings) == 1
        assert findings[0].dependency_name == "requets"

    def test_max_distance_zero(self):
        """With max_distance=0, only exact matches should pass (nothing flagged)."""
        deps = [self._make_dep("requets")]
        findings = check_typosquatting(deps, BuildSystem.PIP, max_distance=0)
        # Distance 0 means only flag exact (which would be the package itself) -- so nothing flagged
        assert len(findings) == 0

    def test_poetry_ecosystem(self):
        """Poetry should use PyPI popular packages."""
        deps = [self._make_dep("djngo")]  # close to "django"
        findings = check_typosquatting(deps, BuildSystem.POETRY)
        assert len(findings) >= 1
        assert any(f.similar_to == "django" for f in findings)


# ============================================================================
# Typosquatting detection tests (JavaScript ecosystem)
# ============================================================================


class TestTyposquattingJavaScript:
    """Tests for typosquatting detection in JavaScript ecosystem."""

    def _make_dep(self, name: str, version: str = "1.0.0") -> Dependency:
        return Dependency(
            name=name,
            version=version,
            type=DependencyType.PRODUCTION,
        )

    def test_legitimate_npm_package(self):
        """Real popular npm package should not be flagged."""
        deps = [self._make_dep("express")]
        findings = check_typosquatting(deps, BuildSystem.NPM)
        assert len(findings) == 0

    def test_typosquat_expres(self):
        """Typosquat 'expres' (missing 's') should be flagged."""
        deps = [self._make_dep("expres")]
        findings = check_typosquatting(deps, BuildSystem.NPM)
        assert len(findings) == 1
        assert findings[0].similar_to == "express"

    def test_typosquat_lodahs(self):
        """Typosquat 'lodahs' should be flagged (distance 2 from 'lodash')."""
        deps = [self._make_dep("lodahs")]
        findings = check_typosquatting(deps, BuildSystem.NPM, max_distance=2)
        assert len(findings) >= 1

    def test_yarn_uses_js_packages(self):
        """Yarn should use npm popular packages."""
        deps = [self._make_dep("recat")]  # close to "react"
        findings = check_typosquatting(deps, BuildSystem.YARN)
        assert len(findings) >= 1
        assert any(f.similar_to == "react" for f in findings)


# ============================================================================
# run_supply_chain_check integration tests
# ============================================================================


class TestRunSupplyChainCheck:
    """Integration tests for the full supply chain check."""

    def _make_context(
        self,
        build_system: BuildSystem,
        deps: list[Dependency] | None = None,
    ) -> BuildContext:
        return BuildContext(
            build_system=build_system,
            project_path="/tmp/test-project",
            project_name="test-project",
            dependencies=deps or [],
        )

    def test_no_dependencies(self):
        """Should pass with no dependencies."""
        ctx = self._make_context(BuildSystem.PIP, deps=[])
        result = run_supply_chain_check(ctx)
        assert result["passed"] is True
        assert result["total_checked"] == 0
        assert result["flagged"] == 0

    def test_clean_dependencies(self):
        """Should pass with all legitimate dependencies."""
        deps = [
            Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION),
            Dependency(name="flask", version="3.0.0", type=DependencyType.PRODUCTION),
            Dependency(name="django", version="5.0.0", type=DependencyType.PRODUCTION),
        ]
        ctx = self._make_context(BuildSystem.PIP, deps=deps)
        result = run_supply_chain_check(ctx)
        assert result["passed"] is True
        assert result["total_checked"] == 3
        assert result["flagged"] == 0

    def test_suspicious_dependency(self):
        """Should fail with a typosquatted dependency."""
        deps = [
            Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION),
            Dependency(name="requets", version="1.0.0", type=DependencyType.PRODUCTION),
        ]
        ctx = self._make_context(BuildSystem.PIP, deps=deps)
        result = run_supply_chain_check(ctx)
        assert result["passed"] is False
        assert result["flagged"] >= 1
        assert len(result["findings"]) >= 1

    def test_unknown_ecosystem(self):
        """Unknown build system should check against combined package sets."""
        deps = [
            Dependency(name="requets", version="1.0.0", type=DependencyType.PRODUCTION),
        ]
        ctx = self._make_context(BuildSystem.UNKNOWN, deps=deps)
        result = run_supply_chain_check(ctx)
        assert result["flagged"] >= 1

    def test_result_structure(self):
        """Verify the result dict structure."""
        deps = [
            Dependency(name="requests", version="2.31.0", type=DependencyType.PRODUCTION),
        ]
        ctx = self._make_context(BuildSystem.PIP, deps=deps)
        result = run_supply_chain_check(ctx)
        assert "passed" in result
        assert "findings" in result
        assert "total_checked" in result
        assert "flagged" in result
        assert "ecosystem" in result


# ============================================================================
# TyposquatFinding model tests
# ============================================================================


class TestTyposquatFinding:
    """Tests for the TyposquatFinding data class."""

    def test_to_dict(self):
        finding = TyposquatFinding(
            dependency_name="requets",
            similar_to="requests",
            distance=1,
            reason="Potential typosquat",
            severity="critical",
        )
        d = finding.to_dict()
        assert d["dependency"] == "requets"
        assert d["similarTo"] == "requests"
        assert d["distance"] == 1
        assert d["severity"] == "critical"
