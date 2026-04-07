"""
Tests for CorpusRunner and corpus label parsing.

Validates:
1. corpus_labels: metadata parsing from docstrings
2. Filename-based label inference (_tp / _fp / clean_)
3. CorpusRunner metric computation (TP/FP/FN/TN → F1)
4. Integration: real corpus files produce expected FP rates
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from warden.validation.corpus.runner import (
    CheckMetrics,
    CorpusRunner,
    _infer_labels_from_filename,
    parse_corpus_labels,
)
from warden.validation.domain.frame import CodeFile, Finding, FrameResult


# ─── parse_corpus_labels ──────────────────────────────────────────────────────


def test_parse_single_label():
    content = '''
"""
corpus_labels:
  sql-injection: 2
"""
'''
    assert parse_corpus_labels(content) == {"sql-injection": 2}


def test_parse_multiple_labels():
    content = '''
"""
Some description.

corpus_labels:
  sql-injection: 3
  xss: 0
  hardcoded-password: 1
"""
'''
    labels = parse_corpus_labels(content)
    assert labels == {"sql-injection": 3, "xss": 0, "hardcoded-password": 1}


def test_parse_no_labels_returns_empty():
    content = '"""Just a regular docstring with no corpus labels."""'
    assert parse_corpus_labels(content) == {}


def test_parse_js_style_comment():
    content = """/**
 * corpus_labels:
 *   xss: 2
 */"""
    # JS comments use * prefix — our regex won't match, returns empty (filename inference used)
    result = parse_corpus_labels(content)
    assert isinstance(result, dict)


def test_parse_zero_expected():
    content = '''"""
corpus_labels:
  sql-injection: 0
  xss: 0
"""'''
    labels = parse_corpus_labels(content)
    assert labels["sql-injection"] == 0
    assert labels["xss"] == 0


# ─── _infer_labels_from_filename ──────────────────────────────────────────────


def test_infer_tp_suffix():
    path = Path("python_sqli_tp.py")
    check_ids = ["sql-injection", "xss"]
    labels = _infer_labels_from_filename(path, check_ids)
    assert labels == {"sql-injection": 1, "xss": 1}


def test_infer_fp_suffix():
    path = Path("python_xss_fp.py")
    check_ids = ["sql-injection", "xss"]
    labels = _infer_labels_from_filename(path, check_ids)
    assert labels == {"sql-injection": 0, "xss": 0}


def test_infer_clean_prefix():
    path = Path("clean_python.py")
    check_ids = ["hardcoded-password"]
    labels = _infer_labels_from_filename(path, check_ids)
    assert labels == {"hardcoded-password": 0}


def test_infer_unknown_filename_returns_none():
    path = Path("some_random_file.py")
    result = _infer_labels_from_filename(path, ["sql-injection"])
    assert result is None


# ─── CheckMetrics ─────────────────────────────────────────────────────────────


def test_metrics_perfect_precision_recall():
    m = CheckMetrics(check_id="sql-injection", tp=5, fp=0, fn=0, tn=5)
    assert m.precision == 1.0
    assert m.recall == 1.0
    assert m.f1 == 1.0
    assert m.fp_rate == 0.0


def test_metrics_all_false_positives():
    m = CheckMetrics(check_id="xss", tp=0, fp=5, fn=0, tn=0)
    assert m.precision == 0.0
    assert m.fp_rate == 1.0
    assert m.f1 == 0.0


def test_metrics_partial():
    # TP=3, FP=1, FN=1, TN=2
    m = CheckMetrics(check_id="test", tp=3, fp=1, fn=1, tn=2)
    assert m.precision == pytest.approx(3 / 4, abs=1e-4)
    assert m.recall == pytest.approx(3 / 4, abs=1e-4)
    assert m.f1 == pytest.approx(0.75, abs=1e-4)


def test_metrics_no_denom_returns_safe_defaults():
    m = CheckMetrics(check_id="empty")
    assert m.precision == 1.0
    assert m.recall == 1.0
    assert m.f1 == 1.0
    assert m.fp_rate == 0.0


# ─── CorpusRunner (mocked frame) ──────────────────────────────────────────────


def _make_finding(check_id: str) -> Finding:
    return Finding(
        id=f"security-{check_id}-0",
        severity="critical",
        message=f"Finding for {check_id}",
        location="file.py:1",
        detection_source="pattern",
    )


def _make_frame_result(findings: list[Finding]) -> FrameResult:
    result = MagicMock(spec=FrameResult)
    result.findings = findings
    return result


@pytest.mark.asyncio
async def test_runner_tp_file_all_found(tmp_path: Path):
    """TP file: scanner flags all expected → TP count correct, FN=0."""
    corpus_file = tmp_path / "vuln_tp.py"
    corpus_file.write_text('''"""
corpus_labels:
  sql-injection: 2
