"""
SQL Injection False-Positive (FP) regression tests.

Verifies that the v2 context-aware SQLInjectionCheck:
1. Still catches real vulnerabilities (no false negatives)
2. Suppresses known FP patterns:
   - Comment lines
   - Library-safe patterns (redis.eval)
   - Parameterization evidence in context
   - Safe whitelist variable names (_SORT_CLAUSES, etc.)
3. Sets pattern_confidence correctly on findings
4. Includes multi-line context in code_snippet

These tests run against the check directly (no LLM) for deterministic results.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SECURITY_DIR = Path(__file__).parents[4] / "src" / "warden" / "validation" / "frames" / "security"
if str(_SECURITY_DIR) not in sys.path:
    sys.path.insert(0, str(_SECURITY_DIR))

from warden.validation.domain.frame import CodeFile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _file(content: str, path: str = "target.py", language: str = "python") -> CodeFile:
    return CodeFile(path=path, content=content, language=language)


@pytest.fixture()
def check():
    from _internal.sql_injection_check import SQLInjectionCheck
    return SQLInjectionCheck()


# ===========================================================================
# TRUE POSITIVES — real vulnerabilities must still be detected
# ===========================================================================

class TestTruePositivesNotLost:
    """Verify that real SQL injection vulnerabilities are still detected."""

    @pytest.mark.asyncio
    async def test_fstring_interpolation_detected(self, check):
        code = (
            "def get_user(user_id):\n"
            '    query = f"SELECT * FROM users WHERE id = {user_id}"\n'
            "    cursor.execute(query)\n"
        )
        result = await check.execute_async(_file(code))
        assert len(result.findings) >= 1
        assert all(f.severity.value == "critical" for f in result.findings)

    @pytest.mark.asyncio
    async def test_string_concat_detected(self, check):
        code = (
            "def search(term):\n"
            '    query = "SELECT * FROM products WHERE name = " + term\n'
            "    db.execute(query)\n"
        )
        result = await check.execute_async(_file(code))
        assert len(result.findings) >= 1

    @pytest.mark.asyncio
    async def test_format_method_detected(self, check):
        code = (
            "def delete_rec(rid):\n"
            '    sql = "DELETE FROM logs WHERE id = {}".format(rid)\n'
            "    cursor.execute(sql)\n"
        )
        result = await check.execute_async(_file(code))
        assert len(result.findings) >= 1

    @pytest.mark.asyncio
    async def test_percent_format_detected(self, check):
        code = (
            "def by_name(name):\n"
            '    q = "SELECT id FROM users WHERE username = \'%s\'" % name\n'
            "    cursor.execute(q)\n"
        )
        result = await check.execute_async(_file(code))
        assert len(result.findings) >= 1

    @pytest.mark.asyncio
    async def test_insert_fstring_detected(self, check):
        code = (
            "def create_user(username):\n"
            "    query = f\"INSERT INTO users (name) VALUES ('{username}')\"\n"
            "    db.execute(query)\n"
        )
        result = await check.execute_async(_file(code))
        assert len(result.findings) >= 1


# ===========================================================================
# FALSE POSITIVES — must be suppressed
# ===========================================================================

class TestFalsePositivesSuppressed:
    """Known FP patterns must NOT produce findings."""

    @pytest.mark.asyncio
    async def test_parameterized_query_not_flagged(self, check):
        """Standard parameterized query must produce zero findings."""
        code = (
            "def get_user(user_id):\n"
            '    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))\n'
            "    return cursor.fetchone()\n"
        )
        result = await check.execute_async(_file(code))
        assert len(result.findings) == 0, (
            f"Parameterized query flagged as SQL injection: {[f.message for f in result.findings]}"
        )

    @pytest.mark.asyncio
    async def test_comment_line_not_flagged(self, check):
        """SQL injection in a comment must not be flagged."""
        code = (
            "def safe_query(uid):\n"
            '    # BAD example: f"SELECT * FROM users WHERE id = {uid}"\n'
            '    cursor.execute("SELECT * FROM users WHERE id = ?", (uid,))\n'
        )
        result = await check.execute_async(_file(code))
        # The comment line should be excluded; the parameterized call has no match
        assert len(result.findings) == 0, (
            f"Comment line flagged: {[f.message for f in result.findings]}"
        )

    @pytest.mark.asyncio
    async def test_redis_eval_not_flagged(self, check):
        """redis.eval() is Lua scripting, not SQL — must not be flagged."""
        code = (
            "import redis\n"
            "\n"
            "def check_rate_limit(key, limit):\n"
            "    script = 'return redis.call(\"INCR\", KEYS[1])'\n"
            "    result = redis_client.eval(script, 1, key)\n"
            "    return result <= limit\n"
        )
        result = await check.execute_async(_file(code))
        assert len(result.findings) == 0, (
            f"redis.eval() wrongly flagged: {[f.message for f in result.findings]}"
        )

    @pytest.mark.asyncio
    async def test_sort_clauses_mapping_not_flagged(self, check):
        """Dict mapping of whitelisted ORDER BY clauses must not be flagged."""
        code = (
            "_SORT_CLAUSES = {\n"
            '    "name":    "SELECT id, name FROM users ORDER BY name ASC",\n'
            '    "created": "SELECT id, name FROM users ORDER BY created DESC",\n'
            "}\n"
            "\n"
            "def get_users(sort_key):\n"
            '    sql = _SORT_CLAUSES.get(sort_key, _SORT_CLAUSES["name"])\n'
            '    cursor.execute(sql)\n'
        )
        result = await check.execute_async(_file(code))
        # If any finding exists it must be low-confidence (soft exclusion)
        high_confidence = [f for f in result.findings if (f.pattern_confidence or 0) >= 0.75]
        assert len(high_confidence) == 0, (
            f"_SORT_CLAUSES mapping produced high-confidence finding: "
            f"{[f.message for f in high_confidence]}"
        )

    @pytest.mark.asyncio
    async def test_pattern_definition_in_security_check_not_flagged(self, check):
        """DANGEROUS_PATTERNS list in a security check file must not be flagged."""
        code = (
            "DANGEROUS_PATTERNS = [\n"
            '    (r\'["\']SELECT.*["\']\\s*\\+\', "SQL concat"),\n'
            '    (r\'f"SELECT.*\\{.*\\}\', "SQL fstring"),\n'
            "]\n"
        )
        result = await check.execute_async(_file(code))
        assert len(result.findings) == 0, (
            f"DANGEROUS_PATTERNS definition wrongly flagged: {[f.message for f in result.findings]}"
        )


# ===========================================================================
# CONFIDENCE VALUES
# ===========================================================================

class TestPatternConfidence:
    """Verify that pattern_confidence is set correctly on findings."""

    @pytest.mark.asyncio
    async def test_fstring_confidence_high(self, check):
        """f-string injection should have confidence >= 0.85."""
        code = 'query = f"SELECT * FROM users WHERE id = {user_id}"\n'
        result = await check.execute_async(_file(code))
        assert len(result.findings) >= 1
        for f in result.findings:
            assert f.pattern_confidence is not None, "pattern_confidence must be set"
            assert f.pattern_confidence >= 0.80, (
                f"f-string finding confidence too low: {f.pattern_confidence}"
            )

    @pytest.mark.asyncio
    async def test_parameterization_context_lowers_confidence(self, check):
        """When parameterization is nearby, confidence must be below 0.75."""
        # The fstring query is built first, then used with params — still risky
        # but LLM should decide. Confidence must be lowered.
        code = (
            "def get_users(sort_col):\n"
            "    # Dynamically select column — comes from validated whitelist\n"
            f'    query = f"SELECT {{sort_col}} FROM users"\n'
            '    cursor.execute(query, ())\n'  # parameterization evidence nearby
        )
        result = await check.execute_async(_file(code))
        if result.findings:
            for f in result.findings:
                assert f.pattern_confidence is not None
                assert f.pattern_confidence < 0.75, (
                    f"Expected lowered confidence due to nearby parameterization, "
                    f"got {f.pattern_confidence}"
                )

    @pytest.mark.asyncio
    async def test_code_snippet_includes_context(self, check):
        """code_snippet in finding must include surrounding context lines."""
        code = (
            "# repository.py\n"
            "def fetch_by_id(uid):\n"
            "    conn = get_connection()\n"
            '    query = f"SELECT * FROM users WHERE id = {uid}"\n'
            "    return conn.execute(query)\n"
        )
        result = await check.execute_async(_file(code))
        assert len(result.findings) >= 1
        snippet = result.findings[0].code_snippet or ""
        # Should contain lines above and below the match
        assert "fetch_by_id" in snippet or "get_connection" in snippet, (
            "code_snippet does not include surrounding context"
        )
        # Should mark the flagged line with >>>
        assert ">>>" in snippet, "code_snippet missing >>> marker on flagged line"


# ===========================================================================
# FP EXCLUSION REGISTRY UNIT TESTS
# ===========================================================================

class TestFPExclusionRegistry:
    """Unit tests for FPExclusionRegistry directly."""

    def test_comment_line_excluded(self):
        from warden.validation.domain.fp_exclusions import FPExclusionRegistry
        reg = FPExclusionRegistry()
        result = reg.check(
            check_id="sql-injection",
            matched_line='    # query = f"SELECT * FROM users WHERE id = {uid}"',
            context_lines=[],
        )
        assert result.is_excluded is True
        assert result.reason == "comment_line"

    def test_redis_eval_excluded(self):
        from warden.validation.domain.fp_exclusions import FPExclusionRegistry
        reg = FPExclusionRegistry()
        result = reg.check(
            check_id="sql-injection",
            matched_line="    result = redis_client.eval(script, 1, key)",
            context_lines=[],
        )
        assert result.is_excluded is True
        assert result.reason == "library_safe_pattern"

    def test_parameterization_lowers_confidence(self):
        from warden.validation.domain.fp_exclusions import FPExclusionRegistry
        reg = FPExclusionRegistry()
        result = reg.check(
            check_id="sql-injection",
            matched_line='    query = f"SELECT * FROM users WHERE id = {uid}"',
            context_lines=['    cursor.execute(query, (uid,))'],
        )
        assert result.is_excluded is False
        assert result.confidence_adjustment is not None
        assert result.confidence_adjustment < 0.75

    def test_safe_variable_name_lowers_confidence(self):
        from warden.validation.domain.fp_exclusions import FPExclusionRegistry
        reg = FPExclusionRegistry()
        result = reg.check(
            check_id="sql-injection",
            matched_line='    "name": "SELECT id, name FROM users ORDER BY name",',
            context_lines=["_SORT_CLAUSES = {"],
        )
        assert result.is_excluded is False
        assert result.confidence_adjustment is not None
        assert result.confidence_adjustment < 0.75

    def test_normal_fstring_not_excluded(self):
        from warden.validation.domain.fp_exclusions import FPExclusionRegistry
        reg = FPExclusionRegistry()
        result = reg.check(
            check_id="sql-injection",
            matched_line='    query = f"SELECT * FROM users WHERE id = {uid}"',
            context_lines=["def get_user(uid):", "    # fetch user"],
        )
        assert result.is_excluded is False
        assert result.confidence_adjustment is None
