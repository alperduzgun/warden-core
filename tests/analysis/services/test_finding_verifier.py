"""
Unit tests for FindingVerificationService.

Covers:
  Issue #620 — Cross-file cache key: (rule_id, code_hash) instead of
               (file_path, rule_id, code_hash).
  Issue #621 — Parallel verification by category: secrets / taint /
               structural / other run concurrently via asyncio.gather.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.analysis.services.finding_verifier import FindingVerificationService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_client(response_content: str | None = None, success: bool = True) -> MagicMock:
    """Return a mock LLM client whose complete_async resolves to a canned response."""
    client = MagicMock()
    resp = MagicMock()
    resp.success = success
    resp.content = response_content
    resp.error_message = "error" if not success else None
    client.complete_async = AsyncMock(return_value=resp)
    return client


def _make_service(
    llm_client: Any | None = None,
    memory_manager: Any | None = None,
    enabled: bool = True,
) -> FindingVerificationService:
    if llm_client is None:
        llm_client = _make_llm_client()
    svc = FindingVerificationService(
        llm_client=llm_client,
        memory_manager=memory_manager,
        enabled=enabled,
    )
    return svc


def _make_finding(
    rule_id: str = "SEC-001",
    code: str = "x = eval(input())",
    message: str = "dangerous eval",
    file_path: str = "src/app.py",
    location: str = "src/app.py:10",
    finding_id: str | None = None,
) -> dict:
    return {
        "id": finding_id or rule_id,
        "rule_id": rule_id,
        "code": code,
        "message": message,
        "file_path": file_path,
        "location": location,
        "line_number": 10,
    }


# ===========================================================================
# Issue #620 — Cross-file cache key tests
# ===========================================================================


class TestGenerateKeyCrossFile:
    """Cache key must be identical for same (rule_id, code) across different files."""

    def test_same_rule_same_code_different_file_same_key(self):
        """Two findings with the same rule_id and code but different file paths
        must produce the same cache key so the cache entry is shared."""
        svc = _make_service()

        f1 = _make_finding(rule_id="SEC-001", code="x = eval(user_input)", file_path="src/a.py", location="src/a.py:5")
        f2 = _make_finding(rule_id="SEC-001", code="x = eval(user_input)", file_path="src/b.py", location="src/b.py:99")

        key1 = svc._generate_key(f1)
        key2 = svc._generate_key(f2)

        assert key1 == key2, (
            "Identical rule_id + code in different files must share a cache key"
        )

    def test_different_code_different_key(self):
        """Different code snippets must produce different cache keys."""
        svc = _make_service()

        f1 = _make_finding(rule_id="SEC-001", code="eval(user_input)")
        f2 = _make_finding(rule_id="SEC-001", code="exec(user_input)")

        key1 = svc._generate_key(f1)
        key2 = svc._generate_key(f2)

        assert key1 != key2

    def test_different_rule_id_different_key(self):
        """Same code but different rule_id must produce different keys."""
        svc = _make_service()

        f1 = _make_finding(rule_id="SEC-001", code="eval(x)")
        f2 = _make_finding(rule_id="SEC-002", code="eval(x)")

        key1 = svc._generate_key(f1)
        key2 = svc._generate_key(f2)

        assert key1 != key2

    def test_key_format_contains_rule_id(self):
        """Cache key must begin with rule_id for human readability / debuggability."""
        svc = _make_service()

        f = _make_finding(rule_id="MY-RULE-42", code="some_code()")
        key = svc._generate_key(f)

        assert key.startswith("MY-RULE-42:"), f"Key should start with rule_id, got: {key}"

    def test_fallback_to_message_when_no_code(self):
        """When code is empty the message is used as the content anchor."""
        svc = _make_service()

        f1 = _make_finding(rule_id="SEC-001", code="", message="SQL injection detected")
        f2 = _make_finding(rule_id="SEC-001", code="", message="SQL injection detected", file_path="other/file.py")
        f3 = _make_finding(rule_id="SEC-001", code="", message="Different message")

        key1 = svc._generate_key(f1)
        key2 = svc._generate_key(f2)
        key3 = svc._generate_key(f3)

        assert key1 == key2, "Same rule+message in different files must share key"
        assert key1 != key3, "Different messages must produce different keys"

    def test_key_is_deterministic(self):
        """Calling _generate_key twice on the same finding returns identical key."""
        svc = _make_service()

        f = _make_finding(rule_id="SEC-099", code="os.system(cmd)")
        assert svc._generate_key(f) == svc._generate_key(f)

    def test_old_keys_with_file_path_produce_cache_miss(self):
        """Old-format cache entries (keyed with file_path) should never hit the new
        key — they'll be a graceful miss and trigger re-verification."""
        svc = _make_service()
        finding = _make_finding(rule_id="SEC-001", code="x = eval(input())", file_path="src/app.py")

        # Simulate an old cache entry using the previous key scheme
        old_key = f"SEC-001:src/app.py:{hashlib.sha256(b'x = eval(input())').hexdigest()}"
        new_key = svc._generate_key(finding)

        assert new_key != old_key, "New key must not collide with legacy keys"


