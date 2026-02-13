"""E2E test configuration and fixtures.

Pre-flight checks run once per session to detect environment capabilities.
Tests that need specific services use markers to auto-skip when unavailable.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_PROJECT = FIXTURES_DIR / "sample_project"


# ---------------------------------------------------------------------------
# Pre-flight checks (run once, cached for the session)
# ---------------------------------------------------------------------------

def _check_ollama() -> bool:
    """Check if Ollama is reachable at localhost:11434."""
    try:
        import httpx
        resp = httpx.get("http://localhost:11434/", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def _check_git() -> bool:
    """Check if git is available and functional."""
    try:
        result = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_warden_importable() -> bool:
    """Check if warden package is importable."""
    try:
        from warden.main import app  # noqa: F401
        return True
    except Exception:
        return False


def _check_warden_binary() -> bool:
    """Check if ``warden`` binary is available on PATH."""
    return shutil.which("warden") is not None


def _check_fixture_integrity() -> list[str]:
    """Validate fixture project has required files. Returns list of errors."""
    errors = []
    required = [
        SAMPLE_PROJECT / ".warden" / "config.yaml",
        SAMPLE_PROJECT / "src" / "vulnerable.py",
        SAMPLE_PROJECT / "src" / "clean.py",
        SAMPLE_PROJECT / "pyproject.toml",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"Missing fixture file: {path.relative_to(FIXTURES_DIR)}")

    # Validate config is parseable
    config_path = SAMPLE_PROJECT / ".warden" / "config.yaml"
    if config_path.exists():
        try:
            import yaml
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            if not cfg.get("project", {}).get("name"):
                errors.append("Fixture config.yaml missing project.name")
            if not cfg.get("frames"):
                errors.append("Fixture config.yaml missing frames section")
        except Exception as e:
            errors.append(f"Fixture config.yaml parse error: {e}")

    return errors


# Cache results at module level (evaluated once per session)
_OLLAMA_AVAILABLE: bool | None = None
_GIT_AVAILABLE: bool | None = None
_WARDEN_IMPORTABLE: bool | None = None
_WARDEN_BINARY: bool | None = None


def _get_ollama_available() -> bool:
    global _OLLAMA_AVAILABLE
    if _OLLAMA_AVAILABLE is None:
        _OLLAMA_AVAILABLE = _check_ollama()
    return _OLLAMA_AVAILABLE


def _get_git_available() -> bool:
    global _GIT_AVAILABLE
    if _GIT_AVAILABLE is None:
        _GIT_AVAILABLE = _check_git()
    return _GIT_AVAILABLE


def _get_warden_importable() -> bool:
    global _WARDEN_IMPORTABLE
    if _WARDEN_IMPORTABLE is None:
        _WARDEN_IMPORTABLE = _check_warden_importable()
    return _WARDEN_IMPORTABLE


def _get_warden_binary() -> bool:
    global _WARDEN_BINARY
    if _WARDEN_BINARY is None:
        _WARDEN_BINARY = _check_warden_binary()
    return _WARDEN_BINARY


# ---------------------------------------------------------------------------
# Pytest hooks
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end tests")
    config.addinivalue_line("markers", "acceptance: subprocess-based acceptance tests")
    config.addinivalue_line("markers", "requires_ollama: test needs Ollama running locally")
    config.addinivalue_line("markers", "requires_git: test needs git CLI")
    config.addinivalue_line("markers", "requires_network: test needs network access")


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests based on environment markers."""
    skip_ollama = pytest.mark.skip(reason="Ollama not running at localhost:11434")
    skip_git = pytest.mark.skip(reason="git CLI not available")

    for item in items:
        if "requires_ollama" in item.keywords and not _get_ollama_available():
            item.add_marker(skip_ollama)
        if "requires_git" in item.keywords and not _get_git_available():
            item.add_marker(skip_git)


def pytest_sessionstart(session):
    """Run pre-flight checks and print environment report."""
    if session.config.option.verbose >= 0:
        # Fixture integrity
        fixture_errors = _check_fixture_integrity()

        # Only print if there are issues or in verbose mode
        if fixture_errors or session.config.option.verbose >= 1:
            print("\n--- E2E Pre-flight Checks ---")
            print(f"  warden import : {'OK' if _get_warden_importable() else 'FAIL'}")
            print(f"  warden binary : {'OK' if _get_warden_binary() else 'MISSING (acceptance tests will skip)'}")
            print(f"  git CLI       : {'OK' if _get_git_available() else 'MISSING'}")
            print(f"  ollama        : {'OK' if _get_ollama_available() else 'UNAVAILABLE (LLM tests will skip)'}")
            print(f"  fixture files : {'OK' if not fixture_errors else 'ERRORS'}")
            for err in fixture_errors:
                print(f"    - {err}")
            print("-----------------------------\n")

        if not _get_warden_importable():
            pytest.exit("FATAL: Cannot import warden — is the package installed?", returncode=1)

        if fixture_errors:
            pytest.exit(
                f"FATAL: Fixture project integrity check failed:\n"
                + "\n".join(f"  - {e}" for e in fixture_errors),
                returncode=1,
            )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_project():
    """Path to the pre-built sample project fixture (read-only)."""
    return SAMPLE_PROJECT


@pytest.fixture
def isolated_project(tmp_path):
    """Copy sample_project to tmp_path for tests that mutate files."""
    dest = tmp_path / "project"
    shutil.copytree(SAMPLE_PROJECT, dest)
    return dest


@pytest.fixture
def ollama_available():
    """Returns True if Ollama is running. Use with requires_ollama marker."""
    return _get_ollama_available()


@pytest.fixture
def git_available():
    """Returns True if git CLI is available."""
    return _get_git_available()
