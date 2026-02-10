"""E2E test configuration and fixtures."""

from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parents[1].parent / "examples"


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end tests")


@pytest.fixture
def examples_dir():
    """Path to the examples/ directory with real test targets."""
    assert EXAMPLES_DIR.exists(), f"examples dir not found: {EXAMPLES_DIR}"
    return EXAMPLES_DIR


@pytest.fixture
def vulnerable_python_file(tmp_path):
    """Create a Python file with known vulnerabilities."""
    code = (
        'import os\n'
        'password = "hardcoded_secret_123"\n'
        'query = f"SELECT * FROM users WHERE id = {user_id}"\n'
        'eval(user_input)\n'
    )
    path = tmp_path / "insecure.py"
    path.write_text(code)
    return tmp_path


@pytest.fixture
def clean_python_file(tmp_path):
    """Create a clean Python file with no issues."""
    code = (
        'def add(a: int, b: int) -> int:\n'
        '    """Add two numbers."""\n'
        '    return a + b\n'
        '\n'
        '\n'
        'def multiply(a: int, b: int) -> int:\n'
        '    """Multiply two numbers."""\n'
        '    return a * b\n'
    )
    path = tmp_path / "clean.py"
    path.write_text(code)
    return tmp_path
