"""
Tests for AsyncRaceFrame.

Tests cover:
- Non-python file → skip
- Empty file → skip
- Syntax error → skip
- No gather calls → no candidates
- gather with Lock → has_lock=True → no finding (even without LLM)
- gather without Lock + shared vars → candidate
- LLM not available → 0 findings (graceful)
- LLM returns async_race + confidence >= 0.5 → finding
- LLM returns safe → no finding
- LLM returns unclear → no finding
- LLM exception → graceful degradation
- Finding structure and metadata
- _parse_verdict edge cases
- frame_executor.py known candidate detection
"""

from __future__ import annotations

import json
import textwrap
from unittest.mock import AsyncMock, MagicMock

import pytest

from warden.validation.domain.frame import CodeFile
from warden.validation.frames.async_race.async_race_frame import (
    AsyncRaceFrame,
    GatherCandidate,
    _CONFIDENCE_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_code_file(content: str = "", path: str = "test.py", language: str = "python") -> CodeFile:
    return CodeFile(path=path, content=content, language=language)


_GATHER_WITHOUT_LOCK = textwrap.dedent("""
    import asyncio

    async def run_parallel(context, frames):
        async def execute(frame):
            result = await frame.execute(context)
            context.findings.extend(result.findings)

        tasks = [execute(f) for f in frames]
        await asyncio.gather(*tasks)
""")

_GATHER_WITH_ASYNC_WITH = textwrap.dedent("""
    import asyncio

    async def run_parallel(context, frames):
        lock = asyncio.Lock()

        async def execute(frame):
            result = await frame.execute(context)
            async with lock:
                context.findings.extend(result.findings)

        tasks = [execute(f) for f in frames]
        await asyncio.gather(*tasks)
""")

_GATHER_WITH_SEMAPHORE = textwrap.dedent("""
    import asyncio

    async def run_parallel(context, frames):
        sem = asyncio.Semaphore(3)

        async def execute(frame):
            async with sem:
                await frame.execute(context)

        tasks = [execute(f) for f in frames]
        await asyncio.gather(*tasks)
""")

_NO_GATHER = textwrap.dedent("""
    async def run_sequential(context, frames):
        for frame in frames:
            result = await frame.execute(context)
            context.findings.extend(result.findings)
""")

_CREATE_TASK_PATTERN = textwrap.dedent("""
    import asyncio

    async def run_tasks(results):
        async def worker(item):
            results.append(await process(item))

        task = asyncio.create_task(worker(1))
        await task
""")


def _make_mock_llm(verdict: str, confidence: float, reasoning: str = "test") -> MagicMock:
    response = MagicMock()
    response.content = json.dumps({"verdict": verdict, "confidence": confidence, "reasoning": reasoning})
    mock_llm = AsyncMock()
    mock_llm.complete_async = AsyncMock(return_value=response)
    return mock_llm


# ---------------------------------------------------------------------------
# Unit: _parse_verdict
# ---------------------------------------------------------------------------


class TestParseVerdict:
    def test_valid_async_race(self):
        frame = AsyncRaceFrame()
        raw = '{"verdict": "async_race", "confidence": 0.8, "reasoning": "shared list mutation"}'
        result = frame._parse_verdict(raw)
        assert result["verdict"] == "async_race"
        assert result["confidence"] == pytest.approx(0.8)

    def test_valid_safe(self):
        frame = AsyncRaceFrame()
        raw = '{"verdict": "safe", "confidence": 0.9, "reasoning": "protected by lock"}'
        result = frame._parse_verdict(raw)
        assert result["verdict"] == "safe"

    def test_invalid_verdict_normalized_to_unclear(self):
        frame = AsyncRaceFrame()
        raw = '{"verdict": "dangerous", "confidence": 0.9}'
        result = frame._parse_verdict(raw)
        assert result["verdict"] == "unclear"

    def test_json_parse_error_returns_unclear(self):
        frame = AsyncRaceFrame()
        result = frame._parse_verdict("not json {{{")
        assert result["verdict"] == "unclear"
        assert result["confidence"] == 0.0

    def test_confidence_clamped(self):
        frame = AsyncRaceFrame()
        raw = '{"verdict": "async_race", "confidence": 5.0}'
        result = frame._parse_verdict(raw)
        assert result["confidence"] == 1.0

    def test_strips_code_fence(self):
        frame = AsyncRaceFrame()
        raw = '```json\n{"verdict": "async_race", "confidence": 0.7, "reasoning": "ok"}\n```'
        result = frame._parse_verdict(raw)
        assert result["verdict"] == "async_race"


# ---------------------------------------------------------------------------
# Unit: AST scanning helpers
# ---------------------------------------------------------------------------


class TestASTScanning:
    def test_find_gather_calls(self):
        import ast

        frame = AsyncRaceFrame()
        tree = ast.parse(_GATHER_WITHOUT_LOCK)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run_parallel":
                lines = frame._find_gather_calls(node)
                assert len(lines) >= 1
                break

    def test_has_lock_usage_with_async_with(self):
        import ast

        frame = AsyncRaceFrame()
        tree = ast.parse(_GATHER_WITH_ASYNC_WITH)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run_parallel":
                assert frame._has_lock_usage(node) is True
                break

    def test_no_lock_without_async_with(self):
        import ast

        frame = AsyncRaceFrame()
        tree = ast.parse(_GATHER_WITHOUT_LOCK)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run_parallel":
                assert frame._has_lock_usage(node) is False
                break

    def test_find_shared_mutable_vars_context(self):
        import ast

        frame = AsyncRaceFrame()
        tree = ast.parse(_GATHER_WITHOUT_LOCK)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run_parallel":
                shared = frame._find_shared_mutable_vars(node)
                assert any("context" in v for v in shared)
                break

    def test_extract_candidates_gather_without_lock(self):
        frame = AsyncRaceFrame()
        code_file = _make_code_file(_GATHER_WITHOUT_LOCK)
        import ast

        tree = ast.parse(_GATHER_WITHOUT_LOCK)
        candidates = frame._extract_candidates(tree, code_file)
        assert len(candidates) >= 1
        assert candidates[0].func_name == "run_parallel"
        assert candidates[0].has_lock is False

    def test_extract_candidates_gather_with_lock_skipped(self):
        frame = AsyncRaceFrame()
        code_file = _make_code_file(_GATHER_WITH_ASYNC_WITH)
        import ast

        tree = ast.parse(_GATHER_WITH_ASYNC_WITH)
        candidates = frame._extract_candidates(tree, code_file)
        # async with → has_lock=True → still a candidate, but _get_llm_verdict skipped
        # The frame should return no findings for locked patterns
        assert all(c.has_lock for c in candidates)

    def test_no_gather_no_candidates(self):
        frame = AsyncRaceFrame()
        code_file = _make_code_file(_NO_GATHER)
        import ast

        tree = ast.parse(_NO_GATHER)
        candidates = frame._extract_candidates(tree, code_file)
        assert len(candidates) == 0

    def test_create_task_detected(self):
        frame = AsyncRaceFrame()
        code_file = _make_code_file(_CREATE_TASK_PATTERN)
        import ast

        tree = ast.parse(_CREATE_TASK_PATTERN)
        candidates = frame._extract_candidates(tree, code_file)
        assert len(candidates) >= 1


# ---------------------------------------------------------------------------
# Integration: execute_async
# ---------------------------------------------------------------------------


class TestAsyncRaceFrameExecute:
    @pytest.mark.asyncio
    async def test_non_python_file_skips(self):
        frame = AsyncRaceFrame()
        result = await frame.execute_async(_make_code_file("content", language="javascript"))
        assert result.status == "passed"
        assert result.metadata.get("reason") == "non_python_file"

    @pytest.mark.asyncio
    async def test_empty_file_skips(self):
        frame = AsyncRaceFrame()
        result = await frame.execute_async(_make_code_file(""))
        assert result.status == "passed"
        assert result.metadata.get("reason") == "empty_file"

    @pytest.mark.asyncio
    async def test_syntax_error_skips(self):
        frame = AsyncRaceFrame()
        result = await frame.execute_async(_make_code_file("def broken(:\n    pass"))
        assert result.status == "passed"
        assert result.metadata.get("reason") == "syntax_error"

    @pytest.mark.asyncio
    async def test_no_gather_no_candidates(self):
        frame = AsyncRaceFrame()
        result = await frame.execute_async(_make_code_file(_NO_GATHER))
        assert result.status == "passed"
        assert result.metadata.get("candidates_found") == 0

    @pytest.mark.asyncio
    async def test_gather_with_lock_no_finding(self):
        frame = AsyncRaceFrame()
        frame.llm_service = _make_mock_llm("async_race", 0.9, "would be race without lock")
        result = await frame.execute_async(_make_code_file(_GATHER_WITH_ASYNC_WITH))
        # has_lock=True → skipped in LLM loop
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_gather_without_lock_no_llm_no_finding(self):
        frame = AsyncRaceFrame()
        # No llm_service set
        result = await frame.execute_async(_make_code_file(_GATHER_WITHOUT_LOCK))
        assert result.status == "passed"
        assert result.issues_found == 0
        assert result.metadata.get("llm_available") is False

    @pytest.mark.asyncio
    async def test_llm_async_race_high_confidence_creates_finding(self):
        frame = AsyncRaceFrame()
        frame.llm_service = _make_mock_llm("async_race", 0.85, "shared context mutation")
        result = await frame.execute_async(_make_code_file(_GATHER_WITHOUT_LOCK))
        assert result.status == "failed"
        assert result.issues_found == 1

        finding = result.findings[0]
        assert "ASYNC-RACE" in finding.id
        assert finding.severity == "high"
        assert finding.is_blocker is False
        assert (
            "asyncio" in finding.message.lower()
            or "gather" in finding.message.lower()
            or "race" in finding.message.lower()
        )

    @pytest.mark.asyncio
    async def test_llm_safe_no_finding(self):
        frame = AsyncRaceFrame()
        frame.llm_service = _make_mock_llm("safe", 0.9, "protected by design")
        result = await frame.execute_async(_make_code_file(_GATHER_WITHOUT_LOCK))
        assert result.status == "passed"
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_llm_unclear_no_finding(self):
        frame = AsyncRaceFrame()
        frame.llm_service = _make_mock_llm("unclear", 0.3)
        result = await frame.execute_async(_make_code_file(_GATHER_WITHOUT_LOCK))
        assert result.status == "passed"
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_llm_low_confidence_no_finding(self):
        frame = AsyncRaceFrame()
        frame.llm_service = _make_mock_llm("async_race", _CONFIDENCE_THRESHOLD - 0.01)
        result = await frame.execute_async(_make_code_file(_GATHER_WITHOUT_LOCK))
        assert result.status == "passed"
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_llm_exception_graceful_degradation(self):
        frame = AsyncRaceFrame()
        mock_llm = AsyncMock()
        mock_llm.complete_async = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        frame.llm_service = mock_llm
        result = await frame.execute_async(_make_code_file(_GATHER_WITHOUT_LOCK))
        assert result.status == "passed"
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_finding_structure(self):
        frame = AsyncRaceFrame()
        frame.llm_service = _make_mock_llm("async_race", 0.9, "shared context is mutated")
        result = await frame.execute_async(_make_code_file(_GATHER_WITHOUT_LOCK))

        assert result.issues_found == 1
        finding = result.findings[0]
        assert finding.id.startswith("CONTRACT-ASYNC-RACE-")
        assert finding.severity == "high"
        assert finding.is_blocker is False
        assert "0.90" in finding.message or "0.9" in finding.message
        assert "shared context is mutated" in finding.detail

    @pytest.mark.asyncio
    async def test_frame_properties(self):
        frame = AsyncRaceFrame()
        assert frame.frame_id == "async_race"
        assert frame.is_blocker is False
        assert frame.supports_verification is False

    @pytest.mark.asyncio
    async def test_semaphore_with_async_with_no_finding(self):
        """Semaphore + async with → has_lock=True → skip."""
        frame = AsyncRaceFrame()
        frame.llm_service = _make_mock_llm("async_race", 0.9)
        result = await frame.execute_async(_make_code_file(_GATHER_WITH_SEMAPHORE))
        assert result.issues_found == 0


# ---------------------------------------------------------------------------
# Known candidate: frame_executor.py
# ---------------------------------------------------------------------------


class TestFrameExecutorCandidate:
    @pytest.mark.asyncio
    async def test_frame_executor_detected_as_candidate(self):
        """The actual frame_executor.py asyncio.gather should be detected."""
        from pathlib import Path

        import warden

        warden_src = Path(warden.__file__).parent.parent
        executor_path = warden_src / "warden/pipeline/application/orchestrator/frame_executor.py"

        if not executor_path.exists():
            pytest.skip("frame_executor.py not found")

        content = executor_path.read_text()
        code_file = _make_code_file(content, path=str(executor_path))

        frame = AsyncRaceFrame()
        # Just extract candidates, don't run LLM
        import ast

        tree = ast.parse(content)
        candidates = frame._extract_candidates(tree, code_file)

        # frame_executor.py has asyncio.gather() calls
        assert len(candidates) >= 1
        gather_funcs = {c.func_name for c in candidates}
        # Should detect the parallel execution function
        assert any("parallel" in f or "execute" in f for f in gather_funcs)