# ===========================================================================
# Issue #621 — Category classification tests
# ===========================================================================


class TestCategorizeFindingsMethod:
    """Unit tests for _categorize_findings()."""

    def _svc(self) -> FindingVerificationService:
        return _make_service()

    def test_secrets_category_matched(self):
        svc = self._svc()
        findings = [_make_finding(rule_id="detect-password-leak")]
        cats = svc._categorize_findings(findings)
        assert "secrets" in cats
        assert findings[0] in cats["secrets"]

    def test_token_rule_goes_to_secrets(self):
        svc = self._svc()
        f = _make_finding(rule_id="hardcoded-token")
        cats = svc._categorize_findings([f])
        assert "secrets" in cats and f in cats["secrets"]

    def test_credential_rule_goes_to_secrets(self):
        svc = self._svc()
        f = _make_finding(rule_id="exposed-credential")
        cats = svc._categorize_findings([f])
        assert "secrets" in cats and f in cats["secrets"]

    def test_sql_injection_goes_to_taint(self):
        svc = self._svc()
        f = _make_finding(rule_id="sql-injection-risk")
        cats = svc._categorize_findings([f])
        assert "taint" in cats and f in cats["taint"]

    def test_xss_goes_to_taint(self):
        svc = self._svc()
        f = _make_finding(rule_id="potential-xss")
        cats = svc._categorize_findings([f])
        assert "taint" in cats and f in cats["taint"]

    def test_command_injection_goes_to_taint(self):
        svc = self._svc()
        f = _make_finding(rule_id="command-injection")
        cats = svc._categorize_findings([f])
        assert "taint" in cats and f in cats["taint"]

    def test_orphan_goes_to_structural(self):
        svc = self._svc()
        f = _make_finding(rule_id="orphan-module")
        cats = svc._categorize_findings([f])
        assert "structural" in cats and f in cats["structural"]

    def test_unused_goes_to_structural(self):
        svc = self._svc()
        f = _make_finding(rule_id="unused-variable")
        cats = svc._categorize_findings([f])
        assert "structural" in cats and f in cats["structural"]

    def test_unreferenced_goes_to_structural(self):
        svc = self._svc()
        f = _make_finding(rule_id="unreferenced-function")
        cats = svc._categorize_findings([f])
        assert "structural" in cats and f in cats["structural"]

    def test_unknown_rule_goes_to_other(self):
        svc = self._svc()
        f = _make_finding(rule_id="timing-attack")
        cats = svc._categorize_findings([f])
        assert "other" in cats and f in cats["other"]

    def test_empty_input_returns_empty_dict(self):
        svc = self._svc()
        cats = svc._categorize_findings([])
        assert cats == {}

    def test_empty_categories_are_dropped(self):
        """Categories with zero findings must not appear in the result dict."""
        svc = self._svc()
        f = _make_finding(rule_id="sql-injection")
        cats = svc._categorize_findings([f])
        assert "taint" in cats
        assert "secrets" not in cats
        assert "structural" not in cats
        assert "other" not in cats

    def test_mixed_findings_correctly_distributed(self):
        svc = self._svc()
        findings = [
            _make_finding(rule_id="password-leak"),
            _make_finding(rule_id="sql-injection"),
            _make_finding(rule_id="orphan-class"),
            _make_finding(rule_id="weird-algorithm"),
        ]
        cats = svc._categorize_findings(findings)

        assert len(cats["secrets"]) == 1
        assert len(cats["taint"]) == 1
        assert len(cats["structural"]) == 1
        assert len(cats["other"]) == 1

    def test_total_count_preserved(self):
        """No finding must be silently dropped or duplicated during categorization."""
        svc = self._svc()
        findings = [
            _make_finding(rule_id="password-leak"),
            _make_finding(rule_id="xss-risk"),
            _make_finding(rule_id="unused-import"),
            _make_finding(rule_id="eval-call"),
        ]
        cats = svc._categorize_findings(findings)
        total = sum(len(v) for v in cats.values())
        assert total == len(findings)


