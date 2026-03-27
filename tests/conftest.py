"""Shared test fixtures for Warden Core test suite."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Auto-marker: classify every test into unit / integration / llm
#
# Priority (first match wins):
#   1. Explicitly decorated with @pytest.mark.{unit,integration,llm} → keep
#   2. Path contains an integration directory → integration
#   3. Filename contains _live → llm + integration
#   4. Filename contains _integration → integration
#   5. Everything else → unit
# ---------------------------------------------------------------------------

_INTEGRATION_PATH_SEGMENTS = {
    "/e2e/", "/integration/", "/chaos/", "/benchmark/",
    "/grpc/", "/llm/",
}


def pytest_collection_modifyitems(config, items: list) -> None:
    # Determine whether the user explicitly requested llm tests.
    # markexpr is the raw -m expression passed on the CLI (empty when not given).
    markexpr: str = getattr(config.option, "markexpr", "") or ""
    llm_explicitly_requested = "llm" in markexpr

    skip_llm = pytest.mark.skip(
        reason="llm tests skipped by default (require Ollama/cloud keys) — run: pytest -m llm"
    )

    for item in items:
        existing = {m.name for m in item.iter_markers()}

        # Step 1 — assign tier marker if not already present
        if not (existing & {"unit", "integration", "llm"}):
            path = str(item.fspath).replace("\\", "/")
            stem = Path(item.fspath).stem

            if any(seg in path for seg in _INTEGRATION_PATH_SEGMENTS):
                item.add_marker(pytest.mark.integration)
            elif stem.endswith("_live"):
                item.add_marker(pytest.mark.llm)
                item.add_marker(pytest.mark.integration)
            elif stem.endswith("_integration"):
                item.add_marker(pytest.mark.integration)
            else:
                item.add_marker(pytest.mark.unit)

        # Step 2 — auto-skip llm tests unless explicitly requested
        if not llm_explicitly_requested:
            updated = {m.name for m in item.iter_markers()}
            if "llm" in updated:
                item.add_marker(skip_llm)


@pytest.fixture
def project_root(tmp_path):
    """Create a temporary project root directory."""
    return tmp_path


@pytest.fixture
def sample_python_file(tmp_path):
    """Create a sample Python file for testing."""
    code = '''
def hello():
    """Say hello."""
    return "Hello, World!"

class Calculator:
    def add(self, a, b):
        return a + b

    def divide(self, a, b):
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b
'''
    file_path = tmp_path / "sample.py"
    file_path.write_text(code)
    return file_path


@pytest.fixture
def sample_code_file(sample_python_file):
    """Create a CodeFile instance for testing."""
    from warden.validation.domain.frame import CodeFile

    return CodeFile(
        path=str(sample_python_file),
        content=sample_python_file.read_text(),
        language="python",
    )


@pytest.fixture
def mock_llm_service():
    """Create a mock LLM service."""
    service = AsyncMock()
    service.send_async = AsyncMock(return_value={
        "content": "No issues found.",
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    })
    service.is_available_async = AsyncMock(return_value=True)
    service.complete_async = AsyncMock(return_value="Analysis complete.")
    service.provider = "mock"
    return service


@pytest.fixture
def pipeline_config():
    """Create a default PipelineConfig for testing."""
    from warden.pipeline.domain.models import PipelineConfig

    return PipelineConfig(
        timeout=60,
        enable_validation=True,
        enable_fortification=False,
        enable_cleaning=False,
    )


@pytest.fixture
def temp_warden_dir(tmp_path):
    """Create a temporary .warden directory structure."""
    warden_dir = tmp_path / ".warden"
    warden_dir.mkdir()
    (warden_dir / "baseline").mkdir()
    (warden_dir / "rules").mkdir()
    (warden_dir / "frames").mkdir()
    return warden_dir
