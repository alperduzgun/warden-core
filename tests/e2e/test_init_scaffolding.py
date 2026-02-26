"""Tests for init scaffolding improvements.

Covers issues #222, #223, #224, #227:
- #222: Auto-populate context.yaml (markers, commands, commit_convention)
- #223: Scaffold rules/root.yaml with per-frame orchestration
- #224: Generate AI_RULES.md with Verify-Loop protocol
- #227: Scaffold per-frame ignore.yaml sections
"""

from pathlib import Path

import pytest
import yaml

from warden.cli.commands.context import (
    _detect_commands,
    _detect_commit_convention,
    _detect_testing,
    _has_tool_config,
    read_pyproject,
)
from warden.cli.commands.init import (
    _generate_ai_rules_md,
    _generate_ignore_yaml_with_frames,
    _generate_root_rules_yaml,
)


# ============================================================================
# Issue #222: Auto-populate context.yaml
# ============================================================================
class TestContextAutoPopulate:
    """Test enhanced context detection (Issue #222)."""

    def test_detect_testing_markers_from_pyproject(self):
        """Markers should be extracted from [tool.pytest.ini_options].markers."""
        pyproject = {
            "tool": {
                "pytest": {
                    "ini_options": {
                        "markers": [
                            "slow: marks slow tests",
                            "e2e: end-to-end tests",
                            "integration: integration tests",
                        ]
                    }
                }
            }
        }
        result = _detect_testing(pyproject)
        assert result["framework"] == "pytest"
        assert "slow" in result["markers"]
        assert "e2e" in result["markers"]
        assert "integration" in result["markers"]

    def test_detect_testing_markers_strips_descriptions(self):
        """Marker names should be extracted without colon descriptions."""
        pyproject = {
            "tool": {
                "pytest": {
                    "ini_options": {
                        "markers": [
                            "slow: marks tests as slow (deselect with '-m \"not slow\"')",
                        ]
                    }
                }
            }
        }
        result = _detect_testing(pyproject)
        assert result["markers"] == ["slow"]

    def test_detect_testing_empty_markers(self):
        """Empty markers list should return empty list."""
        pyproject = {"tool": {"pytest": {"ini_options": {}}}}
        result = _detect_testing(pyproject)
        assert result["markers"] == []

    def test_detect_testing_no_pyproject(self):
        """No pyproject.toml yields default testing config."""
        result = _detect_testing({})
        assert result["framework"] == "pytest"
        assert result["markers"] == []
        assert result["naming"] == ["test_*.py"]

    def test_detect_commands_with_ruff(self, tmp_path):
        """Detect ruff as lint/format tool from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.ruff]\nline-length = 120\n", encoding="utf-8"
        )
        result = _detect_commands(tmp_path)
        assert result["lint"] == "ruff check ."
        assert result["format"] == "ruff format ."

    def test_detect_commands_with_black(self, tmp_path):
        """Detect black as formatter from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.black]\nline-length = 88\n", encoding="utf-8"
        )
        result = _detect_commands(tmp_path)
        assert result["format"] == "black ."

    def test_detect_commands_with_flake8(self, tmp_path):
        """Detect flake8 as linter from .flake8 config."""
        (tmp_path / ".flake8").write_text("[flake8]\nmax-line-length = 120\n")
        result = _detect_commands(tmp_path)
        assert result["lint"] == "flake8 ."

    def test_detect_commands_with_eslint(self, tmp_path):
        """Detect eslint for JS/TS projects."""
        (tmp_path / ".eslintrc.json").write_text('{"rules": {}}')
        result = _detect_commands(tmp_path)
        assert result["lint"] == "eslint ."

    def test_detect_commands_with_prettier(self, tmp_path):
        """Detect prettier as formatter for JS/TS projects."""
        (tmp_path / ".prettierrc").write_text("{}")
        result = _detect_commands(tmp_path)
        assert result["format"] == "prettier --write ."

    def test_detect_commands_with_npm_test(self, tmp_path):
        """Detect npm test from package.json scripts."""
        (tmp_path / "package.json").write_text(
            '{"name": "test", "scripts": {"test": "jest"}}', encoding="utf-8"
        )
        result = _detect_commands(tmp_path)
        assert result["test"] == "npm test"

    def test_detect_commands_default_fallback(self, tmp_path):
        """Default to ruff/pytest when no tool config found."""
        result = _detect_commands(tmp_path)
        assert result["lint"] == "ruff check ."
        assert result["format"] == "ruff format ."
        assert result["test"] == "pytest -q"
        assert result["scan"] == "warden scan"

    def test_detect_commit_convention_from_commitlintrc(self, tmp_path):
        """Detect conventional commits from .commitlintrc file."""
        (tmp_path / ".commitlintrc.json").write_text(
            '{"extends": ["@commitlint/config-conventional"]}',
            encoding="utf-8",
        )
        result = _detect_commit_convention(tmp_path)
        assert result == "conventional"

    def test_detect_commit_convention_from_commitlint_config(self, tmp_path):
        """Detect conventional commits from commitlint.config.js."""
        (tmp_path / "commitlint.config.js").write_text(
            "module.exports = {extends: ['@commitlint/config-conventional']};",
            encoding="utf-8",
        )
        result = _detect_commit_convention(tmp_path)
        assert result == "conventional"

    def test_detect_commit_convention_from_package_json(self, tmp_path):
        """Detect commitlint in package.json devDependencies."""
        (tmp_path / "package.json").write_text(
            '{"devDependencies": {"@commitlint/cli": "^17.0.0"}}',
            encoding="utf-8",
        )
        result = _detect_commit_convention(tmp_path)
        assert result == "conventional"

    def test_detect_commit_convention_unknown(self, tmp_path):
        """Return 'unknown' when no convention detected."""
        result = _detect_commit_convention(tmp_path)
        assert result == "unknown"

    def test_has_tool_config_ruff_pyproject(self, tmp_path):
        """Detect ruff config in pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.ruff]\nline-length = 120\n", encoding="utf-8"
        )
        assert _has_tool_config(tmp_path, "ruff") is True

    def test_has_tool_config_ruff_toml(self, tmp_path):
        """Detect ruff.toml config file."""
        (tmp_path / "ruff.toml").write_text("line-length = 120\n")
        assert _has_tool_config(tmp_path, "ruff") is True

    def test_has_tool_config_not_present(self, tmp_path):
        """Return False when tool config not found."""
        assert _has_tool_config(tmp_path, "ruff") is False


# ============================================================================
# Issue #223: Scaffold rules/root.yaml
# ============================================================================
class TestRootRulesYaml:
    """Test rules/root.yaml generation (Issue #223)."""

    def test_generates_root_yaml(self, tmp_path):
        """root.yaml is generated with project and frame_rules sections."""
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()

        class FakeMeta:
            language = "python"

        _generate_root_rules_yaml(rules_dir, FakeMeta())

        root_yaml = rules_dir / "root.yaml"
        assert root_yaml.exists()

        content = root_yaml.read_text()
        assert "project:" in content
        assert "language: python" in content
        assert "frame_rules:" in content
        assert "security:" in content
        assert "on_fail: stop" in content
        assert "orphan:" in content
        assert "architecture:" in content
        assert "resilience:" in content

    def test_root_yaml_has_pre_rules(self, tmp_path):
        """Security frame should have no-secrets pre_rule."""
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()

        class FakeMeta:
            language = "python"

        _generate_root_rules_yaml(rules_dir, FakeMeta())

        content = (rules_dir / "root.yaml").read_text()
        assert "no-secrets" in content
        assert "pre_rules:" in content

    def test_root_yaml_skips_existing(self, tmp_path):
        """Existing root.yaml should not be overwritten."""
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        root_yaml = rules_dir / "root.yaml"
        root_yaml.write_text("# custom\n")

        class FakeMeta:
            language = "python"

        _generate_root_rules_yaml(rules_dir, FakeMeta())

        assert root_yaml.read_text() == "# custom\n"

    def test_root_yaml_uses_detected_language(self, tmp_path):
        """root.yaml should use the detected language."""
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()

        class FakeMeta:
            language = "typescript"

        _generate_root_rules_yaml(rules_dir, FakeMeta())

        content = (rules_dir / "root.yaml").read_text()
        assert "language: typescript" in content

    def test_root_yaml_unknown_language(self, tmp_path):
        """root.yaml should handle unknown/empty language."""
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()

        class FakeMeta:
            language = ""

        _generate_root_rules_yaml(rules_dir, FakeMeta())

        content = (rules_dir / "root.yaml").read_text()
        assert "language: unknown" in content


# ============================================================================
# Issue #224: Generate AI_RULES.md
# ============================================================================
class TestAiRulesMd:
    """Test AI_RULES.md generation (Issue #224)."""

    def test_generates_ai_rules_md(self, tmp_path):
        """AI_RULES.md is generated with Verify-Loop protocol."""
        _generate_ai_rules_md(tmp_path)

        ai_rules = tmp_path / "AI_RULES.md"
        assert ai_rules.exists()

        content = ai_rules.read_text()
        assert "Verify-Loop" in content
        assert "PLAN" in content
        assert "EXECUTE" in content or "CODE" in content
        assert "VERIFY" in content
        assert "warden scan" in content

    def test_ai_rules_contains_commands(self, tmp_path):
        """AI_RULES.md should include warden commands."""
        _generate_ai_rules_md(tmp_path)

        content = (tmp_path / "AI_RULES.md").read_text()
        assert "warden scan" in content

    def test_ai_rules_contains_failure_recovery(self, tmp_path):
        """AI_RULES.md should include failure recovery section."""
        _generate_ai_rules_md(tmp_path)

        content = (tmp_path / "AI_RULES.md").read_text()
        assert "Failure Recovery" in content

    def test_ai_rules_skips_existing(self, tmp_path):
        """Existing AI_RULES.md should not be overwritten."""
        ai_rules = tmp_path / "AI_RULES.md"
        ai_rules.write_text("# custom rules\n")

        _generate_ai_rules_md(tmp_path)

        assert ai_rules.read_text() == "# custom rules\n"


# ============================================================================
# Issue #227: Per-frame ignore.yaml sections
# ============================================================================
class TestIgnoreYamlFrames:
    """Test per-frame ignore.yaml generation (Issue #227)."""

    def test_generates_ignore_yaml_with_frames(self, tmp_path):
        """ignore.yaml should contain frames: section."""
        _generate_ignore_yaml_with_frames(tmp_path)

        ignore_yaml = tmp_path / "ignore.yaml"
        assert ignore_yaml.exists()

        content = ignore_yaml.read_text()
        data = yaml.safe_load(content)

        assert "frames" in data
        assert "orphan" in data["frames"]
        assert "architecture" in data["frames"]

    def test_ignore_yaml_orphan_patterns(self, tmp_path):
        """Orphan frame should exclude entry-point files."""
        _generate_ignore_yaml_with_frames(tmp_path)

        data = yaml.safe_load((tmp_path / "ignore.yaml").read_text())
        orphan_patterns = data["frames"]["orphan"]

        assert "**/__main__.py" in orphan_patterns
        assert "**/cli.py" in orphan_patterns
        assert "**/main.py" in orphan_patterns

    def test_ignore_yaml_architecture_patterns(self, tmp_path):
        """Architecture frame should exclude test files."""
        _generate_ignore_yaml_with_frames(tmp_path)

        data = yaml.safe_load((tmp_path / "ignore.yaml").read_text())
        arch_patterns = data["frames"]["architecture"]

        assert "test_*.py" in arch_patterns
        assert "**/tests/**" in arch_patterns

    def test_ignore_yaml_security_patterns(self, tmp_path):
        """Security frame should exclude test files."""
        _generate_ignore_yaml_with_frames(tmp_path)

        data = yaml.safe_load((tmp_path / "ignore.yaml").read_text())
        security_patterns = data["frames"]["security"]

        assert "**/test_*.py" in security_patterns
        assert "**/tests/**" in security_patterns

    def test_ignore_yaml_preserves_base_ignores(self, tmp_path):
        """ignore.yaml should include base ignore patterns."""
        _generate_ignore_yaml_with_frames(tmp_path)

        data = yaml.safe_load((tmp_path / "ignore.yaml").read_text())

        assert "ignore" in data
        assert ".git/" in data["ignore"]

    def test_ignore_yaml_skips_existing(self, tmp_path):
        """Existing ignore.yaml should not be overwritten."""
        ignore_yaml = tmp_path / "ignore.yaml"
        ignore_yaml.write_text("# custom\n")

        _generate_ignore_yaml_with_frames(tmp_path)

        assert ignore_yaml.read_text() == "# custom\n"


# ============================================================================
# Template file tests
# ============================================================================
class TestIgnoreYamlTemplate:
    """Test that the ignore.yaml template includes frames section."""

    def test_template_has_frames_section(self):
        """The ignore.yaml template should include frames: key."""
        import importlib.resources

        template = importlib.resources.read_text("warden.templates", "ignore.yaml")
        data = yaml.safe_load(template)

        assert "frames" in data, "Template ignore.yaml should have frames: section"
        assert "orphan" in data["frames"]
        assert "architecture" in data["frames"]
        assert "security" in data["frames"]

    def test_template_orphan_has_entry_points(self):
        """Template orphan frame should list common entry points."""
        import importlib.resources

        template = importlib.resources.read_text("warden.templates", "ignore.yaml")
        data = yaml.safe_load(template)

        orphan = data["frames"]["orphan"]
        assert "**/__main__.py" in orphan
        assert "**/cli.py" in orphan
        assert "**/main.py" in orphan
