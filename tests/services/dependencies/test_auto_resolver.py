"""
Tests for warden.services.dependencies.auto_resolver

Verifies:
1. PACKAGE_MAP resolves pip names to import names correctly
2. require_package returns True for already-installed packages
3. require_package attempts install for missing packages
4. ensure_dependencies returns still-missing packages
5. _resolve_import_name handles known and unknown packages
"""

from unittest.mock import MagicMock, patch

import pytest

from warden.services.dependencies.auto_resolver import (
    PACKAGE_MAP,
    _is_importable,
    _resolve_import_name,
    ensure_dependencies,
    require_package,
)


class TestResolveImportName:
    """Test pip-name to import-name resolution."""

    def test_known_packages_resolved(self):
        """Known packages in PACKAGE_MAP should resolve correctly."""
        assert _resolve_import_name("sentence-transformers") == "sentence_transformers"
        assert _resolve_import_name("qdrant-client") == "qdrant_client"
        assert _resolve_import_name("grpcio") == "grpc"
        assert _resolve_import_name("tiktoken") == "tiktoken"
        assert _resolve_import_name("chromadb") == "chromadb"

    def test_unknown_package_falls_back_to_dash_replacement(self):
        """Unknown packages should replace dashes with underscores."""
        assert _resolve_import_name("my-cool-package") == "my_cool_package"

    def test_simple_name_unchanged(self):
        """Package names without dashes should pass through unchanged."""
        assert _resolve_import_name("requests") == "requests"


class TestIsImportable:
    """Test import availability checking."""

    def test_stdlib_importable(self):
        """Standard library modules should be importable."""
        assert _is_importable("os") is True
        assert _is_importable("sys") is True
        assert _is_importable("json") is True

    def test_nonexistent_not_importable(self):
        """Non-existent modules should not be importable."""
        assert _is_importable("definitely_not_a_real_package_xyz_123") is False


class TestRequirePackage:
    """Test require_package auto-install logic."""

    def test_already_installed_returns_true(self):
        """Packages that are already importable should return True without installing."""
        # 'json' is always available
        result = require_package("json")
        assert result is True

    @patch("warden.services.dependencies.auto_resolver._is_importable", return_value=False)
    @patch("subprocess.run")
    def test_missing_package_attempts_install(self, mock_run, mock_importable):
        """Missing package should trigger pip install subprocess."""
        mock_run.return_value = MagicMock(returncode=0)

        result = require_package("some-fake-package")

        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args
        cmd = args[0][0]
        assert "pip" in cmd
        assert "install" in cmd
        assert "some-fake-package" in cmd

    @patch("warden.services.dependencies.auto_resolver._is_importable", return_value=False)
    @patch("subprocess.run")
    def test_install_failure_returns_false(self, mock_run, mock_importable):
        """Failed pip install should return False."""
        mock_run.return_value = MagicMock(returncode=1, stderr=b"error")

        result = require_package("nonexistent-pkg")

        assert result is False

    @patch("warden.services.dependencies.auto_resolver._is_importable", return_value=False)
    @patch("subprocess.run", side_effect=Exception("subprocess failed"))
    def test_install_exception_returns_false(self, mock_run, mock_importable):
        """Exception during install should return False gracefully."""
        result = require_package("bad-package")
        assert result is False

    def test_custom_import_name_used(self):
        """Custom import_name should be checked instead of pip name."""
        # 'os' is importable, so providing import_name="os" should skip install
        result = require_package("some-pip-name", import_name="os")
        assert result is True


class TestEnsureDependencies:
    """Test batch dependency checking."""

    def test_all_present_returns_empty(self):
        """When all packages are importable, returns empty list."""
        # json and os are always available
        result = ensure_dependencies(["json", "os"])
        assert result == []

    @patch("warden.services.dependencies.auto_resolver.require_package")
    @patch("warden.services.dependencies.auto_resolver._is_importable", return_value=False)
    def test_missing_packages_attempted(self, mock_importable, mock_require):
        """Missing packages should be attempted via require_package."""
        mock_require.return_value = True

        result = ensure_dependencies(["fake-pkg-a", "fake-pkg-b"], context="test")

        assert result == []
        assert mock_require.call_count == 2

    @patch("warden.services.dependencies.auto_resolver.require_package")
    @patch("warden.services.dependencies.auto_resolver._is_importable", return_value=False)
    def test_still_missing_returned(self, mock_importable, mock_require):
        """Packages that fail to install should be returned."""
        mock_require.return_value = False

        result = ensure_dependencies(["fail-pkg-a", "fail-pkg-b"])

        assert "fail-pkg-a" in result
        assert "fail-pkg-b" in result

    @patch("warden.services.dependencies.auto_resolver.require_package")
    @patch("warden.services.dependencies.auto_resolver._is_importable")
    def test_mixed_present_and_missing(self, mock_importable, mock_require):
        """Mix of present and missing packages."""
        # First call: present. Second call: missing.
        mock_importable.side_effect = [True, False]
        mock_require.return_value = False

        result = ensure_dependencies(["present-pkg", "missing-pkg"])

        # Only missing-pkg should be in result
        assert result == ["missing-pkg"]
        # require_package only called for the missing one
        assert mock_require.call_count == 1


class TestPackageMap:
    """Test PACKAGE_MAP contents."""

    def test_all_entries_are_strings(self):
        """All keys and values should be strings."""
        for key, value in PACKAGE_MAP.items():
            assert isinstance(key, str)
            assert isinstance(value, str)

    def test_essential_packages_mapped(self):
        """Essential optional packages should be in the map."""
        assert "tiktoken" in PACKAGE_MAP
        assert "sentence-transformers" in PACKAGE_MAP
        assert "chromadb" in PACKAGE_MAP
        assert "qdrant-client" in PACKAGE_MAP
        assert "grpcio" in PACKAGE_MAP
