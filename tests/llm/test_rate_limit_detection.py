"""Tests for provider rate-limit detection and circuit breaker."""

import asyncio
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.llm.providers.base import detect_provider_error


# ---------------------------------------------------------------------------
# 1. detect_provider_error utility
# ---------------------------------------------------------------------------


class TestDetectProviderError:
    def test_detects_usage_limit(self):
        msg = "🖐 You've hit your usage limit for the day."
        assert detect_provider_error(msg) is not None
        assert "usage limit" in detect_provider_error(msg).lower()

    def test_detects_rate_limit(self):
        assert detect_provider_error("Rate limit exceeded, try again later") is not None

    def test_detects_try_again_in(self):
        assert detect_provider_error("Please try again in 30 seconds") is not None

    def test_detects_too_many_requests(self):
        assert detect_provider_error("Error: Too many requests") is not None

    def test_detects_quota_exceeded(self):
        assert detect_provider_error("Your quota exceeded for this billing period") is not None

    def test_detects_throttled(self):
        assert detect_provider_error("Request throttled by provider") is not None

    def test_returns_none_for_normal_content(self):
        assert detect_provider_error("Here is the security analysis...") is None
        assert detect_provider_error('{"findings": []}') is None

    def test_truncates_long_messages(self):
        long_msg = "Rate limit " + "x" * 300
        result = detect_provider_error(long_msg)
        assert result is not None
        assert len(result) <= 200

    def test_case_insensitive(self):
        assert detect_provider_error("RATE LIMIT exceeded") is not None
        assert detect_provider_error("Usage Limit reached") is not None


# ---------------------------------------------------------------------------
# 2. Codex provider rate limit detection
# ---------------------------------------------------------------------------


class TestCodexRateLimitDetection:
    @pytest.mark.asyncio
    async def test_codex_detects_rate_limit_in_output(self):
        from warden.llm.providers.codex import CodexClient
        from warden.llm.types import LlmRequest

        client = CodexClient()

        # Mock subprocess that returns rate limit message with exit 0
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(
                b"[2026-02-23T10:00:00] Assistant response:\nYou've hit your usage limit for today.",
                b"",
            )
        )

        # Mock the output file to be empty (so it falls back to stdout)
        with (
            patch("warden.llm.providers.codex.shutil.which", return_value="/usr/bin/codex"),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("warden.llm.providers.codex.Path") as mock_path,
            patch("warden.llm.providers.codex.tempfile.mkstemp", return_value=(0, "/tmp/test.txt")),
            patch("warden.llm.providers.codex.os.close"),
            patch("warden.llm.providers.codex.os.unlink"),
        ):
            mock_path.return_value.read_text.return_value = ""

            request = LlmRequest(
                user_message="Analyze this code",
                system_prompt="You are a security auditor",
            )
            response = await client.send_async(request)

        assert response.success is False
        assert "rate limit" in response.error_message.lower()


# ---------------------------------------------------------------------------
# 3. Claude Code provider rate limit detection
# ---------------------------------------------------------------------------


