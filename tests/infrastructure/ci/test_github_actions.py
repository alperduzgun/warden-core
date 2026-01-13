"""
Tests for GitHub Actions template generator.
"""

import pytest
from pathlib import Path
import tempfile
import yaml

from warden.infrastructure.ci.github_actions import (
    GitHubActionsTemplate,
    GitHubActionsConfig,
)


class TestGitHubActionsConfig:
    """Test GitHubActionsConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = GitHubActionsConfig()

        assert config.workflow_name == "Warden Analysis"
        assert config.trigger_events == ["pull_request", "push"]
        assert config.python_version == "3.11"
        assert config.warden_version is None
        assert config.fail_on_issues is True
        assert config.upload_artifacts is True
        assert config.frames == ["security", "fuzz", "property"]

    def test_custom_config(self):
        """Test custom configuration."""
        config = GitHubActionsConfig(
            workflow_name="Custom Warden",
            python_version="3.10",
            warden_version="1.0.0",
            fail_on_issues=False,
            frames=["security"],
        )

        assert config.workflow_name == "Custom Warden"
        assert config.python_version == "3.10"
        assert config.warden_version == "1.0.0"
        assert config.fail_on_issues is False
        assert config.frames == ["security"]


class TestGitHubActionsTemplate:
    """Test GitHubActionsTemplate generator."""

    def test_generate_basic_template(self):
        """Test generating basic workflow template."""
        config = GitHubActionsConfig()
        template = GitHubActionsTemplate.generate(config)

        assert "name: Warden Analysis" in template
        assert "actions/checkout@v4" in template
        assert "actions/setup-python@v5" in template
        assert "python-version: '3.11'" in template
        assert "pip install warden-core" in template
        assert "warden analyze" in template

    def test_generate_with_version(self):
        """Test template with specific Warden version."""
        config = GitHubActionsConfig(warden_version="1.0.0")
        template = GitHubActionsTemplate.generate(config)

        assert "pip install warden-core==1.0.0" in template

    def test_generate_with_frames(self):
        """Test template with specific validation frames."""
        config = GitHubActionsConfig(frames=["security", "chaos"])
        template = GitHubActionsTemplate.generate(config)

        assert "--frame security --frame chaos" in template

    def test_generate_with_fail_on_issues(self):
        """Test template with fail_on_issues flag."""
        config = GitHubActionsConfig(fail_on_issues=True)
        template = GitHubActionsTemplate.generate(config)

        assert "--fail-on-issues" in template

    def test_generate_without_fail_on_issues(self):
        """Test template without fail_on_issues flag."""
        config = GitHubActionsConfig(fail_on_issues=False)
        template = GitHubActionsTemplate.generate(config)

        assert "--fail-on-issues" not in template

    def test_generate_triggers_single(self):
        """Test trigger generation with single event."""
        config = GitHubActionsConfig(trigger_events=["pull_request"])
        template = GitHubActionsTemplate.generate(config)

        assert "'on': [pull_request]" in template

    def test_generate_triggers_multiple(self):
        """Test trigger generation with multiple events."""
        config = GitHubActionsConfig(trigger_events=["pull_request", "push"])
        template = GitHubActionsTemplate.generate(config)

        assert "'on':" in template
        assert "pull_request:" in template
        assert "push:" in template

    def test_save_to_file(self):
        """Test saving workflow to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "workflow.yml"
            config = GitHubActionsConfig()

            GitHubActionsTemplate.save_to_file(config, output_path)

            assert output_path.exists()
            content = output_path.read_text()
            assert "name: Warden Analysis" in content

    def test_validate_valid_workflow(self):
        """Test validating a valid workflow file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow_path = Path(tmpdir) / "workflow.yml"
            config = GitHubActionsConfig()

            GitHubActionsTemplate.save_to_file(config, workflow_path)
            is_valid = GitHubActionsTemplate.validate_workflow(workflow_path)

            assert is_valid is True

    def test_validate_invalid_workflow(self):
        """Test validating an invalid workflow file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow_path = Path(tmpdir) / "invalid.yml"
            workflow_path.write_text("invalid: yaml: content:")

            is_valid = GitHubActionsTemplate.validate_workflow(workflow_path)

            assert is_valid is False

    def test_validate_missing_required_keys(self):
        """Test validation fails for missing required keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow_path = Path(tmpdir) / "incomplete.yml"
            workflow_path.write_text("name: Test\n")

            is_valid = GitHubActionsTemplate.validate_workflow(workflow_path)

            assert is_valid is False

    def test_validate_nonexistent_file(self):
        """Test validation fails for non-existent file."""
        is_valid = GitHubActionsTemplate.validate_workflow(Path("/nonexistent.yml"))

        assert is_valid is False


def test_workflow_yaml_structure():
    """Test that generated workflow is valid YAML."""
    config = GitHubActionsConfig()
    template = GitHubActionsTemplate.generate(config)

    # Should parse as valid YAML
    data = yaml.safe_load(template)

    assert isinstance(data, dict)
    assert "name" in data
    assert "on" in data
    assert "jobs" in data
