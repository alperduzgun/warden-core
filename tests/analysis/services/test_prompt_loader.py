"""
Tests for PromptLoader (Issue #649 — Externalize LLM prompts).

Covers:
  - Default prompt loading from package prompts directory
  - Project-level override from .warden/prompts/
  - Variable interpolation ({{VAR}} placeholders)
  - FileNotFoundError for unknown prompt names
  - Cache behaviour and invalidation
  - has_override() detection
  - PromptLoader.load() integration with FindingVerificationService
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from warden.analysis.services.prompt_loader import PromptLoader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project structure with a .warden directory."""
    (tmp_path / ".warden").mkdir()
    return tmp_path


@pytest.fixture()
def tmp_prompts_dir(tmp_path: Path) -> Path:
    """Return a temporary directory acting as the package default prompts dir."""
    d = tmp_path / "prompts"
    d.mkdir()
    return d


@pytest.fixture()
def loader_with_defaults(tmp_path: Path, tmp_prompts_dir: Path) -> PromptLoader:
    """PromptLoader with a known default_prompts_dir but no project root."""
    return PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)


# ---------------------------------------------------------------------------
# Default prompt loading
# ---------------------------------------------------------------------------


class TestDefaultPromptLoading:
    def test_loads_from_default_dir(self, tmp_prompts_dir: Path) -> None:
        (tmp_prompts_dir / "test_prompt.md").write_text("Hello default", encoding="utf-8")
        loader = PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)
        assert loader.load("test_prompt") == "Hello default"

    def test_raises_file_not_found_for_missing_prompt(self, tmp_prompts_dir: Path) -> None:
        loader = PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)
        with pytest.raises(FileNotFoundError, match="missing_prompt"):
            loader.load("missing_prompt")

    def test_loads_real_verifier_system_prompt(self) -> None:
        """Smoke test: the package default verifier_system.md must exist and be non-empty."""
        loader = PromptLoader(project_root=None)
        content = loader.load("verifier_system")
        assert "Senior Code Auditor" in content
        assert "is_true_positive" in content

    def test_loads_real_verifier_batch_prompt(self) -> None:
        """Smoke test: the package default verifier_batch.md must contain placeholders."""
        loader = PromptLoader(project_root=None)
        content = loader.load("verifier_batch", batch_size="3", context_prompt="ctx", findings_summary="fs")
        assert "3" in content  # batch_size substituted


# ---------------------------------------------------------------------------
# Project-level override
# ---------------------------------------------------------------------------


class TestProjectOverride:
    def test_override_takes_precedence_over_default(
        self, tmp_project: Path, tmp_prompts_dir: Path
    ) -> None:
        # Write a default prompt
        (tmp_prompts_dir / "my_prompt.md").write_text("default content", encoding="utf-8")
        # Write a project override
        override_dir = tmp_project / ".warden" / "prompts"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "my_prompt.md").write_text("override content", encoding="utf-8")

        loader = PromptLoader(project_root=tmp_project, default_prompts_dir=tmp_prompts_dir)
        assert loader.load("my_prompt") == "override content"

    def test_falls_back_to_default_when_no_override(
        self, tmp_project: Path, tmp_prompts_dir: Path
    ) -> None:
        (tmp_prompts_dir / "my_prompt.md").write_text("default content", encoding="utf-8")
        loader = PromptLoader(project_root=tmp_project, default_prompts_dir=tmp_prompts_dir)
        # No override file written — should use default
        assert loader.load("my_prompt") == "default content"

    def test_has_override_returns_true_when_file_exists(
        self, tmp_project: Path, tmp_prompts_dir: Path
    ) -> None:
        override_dir = tmp_project / ".warden" / "prompts"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "my_prompt.md").write_text("override", encoding="utf-8")

        loader = PromptLoader(project_root=tmp_project, default_prompts_dir=tmp_prompts_dir)
        assert loader.has_override("my_prompt") is True

    def test_has_override_returns_false_when_no_file(
        self, tmp_project: Path, tmp_prompts_dir: Path
    ) -> None:
        loader = PromptLoader(project_root=tmp_project, default_prompts_dir=tmp_prompts_dir)
        assert loader.has_override("my_prompt") is False

    def test_has_override_returns_false_when_no_project_root(
        self, tmp_prompts_dir: Path
    ) -> None:
        loader = PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)
        assert loader.has_override("any_prompt") is False


# ---------------------------------------------------------------------------
# Variable interpolation
# ---------------------------------------------------------------------------