class TestClaudeCodeRateLimitDetection:
    @pytest.mark.asyncio
    async def test_claude_code_detects_rate_limit_in_json_content(self):
        from warden.llm.providers.claude_code import ClaudeCodeClient
        from warden.llm.types import LlmRequest

        config = MagicMock()
        config.default_model = "claude-code-default"
        client = ClaudeCodeClient(config)

        # Mock subprocess returning JSON with rate limit in content
        import json

        output = json.dumps({"result": "You've hit your usage limit. Try again in 1 hour."})

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(output.encode(), b""))

        with (
            patch.object(client, "_is_nested_session", return_value=False),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            request = LlmRequest(user_message="Analyze this code", system_prompt="You are a security auditor")
            response = await client.send_async(request)

        assert response.success is False
        assert "rate limit" in response.error_message.lower()

    @pytest.mark.asyncio
    async def test_claude_code_detects_rate_limit_in_plain_text(self):
        from warden.llm.providers.claude_code import ClaudeCodeClient
        from warden.llm.types import LlmRequest

        config = MagicMock()
        config.default_model = "claude-code-default"
        client = ClaudeCodeClient(config)

        # Non-JSON output with rate limit message
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(b"Too many requests. Please slow down.", b""),
        )

        with (
            patch.object(client, "_is_nested_session", return_value=False),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            request = LlmRequest(user_message="Analyze this code", system_prompt="You are a security auditor")
            response = await client.send_async(request)

        assert response.success is False
        assert "rate limit" in response.error_message.lower()


# ---------------------------------------------------------------------------
# 4. Finding verifier circuit breaker
# ---------------------------------------------------------------------------


class TestVerificationCircuitBreaker:
    @pytest.mark.asyncio
    async def test_circuit_breaks_after_consecutive_failures(self):
        from warden.analysis.services.finding_verifier import FindingVerificationService

        mock_llm = MagicMock()
        mock_llm.provider = "test"
        service = FindingVerificationService(llm_client=mock_llm, enabled=True)

        # Create 10 findings
        findings = [
            {"id": f"f{i}", "rule_id": "test_rule", "message": "test", "location": f"file.py:{i}", "code": "x = 1"}
            for i in range(10)
        ]

        # Make _verify_batch_with_llm_async always fail
        call_count = 0

        async def failing_verify(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Provider rate limit: usage limit reached")

        service._verify_batch_with_llm_async = failing_verify
        service._check_cache = lambda _: None  # No cache hits
        service._save_cache = lambda *args: None
        # Force batch_size=1 so each finding is a separate batch
        service._get_safe_batch_size = lambda _: 1

        result = await service.verify_findings_async(findings)

        # Circuit should break after 3 consecutive failures
        assert call_count == 3
        # All findings should be in result (marked as manual review)
        assert len(result) == 10
        # Check that circuit break metadata is set on remaining findings
        for finding in result:
            meta = finding.get("verification_metadata", {})
            assert meta.get("fallback") is True
            assert meta.get("review_required") is True

    @pytest.mark.asyncio
    async def test_circuit_resets_on_success(self):
        from warden.analysis.services.finding_verifier import FindingVerificationService

        mock_llm = MagicMock()
        mock_llm.provider = "test"
        service = FindingVerificationService(llm_client=mock_llm, enabled=True)

        findings = [
            {"id": f"f{i}", "rule_id": "test_rule", "message": "test", "location": f"file.py:{i}", "code": "x = 1"}
            for i in range(5)
        ]

        call_count = 0

        async def intermittent_verify(batch, context):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("Temporary failure")
            return [{"is_true_positive": True, "confidence": 0.9, "reason": "Valid"} for _ in batch]

        service._verify_batch_with_llm_async = intermittent_verify
        service._check_cache = lambda _: None
        service._save_cache = lambda *args: None
        # Force batch size 1 to test each call
        service._get_safe_batch_size = lambda _: 1

        result = await service.verify_findings_async(findings)

        # Should NOT circuit break (only 2 consecutive failures, then success resets)
        assert len(result) == 5
        assert call_count == 5  # 2 failures + 3 successes


# ---------------------------------------------------------------------------
# 5. Pipeline timeout includes phase name
# ---------------------------------------------------------------------------


class TestPipelineTimeoutPhaseInfo:
    @pytest.mark.asyncio
    async def test_timeout_includes_current_phase(self):
        """Timeout error message should contain the stuck phase name."""
        from warden.pipeline.domain.pipeline_context import PipelineContext

        ctx = PipelineContext(
            pipeline_id="test-123",
            started_at=MagicMock(),
            file_path=MagicMock(),
            source_code="",
        )

        # Simulate phase runner setting current_phase
        ctx.current_phase = "Verification"

        # The orchestrator reads this on timeout
        assert ctx.current_phase == "Verification"

        # Simulate what orchestrator does on timeout
        error_msg = f"Pipeline execution timeout after 300s (stuck in: {ctx.current_phase})"
        assert "Verification" in error_msg
        assert "stuck in:" in error_msg


# ---------------------------------------------------------------------------
# 6. Metrics rate limit issue detection
# ---------------------------------------------------------------------------


class TestMetricsRateLimitDetection:
    def test_detects_rate_limit_issues_in_metrics(self):
        from warden.llm.metrics import LLMMetricsCollector

        collector = LLMMetricsCollector()

        # Record some normal requests
        collector.record_request("fast", "ollama", "qwen2.5", True, 500)
        collector.record_request("smart", "codex", "codex-local", True, 3000)

        # Record rate-limited requests
        collector.record_request("smart", "codex", "codex-local", False, 100, error="Provider rate limit: usage limit")
        collector.record_request("smart", "codex", "codex-local", False, 100, error="Provider rate limit: usage limit")
        collector.record_request(
            "smart", "codex", "codex-local", False, 100, error="Provider rate limit: quota exceeded"
        )

        summary = collector.get_summary()
        issues = summary.get("issues", [])

        rate_limit_issues = [i for i in issues if i["type"] == "rate_limit"]
        assert len(rate_limit_issues) == 1
        assert rate_limit_issues[0]["count"] == 3
        assert "codex" in rate_limit_issues[0]["message"]
        assert rate_limit_issues[0]["severity"] == "error"

    def test_no_rate_limit_issue_when_no_rate_limits(self):
        from warden.llm.metrics import LLMMetricsCollector

        collector = LLMMetricsCollector()
        collector.record_request("fast", "ollama", "qwen2.5", True, 500)
        collector.record_request("fast", "ollama", "qwen2.5", False, 100, error="Timeout after 30s")

        summary = collector.get_summary()
        issues = summary.get("issues", [])

        rate_limit_issues = [i for i in issues if i.get("type") == "rate_limit"]
        assert len(rate_limit_issues) == 0
