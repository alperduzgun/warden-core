"""Infrastructure E2E tests — verify registries, suppression, error handling."""

import asyncio

import pytest
import structlog


@pytest.mark.e2e
class TestProviderRegistry:

    def test_all_providers_registered(self):
        """All LLM providers auto-register via factory import."""
        from warden.llm.factory import _ensure_providers_registered
        from warden.llm.registry import ProviderRegistry

        _ensure_providers_registered()
        providers = ProviderRegistry.available()
        # 8 provider modules: anthropic, deepseek, qwencode, openai, groq, ollama, gemini, claude_code
        assert len(providers) >= 8, (
            f"Expected >=8 providers, got {len(providers)}: {providers}"
        )

    def test_registry_is_registered(self):
        """Registry correctly reports registered status."""
        from warden.llm.factory import _ensure_providers_registered
        from warden.llm.registry import ProviderRegistry
        from warden.llm.types import LlmProvider

        _ensure_providers_registered()
        assert ProviderRegistry.is_registered(LlmProvider.OPENAI) is True
        assert ProviderRegistry.is_registered(LlmProvider.OLLAMA) is True


@pytest.mark.e2e
class TestSuppressionSystem:

    def test_global_rule_suppression(self):
        """Global suppression rules work."""
        from warden.suppression.matcher import SuppressionMatcher
        from warden.suppression.models import SuppressionConfig

        config = SuppressionConfig(enabled=True, global_rules=["test-rule"])
        matcher = SuppressionMatcher(config)
        assert matcher.is_suppressed(1, "test-rule") is True
        assert matcher.is_suppressed(1, "other-rule") is False

    def test_disabled_suppression(self):
        """Disabled suppression config does not suppress anything."""
        from warden.suppression.matcher import SuppressionMatcher
        from warden.suppression.models import SuppressionConfig

        config = SuppressionConfig(enabled=False, global_rules=["test-rule"])
        matcher = SuppressionMatcher(config)
        assert matcher.is_suppressed(1, "test-rule") is False

    def test_file_ignore(self):
        """File-level ignore works."""
        from warden.suppression.models import SuppressionConfig

        config = SuppressionConfig(
            enabled=True,
            ignored_files=["vendor/*", "*.min.js"],
        )
        assert config.is_file_ignored("vendor/lib.py") is True
        assert config.is_file_ignored("src/main.py") is False


@pytest.mark.e2e
class TestErrorHandler:

    def test_fallback_value(self):
        """Error handler returns fallback on failure."""
        from warden.shared.infrastructure.error_handler import async_error_handler

        @async_error_handler(fallback_value=42, reraise=False)
        async def failing_func():
            raise RuntimeError("boom")

        result = asyncio.run(failing_func())
        assert result == 42

    def test_reraise(self):
        """Error handler re-raises when configured."""
        from warden.shared.infrastructure.error_handler import async_error_handler

        @async_error_handler(reraise=True)
        async def failing_func():
            raise ValueError("expected")

        with pytest.raises(ValueError, match="expected"):
            asyncio.run(failing_func())


@pytest.mark.e2e
class TestCorrelationIDs:

    def test_scan_id_propagation(self):
        """structlog contextvars propagate scan_id."""
        structlog.contextvars.bind_contextvars(scan_id="test-e2e-123")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("scan_id") == "test-e2e-123"
        structlog.contextvars.unbind_contextvars("scan_id")

        # Verify cleanup
        ctx = structlog.contextvars.get_contextvars()
        assert "scan_id" not in ctx


@pytest.mark.e2e
class TestFrameRegistry:

    def test_frame_registry_loads(self):
        """Frame registry discovers and registers frames."""
        from warden.validation.infrastructure.frame_registry import FrameRegistry

        registry = FrameRegistry()
        frames = registry.discover_all()
        # At minimum SecurityFrame should be present
        assert len(frames) >= 1
        frame_names = [f.name for f in frames]
        assert "Security Analysis" in frame_names