class TestVariableInterpolation:
    def test_substitutes_known_variables(self, tmp_prompts_dir: Path) -> None:
        (tmp_prompts_dir / "greet.md").write_text("Hello {{name}}!", encoding="utf-8")
        loader = PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)
        assert loader.load("greet", name="World") == "Hello World!"

    def test_leaves_unknown_placeholders_intact(self, tmp_prompts_dir: Path) -> None:
        (tmp_prompts_dir / "partial.md").write_text("A={{a}} B={{b}}", encoding="utf-8")
        loader = PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)
        result = loader.load("partial", a="1")
        assert result == "A=1 B={{b}}"

    def test_no_variables_leaves_template_unchanged(self, tmp_prompts_dir: Path) -> None:
        (tmp_prompts_dir / "static.md").write_text("No placeholders here.", encoding="utf-8")
        loader = PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)
        assert loader.load("static") == "No placeholders here."

    def test_multiple_variables_substituted(self, tmp_prompts_dir: Path) -> None:
        (tmp_prompts_dir / "multi.md").write_text("{{x}} and {{y}}", encoding="utf-8")
        loader = PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)
        assert loader.load("multi", x="foo", y="bar") == "foo and bar"


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestCaching:
    def test_cache_returns_same_content_on_second_call(self, tmp_prompts_dir: Path) -> None:
        prompt_file = tmp_prompts_dir / "cached.md"
        prompt_file.write_text("original", encoding="utf-8")
        loader = PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)

        first = loader.load("cached")
        # Mutate file after first load — cache should still return original
        prompt_file.write_text("modified", encoding="utf-8")
        second = loader.load("cached")

        assert first == second == "original"

    def test_invalidate_cache_forces_reload(self, tmp_prompts_dir: Path) -> None:
        prompt_file = tmp_prompts_dir / "cached2.md"
        prompt_file.write_text("original", encoding="utf-8")
        loader = PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)

        loader.load("cached2")  # prime cache
        prompt_file.write_text("updated", encoding="utf-8")
        loader.invalidate_cache()

        assert loader.load("cached2") == "updated"


# ---------------------------------------------------------------------------
# _find_project_root
# ---------------------------------------------------------------------------


class TestSafety:
    def test_rejects_invalid_prompt_name(self, tmp_prompts_dir: Path) -> None:
        loader = PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)
        with pytest.raises(ValueError, match="Invalid prompt name"):
            loader.load("../etc/passwd")

    def test_rejects_prompt_name_with_path_separator(self, tmp_prompts_dir: Path) -> None:
        loader = PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)
        with pytest.raises(ValueError, match="Invalid prompt name"):
            loader.load("sub/dir")

    def test_rejects_prompt_name_with_null_byte(self, tmp_prompts_dir: Path) -> None:
        loader = PromptLoader(project_root=None, default_prompts_dir=tmp_prompts_dir)
        with pytest.raises(ValueError, match="Invalid prompt name"):
            loader.load("name\x00evil")


class TestFindProjectRoot:
    def test_finds_warden_dir_in_cwd(self, tmp_path: Path) -> None:
        (tmp_path / ".warden").mkdir()
        with patch("warden.analysis.services.prompt_loader.Path.cwd", return_value=tmp_path):
            root = PromptLoader._find_project_root()
        assert root == tmp_path.resolve()

    def test_finds_warden_dir_in_parent(self, tmp_path: Path) -> None:
        (tmp_path / ".warden").mkdir()
        subdir = tmp_path / "deep" / "nested"
        subdir.mkdir(parents=True)
        with patch("warden.analysis.services.prompt_loader.Path.cwd", return_value=subdir):
            root = PromptLoader._find_project_root()
        assert root == tmp_path.resolve()

    def test_returns_none_when_no_warden_dir(self, tmp_path: Path) -> None:
        subdir = tmp_path / "project" / "src"
        subdir.mkdir(parents=True)

        original_is_dir = Path.is_dir

        def is_dir_without_warden(self: Path) -> bool:
            if self.name == ".warden":
                return False
            return original_is_dir(self)

        with (
            patch("warden.analysis.services.prompt_loader.Path.cwd", return_value=subdir),
            patch.object(Path, "is_dir", autospec=True, side_effect=is_dir_without_warden),
        ):
            root = PromptLoader._find_project_root()

        assert root is None


# ---------------------------------------------------------------------------
# Integration: FindingVerificationService uses PromptLoader
# ---------------------------------------------------------------------------


class TestFindingVerifierIntegration:
    """Verify that FindingVerificationService loads its system prompt via PromptLoader."""

    def test_service_uses_prompt_loader_system_prompt(self, tmp_prompts_dir: Path) -> None:
        from unittest.mock import MagicMock

        from warden.analysis.services.finding_verifier import FindingVerificationService

        llm_client = MagicMock()
        svc = FindingVerificationService(llm_client=llm_client)
        # The system prompt must contain the canonical marker from verifier_system.md
        assert "Senior Code Auditor" in svc.system_prompt

    def test_service_uses_override_when_provided(
        self, tmp_project: Path, tmp_prompts_dir: Path
    ) -> None:
        from unittest.mock import MagicMock

        from warden.analysis.services.finding_verifier import FindingVerificationService

        # Write a custom override
        override_dir = tmp_project / ".warden" / "prompts"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "verifier_system.md").write_text(
            "CUSTOM SYSTEM PROMPT FOR TESTING", encoding="utf-8"
        )

        llm_client = MagicMock()
        svc = FindingVerificationService(llm_client=llm_client, project_root=tmp_project)
        assert svc.system_prompt == "CUSTOM SYSTEM PROMPT FOR TESTING"
