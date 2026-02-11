"""E2E test configuration and fixtures."""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_PROJECT = FIXTURES_DIR / "sample_project"


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end tests")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_project():
    """Path to the pre-built sample project fixture."""
    assert SAMPLE_PROJECT.exists(), f"Fixture not found: {SAMPLE_PROJECT}"
    return SAMPLE_PROJECT


@pytest.fixture
def isolated_project(tmp_path):
    """Copy sample_project to tmp_path for tests that mutate files."""
    dest = tmp_path / "project"
    shutil.copytree(SAMPLE_PROJECT, dest)
    return dest
