"""
Tests for `warden rules autoimprove` — keep-or-revert loop helpers.

Covers:
- _collect_fp_examples
- _apply_pattern_to_exclusions + _revert_file
- _make_demo_pattern
- _get_check_f1
- _snapshot_file
- CLI dry-run (no file modification)
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers to import internal functions
# ---------------------------------------------------------------------------

from warden.cli.commands.rules import (
    _apply_pattern_to_exclusions,
    _collect_fp_examples,
    _get_check_f1,
    _make_demo_pattern,
    _revert_file,
    _snapshot_file,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FP_FILE_CONTENT = textwrap.dedent('''\
    """
    Safe asyncpg patterns.

    corpus_labels:
      sql-injection: 0
      xss: 0
    """

    async def fetch(pool, user_id):
        return await pool.fetch("SELECT * FROM users WHERE id=$1", user_id)
''')

_FP_EXCLUSIONS_SKELETON = (
    'import re\n\n'
    '_LIBRARY_SAFE_PATTERNS = {\n'
    '    "sql-injection": [\n'
    '        re.compile(r"existing_sql_pattern", re.IGNORECASE),\n'
    '    ],\n'
    '    "xss": [\n'
    '        re.compile(r"existing_xss_pattern", re.IGNORECASE),\n'
    '    ],\n'
    '}\n'
)


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "python_sqli_fp.py").write_text(_FP_FILE_CONTENT, encoding="utf-8")
    return d


@pytest.fixture
def fp_exclusions_file(tmp_path: Path) -> Path:
    f = tmp_path / "fp_exclusions.py"
    f.write_text(_FP_EXCLUSIONS_SKELETON, encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# _collect_fp_examples
# ---------------------------------------------------------------------------

class TestCollectFpExamples:
    def test_collects_lines_from_fp_files(self, corpus_dir: Path) -> None:
        examples = _collect_fp_examples(corpus_dir, check_id=None)
        assert len(examples) > 0

    def test_filters_by_check_id(self, corpus_dir: Path) -> None:
        examples = _collect_fp_examples(corpus_dir, check_id="sql-injection")
        assert all(ex["check_id"] == "sql-injection" for ex in examples)

    def test_unknown_check_id_returns_empty(self, corpus_dir: Path) -> None:
        examples = _collect_fp_examples(corpus_dir, check_id="nonexistent-check")
        assert examples == []

    def test_skips_comment_lines(self, corpus_dir: Path) -> None:
        examples = _collect_fp_examples(corpus_dir, check_id=None)
        for ex in examples:
            assert not ex["line"].startswith("#")

    def test_max_20_examples(self, tmp_path: Path) -> None:
        d = tmp_path / "big_corpus"
        d.mkdir()
        # Create a large FP file
        lines = "\n".join(f"    result_{i} = safe_func_{i}()" for i in range(50))
        content = textwrap.dedent(f'''\
            """
            corpus_labels:
              sql-injection: 0
            """
            {lines}
        ''')
        (d / "big_fp.py").write_text(content)
        examples = _collect_fp_examples(d, check_id="sql-injection")
        assert len(examples) <= 20


# ---------------------------------------------------------------------------
# _apply_pattern_to_exclusions + _revert_file
# ---------------------------------------------------------------------------

class TestApplyAndRevert:
    def test_pattern_inserted_in_correct_block(self, fp_exclusions_file: Path) -> None:
        original = _apply_pattern_to_exclusions(
            fp_exclusions_file, "sql-injection", r"\bparameterized\b"
        )
        content = fp_exclusions_file.read_text()
        assert r"\bparameterized\b" in content

    def test_pattern_not_in_wrong_block(self, fp_exclusions_file: Path) -> None:
        _apply_pattern_to_exclusions(fp_exclusions_file, "sql-injection", r"\bunique_token\b")
        content = fp_exclusions_file.read_text()
        # Should be in sql-injection block, not xss block
        sql_block_end = content.index('"xss"')
        assert r"\bunique_token\b" in content[:sql_block_end]

    def test_revert_restores_original(self, fp_exclusions_file: Path) -> None:
        original_content = fp_exclusions_file.read_text()
        saved = _apply_pattern_to_exclusions(fp_exclusions_file, "xss", r"\bsafe_render\b")
        assert fp_exclusions_file.read_text() != original_content
        _revert_file(fp_exclusions_file, saved)
        assert fp_exclusions_file.read_text() == original_content

    def test_raises_for_unknown_check(self, fp_exclusions_file: Path) -> None:
        with pytest.raises(ValueError, match="not found"):
            _apply_pattern_to_exclusions(fp_exclusions_file, "unknown-check", r"\bfoo\b")

    def test_pattern_written_as_raw_string(self, fp_exclusions_file: Path) -> None:
        _apply_pattern_to_exclusions(fp_exclusions_file, "xss", r"\bsafe_func\s*\(")
        content = fp_exclusions_file.read_text()
        # raw string — backslashes NOT double-escaped
        assert r'\bsafe_func\s*\(' in content


# ---------------------------------------------------------------------------
# _make_demo_pattern
# ---------------------------------------------------------------------------

class TestMakeDemoPattern:
    def test_returns_string(self) -> None:
        examples = [{"line": "pool.execute(query, params)", "check_id": "sql-injection"}]
        pattern = _make_demo_pattern("sql-injection", examples)
        assert isinstance(pattern, str)
        assert len(pattern) > 0

    def test_uses_common_identifier(self) -> None:
        examples = [
            {"line": "asyncpg.fetch(query, params)", "check_id": "sql-injection"},
            {"line": "asyncpg.execute(query, params)", "check_id": "sql-injection"},
            {"line": "asyncpg.fetchrow(query, params)", "check_id": "sql-injection"},
        ]
        pattern = _make_demo_pattern("sql-injection", examples)
        # Most frequent identifier — wrapped in \b word-boundary markers
        assert pattern.startswith(r"\b") and pattern.endswith(r"\b")

    def test_fallback_when_no_identifiers(self) -> None:
        examples = [{"line": "123", "check_id": "sql-injection"}]
        pattern = _make_demo_pattern("sql-injection", examples)
        assert "sql-injection" in pattern or len(pattern) > 0


# ---------------------------------------------------------------------------
# _get_check_f1
# ---------------------------------------------------------------------------

class TestGetCheckF1:
    def _make_result(self, metrics: dict) -> MagicMock:
        from warden.validation.corpus.runner import CheckMetrics, CorpusResult
        result = MagicMock(spec=CorpusResult)
        result.metrics = {
            cid: CheckMetrics(check_id=cid, tp=m[0], fp=m[1], fn=m[2], tn=m[3])
            for cid, m in metrics.items()
        }
        result.overall_f1 = sum(
            CheckMetrics(check_id=cid, tp=m[0], fp=m[1], fn=m[2], tn=m[3]).f1
            for cid, m in metrics.items()
        ) / len(metrics)
        return result

    def test_returns_check_f1_when_check_given(self) -> None:
        result = self._make_result({"sql-injection": (3, 0, 0, 7), "xss": (1, 1, 0, 3)})
        assert _get_check_f1(result, "sql-injection") == pytest.approx(1.0)

    def test_returns_overall_f1_when_no_check(self) -> None:
        result = self._make_result({"sql-injection": (3, 0, 0, 7)})
        f1 = _get_check_f1(result, None)
        assert 0.0 <= f1 <= 1.0

    def test_returns_overall_f1_when_check_not_in_metrics(self) -> None:
        result = self._make_result({"sql-injection": (3, 0, 0, 7)})
        f1 = _get_check_f1(result, "nonexistent")
        assert f1 == result.overall_f1


# ---------------------------------------------------------------------------
# _snapshot_file
# ---------------------------------------------------------------------------

class TestSnapshotFile:
    def test_returns_sha256_hex(self, tmp_path: Path) -> None:
        f = tmp_path / "test.py"
        f.write_text("hello")
        digest = _snapshot_file(f)
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_different_content_different_digest(self, tmp_path: Path) -> None:
        f = tmp_path / "test.py"
        f.write_text("hello")
        d1 = _snapshot_file(f)
        f.write_text("world")
        d2 = _snapshot_file(f)
        assert d1 != d2

    def test_same_content_same_digest(self, tmp_path: Path) -> None:
        f = tmp_path / "test.py"
        f.write_text("hello")
        assert _snapshot_file(f) == _snapshot_file(f)


# ---------------------------------------------------------------------------
# CLI dry-run: no file modification
# ---------------------------------------------------------------------------

class TestAutoimproveCliDryRun:
    def test_dry_run_does_not_modify_fp_exclusions(self, corpus_dir: Path, fp_exclusions_file: Path, monkeypatch) -> None:
        """--dry-run must not touch fp_exclusions.py."""
        import warden.cli.commands.rules as rules_mod

        original = fp_exclusions_file.read_text()
        monkeypatch.setattr(rules_mod, "_resolve_fp_exclusions_path", lambda: fp_exclusions_file)

        # Simulate a corpus with FP (fp=1 for sql-injection) so loop has something to do
        from warden.validation.corpus.runner import CheckMetrics, CorpusResult
        mock_result = CorpusResult()
        mock_result.files_scanned = 5
        mock_result.metrics = {
            "sql-injection": CheckMetrics("sql-injection", tp=2, fp=1, fn=0, tn=5),
        }

        import asyncio

        async def fake_corpus_eval(*a, **kw):
            return mock_result

        monkeypatch.setattr(rules_mod, "_run_corpus_eval", fake_corpus_eval)

        asyncio.run(rules_mod._autoimprove_loop(
            corpus_dir=corpus_dir,
            fp_exclusions_file=fp_exclusions_file,
            check_id="sql-injection",
            iterations=1,
            min_improvement=0.005,
            dry_run=True,
            fast=True,
            llm_service=None,
        ))

        assert fp_exclusions_file.read_text() == original