# ===========================================================================
# Issue #621 — Parallel verification integration tests
# ===========================================================================


class TestVerifyFindingsAsyncParallel:
    """verify_findings_async() must produce results equivalent to sequential processing
    while running categories in parallel."""

    def _llm_approve_all(self) -> MagicMock:
        """LLM client that approves every finding as a true positive."""
        import json

        client = MagicMock()

        async def _respond(prompt, system, **kwargs):
            # Parse how many findings are in the batch from the prompt
            count = prompt.count("FINDING #")
            results = [
                {"idx": i, "is_true_positive": True, "confidence": 0.9, "reason": "real issue"}
                for i in range(count)
            ]
            resp = MagicMock()
            resp.success = True
            resp.content = json.dumps(results)
            return resp

        client.complete_async = AsyncMock(side_effect=_respond)
        return client

    def _llm_reject_all(self) -> MagicMock:
        """LLM client that rejects every finding as a false positive."""
        import json

        client = MagicMock()

        async def _respond(prompt, system, **kwargs):
            count = prompt.count("FINDING #")
            results = [
                {"idx": i, "is_true_positive": False, "confidence": 0.95, "reason": "false positive"}
                for i in range(count)
            ]
            resp = MagicMock()
            resp.success = True
            resp.content = json.dumps(results)
            return resp

        client.complete_async = AsyncMock(side_effect=_respond)
        return client

    @pytest.mark.asyncio
    async def test_all_categories_processed(self):
        """Findings from all four categories must appear in output when LLM approves all."""
        client = self._llm_approve_all()
        svc = _make_service(llm_client=client)
        svc._get_safe_batch_size = MagicMock(return_value=10)

        findings = [
            _make_finding(rule_id="password-leak",    code="pwd='secret'",    location="a.py:1"),
            _make_finding(rule_id="sql-injection",    code="query=user_in",   location="b.py:2"),
            _make_finding(rule_id="orphan-class",     code="class Dead: ...", location="c.py:3"),
            _make_finding(rule_id="timing-attack",    code="if a == b: ...",  location="d.py:4"),
        ]

        result = await svc.verify_findings_async(findings)

        result_ids = {f["id"] for f in result}
        for f in findings:
            assert f["id"] in result_ids, f"Finding {f['id']} was lost in parallel verification"

    @pytest.mark.asyncio
    async def test_parallel_equivalent_to_sequential(self):
        """Results must contain the same findings as a baseline sequential run."""
        client = self._llm_approve_all()
        svc = _make_service(llm_client=client)
        svc._get_safe_batch_size = MagicMock(return_value=10)

        findings = [
            _make_finding(rule_id="exposed-token",  code="tok='abc'",  location="x.py:1"),
            _make_finding(rule_id="xss-reflected",  code="<script>",   location="x.py:2"),
            _make_finding(rule_id="unused-fn",      code="def noop():", location="x.py:3"),
            _make_finding(rule_id="magic-numbers",  code="x = 42",     location="x.py:4"),
        ]

        result = await svc.verify_findings_async(findings)

        # All four should survive (LLM approves all)
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_false_positives_dropped_across_categories(self):
        """When LLM rejects all, zero findings survive regardless of category."""
        client = self._llm_reject_all()
        svc = _make_service(llm_client=client)
        svc._get_safe_batch_size = MagicMock(return_value=10)

        findings = [
            _make_finding(rule_id="credential-leak", code="c='pass'",  location="f.py:1"),
            _make_finding(rule_id="sql-injection",   code="q=user",    location="g.py:2"),
        ]

        result = await svc.verify_findings_async(findings)

        assert result == [], "All rejected findings must be dropped"

    @pytest.mark.asyncio
    async def test_disabled_service_returns_original(self):
        """When enabled=False, findings are returned as-is without any LLM calls."""
        client = MagicMock()
        svc = _make_service(llm_client=client, enabled=False)
        findings = [_make_finding()]
        result = await svc.verify_findings_async(findings)
        assert result == findings
        client.complete_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_category_failure_does_not_break_others(self):
        """If one category's LLM call raises, other categories still produce results."""
        import json

        call_count = 0

        async def _flaky_respond(prompt, system, **kwargs):
            nonlocal call_count
            call_count += 1
            count = prompt.count("FINDING #")
            # Fail on the first call (secrets category), succeed on others
            if call_count == 1:
                raise RuntimeError("LLM network error")
            results = [
                {"idx": i, "is_true_positive": True, "confidence": 0.85, "reason": "ok"}
                for i in range(count)
            ]
            resp = MagicMock()
            resp.success = True
            resp.content = json.dumps(results)
            return resp

        client = MagicMock()
        client.complete_async = AsyncMock(side_effect=_flaky_respond)

        svc = _make_service(llm_client=client)
        svc._get_safe_batch_size = MagicMock(return_value=10)

        findings = [
            _make_finding(rule_id="password-leak",  code="pw='x'",   location="a.py:1"),
            _make_finding(rule_id="sql-injection",  code="q=user",   location="b.py:2"),
        ]

        # Should not raise — failed category is handled gracefully
        result = await svc.verify_findings_async(findings)

        # sql finding (second call, succeeds) must survive; secrets finding
        # (first call, fails) is kept with fallback meta per circuit-break logic
        ids = {f["id"] for f in result}
        assert "sql-injection" in ids

    @pytest.mark.asyncio
    async def test_cache_hit_prevents_llm_call(self):
        """Findings with a cache hit must not reach the LLM at all."""
        cached_result = {"is_true_positive": True, "confidence": 0.95, "reason": "cached"}

        memory = MagicMock()
        memory.get_llm_cache = MagicMock(return_value=cached_result)
        memory.set_llm_cache = MagicMock()

        client = MagicMock()
        client.complete_async = AsyncMock()

        svc = _make_service(llm_client=client, memory_manager=memory)

        finding = _make_finding(rule_id="sql-injection", code="q=user", location="a.py:1")
        result = await svc.verify_findings_async([finding])

        assert len(result) == 1
        client.complete_async.assert_not_called()


# ===========================================================================
# Issue #620 — Cache hit log
# ===========================================================================


class TestCacheHitLogging:
    """_check_cache() must log verification_cache_hit on a hit."""

    def test_cache_hit_triggers_log(self):
        """On a cache hit, logger.debug must be called with 'verification_cache_hit'."""
        cached = {"is_true_positive": True, "confidence": 0.9}
        memory = MagicMock()
        memory.get_llm_cache = MagicMock(return_value=cached)

        svc = _make_service(memory_manager=memory)

        with patch.object(svc, "_check_cache", wraps=svc._check_cache) as patched:
            with patch("warden.analysis.services.finding_verifier.logger") as mock_logger:
                result = svc._check_cache("some:key")
                mock_logger.debug.assert_called_once_with("verification_cache_hit", key="some:key")

        assert result == cached

    def test_cache_miss_no_hit_log(self):
        """On a cache miss, verification_cache_hit must NOT be logged."""
        memory = MagicMock()
        memory.get_llm_cache = MagicMock(return_value=None)

        svc = _make_service(memory_manager=memory)

        with patch("warden.analysis.services.finding_verifier.logger") as mock_logger:
            result = svc._check_cache("some:key")

        mock_logger.debug.assert_not_called()
        assert result is None