"""
q = f"SELECT * FROM users WHERE id = {uid}"
q2 = "SELECT * FROM items WHERE name = '" + name + "'"
''')

    mock_frame = MagicMock()
    mock_frame.execute_async = AsyncMock(
        return_value=_make_frame_result([
            _make_finding("sql-injection"),
            _make_finding("sql-injection"),
        ])
    )

    runner = CorpusRunner(tmp_path, mock_frame)
    result = await runner.evaluate(check_id="sql-injection")

    m = result.metrics["sql-injection"]
    assert m.tp == 2
    assert m.fn == 0
    assert m.fp == 0
    assert m.f1 == 1.0


@pytest.mark.asyncio
async def test_runner_fp_file_scanner_silent(tmp_path: Path):
    """FP file: scanner produces 0 findings → TN incremented."""
    corpus_file = tmp_path / "safe_fp.py"
    corpus_file.write_text('''"""
corpus_labels:
  sql-injection: 0
"""
return await pool.fetch(query, *params)
''')

    mock_frame = MagicMock()
    mock_frame.execute_async = AsyncMock(
        return_value=_make_frame_result([])
    )

    runner = CorpusRunner(tmp_path, mock_frame)
    result = await runner.evaluate(check_id="sql-injection")

    m = result.metrics["sql-injection"]
    assert m.fp == 0
    assert m.tn == 1
    assert result.files_scanned == 1


@pytest.mark.asyncio
async def test_runner_fp_file_scanner_fires_fp(tmp_path: Path):
    """FP file: scanner wrongly fires → FP incremented."""
    corpus_file = tmp_path / "safe_fp.py"
    corpus_file.write_text('''"""
corpus_labels:
  sql-injection: 0
"""
return await pool.fetch(query, *params)
''')

    mock_frame = MagicMock()
    mock_frame.execute_async = AsyncMock(
        return_value=_make_frame_result([_make_finding("sql-injection")])
    )

    runner = CorpusRunner(tmp_path, mock_frame)
    result = await runner.evaluate(check_id="sql-injection")

    m = result.metrics["sql-injection"]
    assert m.fp == 1
    assert m.tn == 0


@pytest.mark.asyncio
async def test_runner_tp_file_scanner_misses_fn(tmp_path: Path):
    """TP file: scanner misses expected finding → FN incremented."""
    corpus_file = tmp_path / "vuln_tp.py"
    corpus_file.write_text('''"""
corpus_labels:
  sql-injection: 2
"""
# Two injections but scanner only finds one
''')

    mock_frame = MagicMock()
    mock_frame.execute_async = AsyncMock(
        return_value=_make_frame_result([_make_finding("sql-injection")])
    )

    runner = CorpusRunner(tmp_path, mock_frame)
    result = await runner.evaluate(check_id="sql-injection")

    m = result.metrics["sql-injection"]
    assert m.tp == 1
    assert m.fn == 1


@pytest.mark.asyncio
async def test_runner_no_labeled_files_returns_zero_scanned(tmp_path: Path):
    """No labeled files → files_scanned=0."""
    (tmp_path / "unlabeled.py").write_text("x = 1\n")

    mock_frame = MagicMock()
    mock_frame.execute_async = AsyncMock(return_value=_make_frame_result([]))

    runner = CorpusRunner(tmp_path, mock_frame)
    result = await runner.evaluate()
    assert result.files_scanned == 0


# ─── Integration: real corpus files ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_real_corpus_sqli_fp_produces_zero_findings():
    """verify/corpus/python_sqli_fp.py must produce 0 sql-injection findings."""
    corpus_dir = Path("verify/corpus")
    if not corpus_dir.exists():
        pytest.skip("verify/corpus not found — run from repo root")

    from warden.validation.frames.security.security_frame import SecurityFrame

    runner = CorpusRunner(corpus_dir, SecurityFrame())
    result = await runner.evaluate(check_id="sql-injection")

    fp_files_scanned = result.files_scanned
    assert fp_files_scanned > 0, "No corpus files were scanned"

    m = result.metrics.get("sql-injection")
    assert m is not None
    # FP rate on _fp files: we expect 0
    assert m.fp == 0, (
        f"sql-injection check wrongly flagged {m.fp} findings in FP corpus files"
    )


@pytest.mark.asyncio
async def test_real_corpus_xss_fp_produces_zero_findings():
    """verify/corpus/python_xss_fp.py must produce 0 xss findings."""
    corpus_dir = Path("verify/corpus")
    if not corpus_dir.exists():
        pytest.skip("verify/corpus not found — run from repo root")

    from warden.validation.frames.security.security_frame import SecurityFrame

    runner = CorpusRunner(corpus_dir, SecurityFrame())
    result = await runner.evaluate(check_id="xss")

    m = result.metrics.get("xss")
    assert m is not None
    assert m.fp == 0, (
        f"xss check wrongly flagged {m.fp} findings in FP corpus files"
    )
