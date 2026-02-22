"""E2E tests for LLM provider runtime switching.

Tests verify:
- Provider switching via config set
- Provider-to-model auto-mapping
- Invalid provider rejection
- Config persistence after provider change
- Fast vs smart model independence
- Config get/set for all LLM fields
"""

from pathlib import Path

import pytest
import yaml
from warden.main import app


@pytest.mark.e2e
class TestLLMProviderSwitch:
    """Test LLM provider switching via config CLI."""

    def test_config_get_llm_provider(self, runner, isolated_project, monkeypatch):
        """Get current LLM provider."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "get", "llm.provider"], catch_exceptions=False)
        assert result.exit_code == 0
        # Should show current provider (ollama in fixture)
        assert "ollama" in result.stdout.lower()

    def test_config_set_llm_provider_ollama(self, runner, isolated_project, monkeypatch):
        """Switch provider to ollama."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.provider", "ollama"], catch_exceptions=False)
        assert result.exit_code == 0

        # Verify config file was updated
        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["provider"] == "ollama"

        # Verify output message
        assert "ollama" in result.stdout.lower()

    def test_config_set_llm_provider_groq(self, runner, isolated_project, monkeypatch):
        """Switch provider to groq."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.provider", "groq"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["provider"] == "groq"

        # Verify model was auto-updated to groq default
        assert config["llm"]["model"] == "llama-3.3-70b-versatile"

    def test_config_set_llm_provider_openai(self, runner, isolated_project, monkeypatch):
        """Switch provider to openai."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.provider", "openai"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["provider"] == "openai"

        # Verify model was auto-updated to openai default
        assert config["llm"]["model"] == "gpt-4o"

    def test_config_set_llm_provider_anthropic(self, runner, isolated_project, monkeypatch):
        """Switch provider to anthropic."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.provider", "anthropic"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["provider"] == "anthropic"

        # Verify model was auto-updated to anthropic default
        assert config["llm"]["model"] == "claude-3-5-sonnet-20241022"

    def test_config_set_llm_provider_deepseek(self, runner, isolated_project, monkeypatch):
        """Switch provider to deepseek."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.provider", "deepseek"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["provider"] == "deepseek"

        # Verify model was auto-updated to deepseek default
        assert config["llm"]["model"] == "deepseek-coder"

    def test_config_set_llm_provider_qwencode(self, runner, isolated_project, monkeypatch):
        """Switch provider to qwencode."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.provider", "qwencode"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["provider"] == "qwencode"

    def test_config_set_llm_provider_azure_openai(self, runner, isolated_project, monkeypatch):
        """Switch provider to azure_openai."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.provider", "azure_openai"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["provider"] == "azure_openai"

    def test_config_set_llm_provider_openrouter(self, runner, isolated_project, monkeypatch):
        """Switch provider to openrouter."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.provider", "openrouter"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["provider"] == "openrouter"

    def test_config_set_llm_provider_gemini(self, runner, isolated_project, monkeypatch):
        """Switch provider to gemini."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.provider", "gemini"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["provider"] == "gemini"

    def test_config_set_llm_provider_claude_code(self, runner, isolated_project, monkeypatch):
        """Switch provider to claude_code."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.provider", "claude_code"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["provider"] == "claude_code"

    def test_config_set_invalid_provider_rejected(self, runner, isolated_project, monkeypatch):
        """Invalid provider name is rejected."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.provider", "nonexistent_provider"], catch_exceptions=False)

        # Should fail with clear error message
        assert result.exit_code == 1
        assert "invalid" in result.stdout.lower() or "valid providers" in result.stdout.lower()

    def test_config_set_llm_model(self, runner, isolated_project, monkeypatch):
        """Set LLM model directly."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.model", "gpt-4o"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["model"] == "gpt-4o"

    def test_config_set_fast_model(self, runner, isolated_project, monkeypatch):
        """Set fast model independently."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.fast_model", "qwen2.5-coder:0.5b"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["fast_model"] == "qwen2.5-coder:0.5b"

    def test_config_set_smart_model(self, runner, isolated_project, monkeypatch):
        """Set smart model independently."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.smart_model", "claude-sonnet-4-20250514"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["smart_model"] == "claude-sonnet-4-20250514"

    def test_fast_smart_model_independence(self, runner, isolated_project, monkeypatch):
        """Setting fast model doesn't affect smart model and vice versa."""
        monkeypatch.chdir(isolated_project)

        # Set both models
        runner.invoke(app, ["config", "set", "llm.fast_model", "small-model"], catch_exceptions=False)
        runner.invoke(app, ["config", "set", "llm.smart_model", "big-model"], catch_exceptions=False)

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["fast_model"] == "small-model"
        assert config["llm"]["smart_model"] == "big-model"

        # Change fast model, smart should remain unchanged
        runner.invoke(app, ["config", "set", "llm.fast_model", "another-small-model"], catch_exceptions=False)
        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["fast_model"] == "another-small-model"
        assert config["llm"]["smart_model"] == "big-model"

    def test_config_set_llm_timeout(self, runner, isolated_project, monkeypatch):
        """Set LLM timeout."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.timeout", "60"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["timeout"] == 60  # Should be integer

    def test_config_set_llm_max_tokens(self, runner, isolated_project, monkeypatch):
        """Set LLM max_tokens."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.max_tokens", "8000"], catch_exceptions=False)
        assert result.exit_code == 0

        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["max_tokens"] == 8000  # Should be integer

    def test_provider_persists_across_reads(self, runner, isolated_project, monkeypatch):
        """Provider change persists in config file and can be read back."""
        monkeypatch.chdir(isolated_project)

        # Set provider
        runner.invoke(app, ["config", "set", "llm.provider", "groq"], catch_exceptions=False)

        # Read it back via config get
        result = runner.invoke(app, ["config", "get", "llm.provider"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "groq" in result.stdout.lower()

        # Verify file persistence
        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
        assert config["llm"]["provider"] == "groq"

    def test_provider_change_updates_smart_model(self, runner, isolated_project, monkeypatch):
        """Changing provider auto-updates smart_model to provider's default."""
        monkeypatch.chdir(isolated_project)

        # Switch to OpenAI
        runner.invoke(app, ["config", "set", "llm.provider", "openai"], catch_exceptions=False)
        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())

        # smart_model should be updated to OpenAI's default
        assert config["llm"]["smart_model"] == "gpt-4o"

        # Switch to Anthropic
        runner.invoke(app, ["config", "set", "llm.provider", "anthropic"], catch_exceptions=False)
        config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())

        # smart_model should be updated to Anthropic's default
        assert config["llm"]["smart_model"] == "claude-3-5-sonnet-20241022"

    def test_provider_change_shows_helpful_hints(self, runner, isolated_project, monkeypatch):
        """Provider change shows helpful setup hints."""
        monkeypatch.chdir(isolated_project)

        # OpenAI shows API key hint
        result = runner.invoke(app, ["config", "set", "llm.provider", "openai"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "OPENAI_API_KEY" in result.stdout or "api key" in result.stdout.lower()

        # Ollama shows local server hint
        result = runner.invoke(app, ["config", "set", "llm.provider", "ollama"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "ollama serve" in result.stdout.lower() or "running" in result.stdout.lower()

    def test_config_get_nonexistent_key(self, runner, isolated_project, monkeypatch):
        """Getting non-existent config key fails gracefully."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "get", "llm.nonexistent_field"], catch_exceptions=False)
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()

    def test_config_set_invalid_timeout(self, runner, isolated_project, monkeypatch):
        """Setting non-integer timeout is rejected."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "set", "llm.timeout", "not-a-number"], catch_exceptions=False)
        assert result.exit_code == 1
        assert "invalid" in result.stdout.lower()

    def test_multiple_provider_switches(self, runner, isolated_project, monkeypatch):
        """Multiple provider switches in sequence work correctly."""
        monkeypatch.chdir(isolated_project)

        providers = ["groq", "openai", "anthropic", "ollama", "deepseek"]

        for provider in providers:
            result = runner.invoke(app, ["config", "set", "llm.provider", provider], catch_exceptions=False)
            assert result.exit_code == 0

            config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())
            assert config["llm"]["provider"] == provider

    def test_config_get_entire_llm_section(self, runner, isolated_project, monkeypatch):
        """Get entire LLM config section shows all fields."""
        monkeypatch.chdir(isolated_project)
        result = runner.invoke(app, ["config", "get", "llm"], catch_exceptions=False)
        assert result.exit_code == 0

        # Should show key LLM fields
        assert "provider" in result.stdout.lower() or "ollama" in result.stdout.lower()

    def test_provider_model_default_mapping(self, runner, isolated_project, monkeypatch):
        """Verify all providers get their correct default models."""
        monkeypatch.chdir(isolated_project)

        # Map of provider -> expected default model
        provider_defaults = {
            "deepseek": "deepseek-coder",
            "qwencode": "qwen2.5-coder-32b-instruct",
            "anthropic": "claude-3-5-sonnet-20241022",
            "openai": "gpt-4o",
            "groq": "llama-3.3-70b-versatile",
            "ollama": "qwen2.5-coder:0.5b",
        }

        for provider, expected_model in provider_defaults.items():
            runner.invoke(app, ["config", "set", "llm.provider", provider], catch_exceptions=False)
            config = yaml.safe_load((isolated_project / ".warden/config.yaml").read_text())

            assert config["llm"]["model"] == expected_model, (
                f"Provider {provider} should default to {expected_model}, "
                f"got {config['llm']['model']}"
            )
