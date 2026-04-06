"""
End-to-End False Positive reduction validation tests.

Validates that the complete FP reduction pipeline (exclusions + context window
+ confidence scoring + batch_processor routing) reduces false positives across
all pattern-based security checks without losing true positive detections.

These tests run against the checks directly (no LLM) and verify:
1. Known FP patterns are suppressed at the check level
2. Known TP patterns still produce findings
3. pattern_confidence is set correctly for routing decisions
4. The batch_processor threshold logic works as expected

Issue: Warden FP improvement initiative (Phase 1-3)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SECURITY_DIR = Path(__file__).parents[4] / "src" / "warden" / "validation" / "frames" / "security"
if str(_SECURITY_DIR) not in sys.path:
    sys.path.insert(0, str(_SECURITY_DIR))

from warden.validation.domain.frame import CodeFile, Finding

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 0.75  # Matches batch_processor._PATTERN_CONFIDENCE_THRESHOLD


def _file(content: str, path: str = "target.py", language: str = "python") -> CodeFile:
    return CodeFile(path=path, content=content, language=language)


@pytest.fixture()
def security_frame():
    """SecurityFrame without LLM (deterministic mode)."""
    from warden.validation.frames.security.security_frame import SecurityFrame
    return SecurityFrame()


def _findings_for(result, check_substring: str) -> list[Finding]:
    return [f for f in result.findings if check_substring in f.id]


def _high_confidence(findings: list[Finding]) -> list[Finding]:
    """Findings that would bypass LLM (confidence >= threshold or unset)."""
    return [
        f for f in findings
        if f.pattern_confidence is None or f.pattern_confidence >= CONFIDENCE_THRESHOLD
    ]


def _low_confidence(findings: list[Finding]) -> list[Finding]:
    """Findings that would be routed to LLM (confidence < threshold)."""
    return [f for f in findings if f.pattern_confidence is not None and f.pattern_confidence < CONFIDENCE_THRESHOLD]


# ===========================================================================
# 1. SQL Injection FP Reduction
# ===========================================================================

class TestSQLInjectionFPReduction:
    """SQL injection FP scenarios that were fixed in Phase 1."""

    @pytest.mark.asyncio
    async def test_redis_eval_not_flagged(self, security_frame):
        code = (
            "import redis\n\n"
            "def rate_limit(key):\n"
            "    script = 'return redis.call(\"INCR\", KEYS[1])'\n"
            "    return redis_client.eval(script, 1, key)\n"
        )
        result = await security_frame.execute_async(_file(code))
        sql_findings = _findings_for(result, "sql-injection")
        assert len(sql_findings) == 0, f"redis.eval() wrongly flagged: {[f.message for f in sql_findings]}"

    @pytest.mark.asyncio
    async def test_sort_clauses_produces_low_confidence(self, security_frame):
        """_SORT_CLAUSES pattern must produce low-confidence findings (routed to LLM)."""
        code = (
            "_SORT_CLAUSES = {\n"
            '    "name": "SELECT id FROM users ORDER BY name",\n'
            "}\n"
        )
        result = await security_frame.execute_async(_file(code))
        sql_findings = _findings_for(result, "sql-injection")
        high_conf = _high_confidence(sql_findings)
        assert len(high_conf) == 0, (
            f"_SORT_CLAUSES should not produce high-confidence findings: "
            f"{[(f.message, f.pattern_confidence) for f in high_conf]}"
        )

    @pytest.mark.asyncio
    async def test_parameterized_context_produces_low_confidence(self, security_frame):
        """SQL building with nearby parameterized execution must lower confidence."""
        code = (
            "def search(query_fragment):\n"
            '    sql = f"SELECT {query_fragment} FROM data"\n'
            "    cursor.execute(sql, ())\n"
        )
        result = await security_frame.execute_async(_file(code))
        sql_findings = _findings_for(result, "sql-injection")
        if sql_findings:
            assert all(f.pattern_confidence is not None and f.pattern_confidence < CONFIDENCE_THRESHOLD
                       for f in sql_findings), (
                f"Expected low confidence but got: {[(f.message, f.pattern_confidence) for f in sql_findings]}"
            )

    @pytest.mark.asyncio
    async def test_real_sql_injection_high_confidence(self, security_frame):
        """Real SQL injection must produce high-confidence findings."""
        code = (
            "def get_user(uid):\n"
            '    q = f"SELECT * FROM users WHERE id = {uid}"\n'
            "    db.execute(q)\n"
        )
        result = await security_frame.execute_async(_file(code))
        sql_findings = _findings_for(result, "sql-injection")
        assert len(sql_findings) >= 1
        high_conf = _high_confidence(sql_findings)
        assert len(high_conf) >= 1, "Real SQL injection must produce at least one high-confidence finding"


# ===========================================================================
# 2. XSS FP Reduction
# ===========================================================================

class TestXSSFPReduction:
    """XSS FP scenarios fixed in Phase 2."""

    @pytest.mark.asyncio
    async def test_comment_line_not_flagged(self, security_frame):
        code = (
            "function safe(el, text) {\n"
            "    // BAD: el.innerHTML = text — XSS risk, do not use\n"
            "    el.textContent = text;  // safe\n"
            "}\n"
        )
        result = await security_frame.execute_async(_file(code, path="app.js", language="javascript"))
        xss_findings = _findings_for(result, "xss")
        assert len(xss_findings) == 0, f"Comment line wrongly flagged: {[f.message for f in xss_findings]}"

    @pytest.mark.asyncio
    async def test_dangerous_patterns_definition_not_flagged(self, security_frame):
        """Pattern definitions in check files must not produce findings."""
        code = (
            "DANGEROUS_PATTERNS = [\n"
            "    (r'\\.innerHTML\\s*=', 'innerHTML assignment'),\n"
            "    (r'eval\\(', 'eval usage'),\n"
            "]\n"
        )
        result = await security_frame.execute_async(_file(code))
        xss_findings = _findings_for(result, "xss")
        assert len(xss_findings) == 0, f"Pattern definition wrongly flagged: {[f.message for f in xss_findings]}"

    @pytest.mark.asyncio
    async def test_real_innerhtml_high_confidence(self, security_frame):
        code = (
            "function render(msg) {\n"
            "    document.getElementById('out').innerHTML = msg;\n"
            "}\n"
        )
        result = await security_frame.execute_async(_file(code, path="app.js", language="javascript"))
        xss_findings = _findings_for(result, "xss")
        assert len(xss_findings) >= 1
        assert all(
            f.pattern_confidence is None or f.pattern_confidence >= 0.80
            for f in xss_findings
        ), "innerHTML should produce high-confidence finding"


# ===========================================================================
# 3. Confidence Scoring Coverage
# ===========================================================================

class TestConfidenceScoringCoverage:
    """Verify pattern_confidence is populated across all check types."""

    @pytest.mark.asyncio
    async def test_sql_injection_sets_confidence(self, security_frame):
        code = 'q = f"SELECT * FROM t WHERE id = {uid}"\n'
        result = await security_frame.execute_async(_file(code))
        sql_findings = _findings_for(result, "sql-injection")
        assert len(sql_findings) >= 1
        for f in sql_findings:
            assert f.pattern_confidence is not None, (
                f"sql-injection finding missing pattern_confidence: {f.message}"
            )

    @pytest.mark.asyncio
    async def test_xss_sets_confidence(self, security_frame):
        code = "el.innerHTML = userInput;\n"
        result = await security_frame.execute_async(_file(code, path="a.js", language="javascript"))
        xss_findings = _findings_for(result, "xss")
        assert len(xss_findings) >= 1
        for f in xss_findings:
            assert f.pattern_confidence is not None, (
                f"xss finding missing pattern_confidence: {f.message}"
            )

    @pytest.mark.asyncio
    async def test_hardcoded_password_sets_confidence(self, security_frame):
        code = "password = 'my_secret_pass'\n"
        result = await security_frame.execute_async(_file(code))
        pw_findings = _findings_for(result, "hardcoded-password")
        assert len(pw_findings) >= 1
        for f in pw_findings:
            assert f.pattern_confidence is not None, (
                f"hardcoded-password finding missing pattern_confidence: {f.message}"
            )
            assert f.pattern_confidence >= CONFIDENCE_THRESHOLD, (
                f"Hardcoded password should have high confidence: {f.pattern_confidence}"
            )

    @pytest.mark.asyncio
    async def test_weak_crypto_cipher_sets_confidence(self, security_frame):
        code = (
            "from Crypto.Cipher import DES\n"
            "cipher = DES.new(key, DES.MODE_ECB)\n"
        )
        result = await security_frame.execute_async(_file(code))
        crypto_findings = _findings_for(result, "weak-crypto")
        assert len(crypto_findings) >= 1
        for f in crypto_findings:
            assert f.pattern_confidence is not None, (
                f"weak-crypto finding missing pattern_confidence: {f.message}"
            )
            assert f.pattern_confidence >= CONFIDENCE_THRESHOLD, (
                f"Weak cipher should have high confidence: {f.pattern_confidence}"
            )


# ===========================================================================
# 4. Batch Processor Routing Logic
# ===========================================================================

class TestBatchProcessorRouting:
    """Verify the confidence-based routing decision logic."""

    def test_low_confidence_finding_routed_to_llm(self):
        """A finding with pattern_confidence < 0.75 must be routed to LLM."""
        finding = Finding(
            id="security-sql-injection-0",
            severity="critical",
            message="Potential SQL injection",
            location="target.py:5",
            detection_source="pattern",
            pattern_confidence=0.45,  # Low: parameterization detected in context
        )
        # Simulate batch_processor logic
        _FULLY_DETERMINISTIC = {"taint", "ast", "deterministic"}
        _THRESHOLD = 0.75
        ds = finding.detection_source or ""
        pc = finding.pattern_confidence
        is_deterministic = (
            ds in _FULLY_DETERMINISTIC
            or (ds == "pattern" and (pc is None or pc >= _THRESHOLD))
        )
        assert not is_deterministic, "Low-confidence pattern finding must be routed to LLM"

    def test_high_confidence_finding_skips_llm(self):
        """A finding with pattern_confidence >= 0.75 must bypass LLM."""
        finding = Finding(
            id="security-sql-injection-0",
            severity="critical",
            message="Potential SQL injection",
            location="target.py:5",
            detection_source="pattern",
            pattern_confidence=0.87,  # High: clear f-string injection
        )
        _FULLY_DETERMINISTIC = {"taint", "ast", "deterministic"}
        _THRESHOLD = 0.75
        ds = finding.detection_source or ""
        pc = finding.pattern_confidence
        is_deterministic = (
            ds in _FULLY_DETERMINISTIC
            or (ds == "pattern" and (pc is None or pc >= _THRESHOLD))
        )
        assert is_deterministic, "High-confidence pattern finding must bypass LLM"

    def test_unscored_finding_skips_llm_backward_compat(self):
        """Unscored findings (pattern_confidence=None) must bypass LLM for backward compat."""
        finding = Finding(
            id="security-secrets-0",
            severity="critical",
            message="Hardcoded secret",
            location="config.py:3",
            detection_source="pattern",
            pattern_confidence=None,  # Legacy: check did not set confidence
        )
        _FULLY_DETERMINISTIC = {"taint", "ast", "deterministic"}
        _THRESHOLD = 0.75
        ds = finding.detection_source or ""
        pc = finding.pattern_confidence
        is_deterministic = (
            ds in _FULLY_DETERMINISTIC
            or (ds == "pattern" and (pc is None or pc >= _THRESHOLD))
        )
        assert is_deterministic, "Unscored findings must preserve legacy bypass behavior"
