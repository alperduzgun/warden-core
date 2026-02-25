"""
AsyncRaceFrame — detects ASYNC_RACE contract violations via AST + LLM.

An ASYNC_RACE occurs when asyncio.gather() or asyncio.create_task() is used
to run coroutines in parallel, but those coroutines share and mutate a mutable
object (e.g. context.findings) without protection by asyncio.Lock or similar.

Detection algorithm (per-file):
1. AST: find functions containing asyncio.gather() or asyncio.create_task()
2. In the same function: look for shared mutable object access patterns
   (captured variable mutations in task closures)
3. Check for Lock usage: asyncio.Lock(), asyncio.Semaphore, async with lock
4. If gather + shared mutable + no lock → build code context → LLM verify
5. LLM confidence >= 0.5 → ASYNC_RACE [high]

This frame is ONLY active when contract_mode=True (opt-in).
LLM is required for the verdict step (without LLM, candidates are skipped).
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
)
from warden.validation.domain.frame import (
    CodeFile,
    Finding,
    FrameResult,
    ValidationFrame,
)

if TYPE_CHECKING:
    from warden.pipeline.domain.pipeline_context import PipelineContext

# Names that signal parallel async execution
_GATHER_CALLS = frozenset({"gather", "create_task", "ensure_future"})

# Names that signal lock usage
_LOCK_NAMES = frozenset({"Lock", "RLock", "Semaphore", "asyncio.Lock", "asyncio.Semaphore"})

# Common shared mutable object name patterns
_SHARED_PATTERNS = frozenset(
    {
        "context",
        "results",
        "findings",
        "output",
        "errors",
        "collected",
        "items",
        "data",
        "accumulator",
        "sink",
    }
)

# LLM confidence threshold for reporting
_CONFIDENCE_THRESHOLD = 0.5

# Max candidates per file
_MAX_CANDIDATES_PER_FILE = 5


@dataclass
class GatherCandidate:
    """A gather call site suspected of being an async race condition."""

    func_name: str
    file_path: str
    gather_line: int
    shared_vars: list[str]
    has_lock: bool
    code_snippet: str


class AsyncRaceFrame(ValidationFrame):
    """
    Detects ASYNC_RACE contract violations.

    Scans per-file for asyncio.gather/create_task patterns with shared
    mutable access but no Lock protection. LLM verifies if it's a real race.

    This frame:
    - Requires no DDG injection (AST-only AST scan + LLM)
    - Operates per-file (unlike DeadDataFrame/StaleSyncFrame)
    - LLM required for verdict (without LLM, candidates skipped)
    - is_blocker=False (informational, v2.5.0 feature)
    """

    name: str = "Async Race Detector"
    description: str = "Detects ASYNC_RACE: asyncio.gather with shared mutable access and no Lock"
    category: FrameCategory = FrameCategory.LANGUAGE_SPECIFIC
    priority: FramePriority = FramePriority.MEDIUM
    scope: FrameScope = FrameScope.FILE_LEVEL
    is_blocker: bool = False
    supports_verification: bool = False

    @property
    def frame_id(self) -> str:
        return "async_race"

    async def execute_async(self, code_file: CodeFile, context: PipelineContext | None = None) -> FrameResult:  # noqa: ARG002
        """
        Scan a single file for async race condition candidates.

        Steps:
        1. Parse AST — find gather/create_task calls
        2. Identify shared mutable variables in task closures
        3. Check for Lock usage in the same function
        4. Ask LLM to verify candidates
        5. Return ASYNC_RACE findings for confirmed cases
        """
        start = time.monotonic()

        # Only analyze Python files
        if code_file.language not in ("python", "py", ""):
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=time.monotonic() - start,
                issues_found=0,
                is_blocker=self.is_blocker,
                findings=[],
                metadata={"skipped": True, "reason": "non_python_file"},
            )

        if not code_file.content or not code_file.content.strip():
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=time.monotonic() - start,
                issues_found=0,
                is_blocker=self.is_blocker,
                findings=[],
                metadata={"skipped": True, "reason": "empty_file"},
            )

        # Step 1: AST scan
        try:
            tree = ast.parse(code_file.content, filename=code_file.path)
        except SyntaxError:
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=time.monotonic() - start,
                issues_found=0,
                is_blocker=self.is_blocker,
                findings=[],
                metadata={"skipped": True, "reason": "syntax_error"},
            )

        candidates = self._extract_candidates(tree, code_file)
        if not candidates:
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=time.monotonic() - start,
                issues_found=0,
                is_blocker=self.is_blocker,
                findings=[],
                metadata={"candidates_found": 0},
            )

        # Step 2: LLM verify candidates
        finding_objects: list[Finding] = []
        llm_available = self._has_llm_service()

        for candidate in candidates[:_MAX_CANDIDATES_PER_FILE]:
            if candidate.has_lock:
                # Already has a lock — skip LLM, no finding
                continue

            verdict_info = await self._get_llm_verdict(candidate, llm_available)
            if (
                verdict_info.get("verdict") == "async_race"
                and verdict_info.get("confidence", 0.0) >= _CONFIDENCE_THRESHOLD
            ):
                finding_objects.append(self._make_finding(candidate, verdict_info))

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="failed" if finding_objects else "passed",
            duration=time.monotonic() - start,
            issues_found=len(finding_objects),
            is_blocker=self.is_blocker,
            findings=finding_objects,
            metadata={
                "gap_type": "ASYNC_RACE",
                "candidates_found": len(candidates),
                "llm_available": llm_available,
            },
        )

    # -------------------------------------------------------------------------
    # AST scanning
    # -------------------------------------------------------------------------

    def _extract_candidates(self, tree: ast.AST, code_file: CodeFile) -> list[GatherCandidate]:
        """Scan the AST for gather call sites with potential race conditions."""
        candidates: list[GatherCandidate] = []
        lines = code_file.content.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            gather_lines = self._find_gather_calls(node)
            if not gather_lines:
                continue

            has_lock = self._has_lock_usage(node)
            shared_vars = self._find_shared_mutable_vars(node)

            if not shared_vars and has_lock:
                continue  # Protected and clean

            for gather_line in gather_lines:
                snippet = self._extract_snippet(lines, gather_line - 1, context=5)
                candidates.append(
                    GatherCandidate(
                        func_name=node.name,
                        file_path=code_file.path,
                        gather_line=gather_line,
                        shared_vars=shared_vars,
                        has_lock=has_lock,
                        code_snippet=snippet,
                    )
                )

        return candidates

    def _find_gather_calls(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[int]:
        """Find line numbers of asyncio.gather() or create_task() calls in a function."""
        lines: list[int] = []
        for node in ast.walk(func_node):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            call_name = ""
            if isinstance(func, ast.Attribute):
                call_name = func.attr
            elif isinstance(func, ast.Name):
                call_name = func.id
            if call_name in _GATHER_CALLS and hasattr(node, "lineno"):
                lines.append(node.lineno)
        return lines

    def _has_lock_usage(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Check if the function uses asyncio.Lock, Semaphore, or 'async with'."""
        for node in ast.walk(func_node):
            # async with lock: pattern
            if isinstance(node, ast.AsyncWith):
                return True
            # Lock/Semaphore instantiation
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in _LOCK_NAMES:
                    return True
                if isinstance(func, ast.Name) and func.id in _LOCK_NAMES:
                    return True
        return False

    def _find_shared_mutable_vars(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        """
        Find variables that look like shared mutable state accessed in the function.

        Heuristic: look for Name nodes with patterns typical of shared accumulators
        that appear in both task definitions and the outer function body.
        """
        shared: set[str] = set()
        for node in ast.walk(func_node):
            if isinstance(node, ast.Name) and node.id in _SHARED_PATTERNS:
                shared.add(node.id)
            # context.X access pattern
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id in _SHARED_PATTERNS:
                    shared.add(f"{node.value.id}.{node.attr}")
        return sorted(shared)

    @staticmethod
    def _extract_snippet(lines: list[str], center_line: int, context: int = 5) -> str:
        """Extract a code snippet around a line (0-indexed center_line)."""
        start = max(0, center_line - context)
        end = min(len(lines), center_line + context + 1)
        numbered = [f"{start + i + 1}: {line}" for i, line in enumerate(lines[start:end])]
        return "\n".join(numbered)

    # -------------------------------------------------------------------------
    # LLM integration
    # -------------------------------------------------------------------------

    def _has_llm_service(self) -> bool:
        return bool(getattr(self, "llm_service", None))

    async def _get_llm_verdict(self, candidate: GatherCandidate, llm_available: bool) -> dict[str, Any]:
        """Ask LLM if this gather pattern is an async race condition."""
        if not llm_available:
            return {"verdict": "unclear", "confidence": 0.0, "reasoning": "LLM not available"}

        shared_str = ", ".join(candidate.shared_vars) if candidate.shared_vars else "(none detected)"
        prompt = f"""You are a Python concurrency expert reviewing code for async race conditions.

[CODE CONTEXT]
File: {candidate.file_path}
Function: {candidate.func_name} (line {candidate.gather_line})

```python
{candidate.code_snippet}
```

[ANALYSIS REQUEST]
This function uses asyncio.gather() or asyncio.create_task() to run coroutines in parallel.
Suspected shared mutable variables accessed across tasks: {shared_str}
Lock/Semaphore detected: {candidate.has_lock}

Is this an ASYNC_RACE condition? An async race occurs when:
- Multiple coroutines share a mutable object (list, dict, object with writable attributes)
- The coroutines mutate the shared object concurrently without a Lock
- This can cause data loss, corruption, or inconsistent state

Respond with ONLY a JSON object:
{{
  "verdict": "async_race" | "safe" | "unclear",
  "confidence": 0.0,
  "reasoning": "one sentence"
}}

Where:
- "async_race": there is a real concurrency bug here (report if confidence >= 0.5)
- "safe": the code is safe (protected by lock/semaphore, or no actual shared mutation)
- "unclear": cannot determine from this snippet alone"""

        try:
            response = await self.llm_service.complete_async(  # type: ignore[attr-defined]
                prompt=prompt,
                system_prompt=(
                    "You are a Python concurrency expert. Respond only with a JSON object. "
                    "No markdown, no code blocks, no extra text."
                ),
                use_fast_tier=False,
            )
            raw = response.content if hasattr(response, "content") else str(response)
            return self._parse_verdict(raw)
        except Exception:
            return {"verdict": "unclear", "confidence": 0.0, "reasoning": "LLM call failed"}

    def _parse_verdict(self, raw: str) -> dict[str, Any]:
        """Parse LLM JSON verdict response."""
        import json

        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

            data = json.loads(cleaned)
            verdict = data.get("verdict", "unclear")
            confidence = float(data.get("confidence", 0.0))
            reasoning = str(data.get("reasoning", ""))

            if verdict not in ("async_race", "safe", "unclear"):
                verdict = "unclear"
            confidence = max(0.0, min(1.0, confidence))
            return {"verdict": verdict, "confidence": confidence, "reasoning": reasoning}
        except (json.JSONDecodeError, ValueError, TypeError):
            return {"verdict": "unclear", "confidence": 0.0, "reasoning": f"parse_error: {raw[:80]}"}

    # -------------------------------------------------------------------------
    # Finding construction
    # -------------------------------------------------------------------------

    def _make_finding(self, candidate: GatherCandidate, verdict_info: dict[str, Any]) -> Finding:
        """Create an ASYNC_RACE Finding."""
        confidence = verdict_info.get("confidence", 0.0)
        reasoning = verdict_info.get("reasoning", "")
        shared_str = ", ".join(candidate.shared_vars[:5]) or "(unspecified)"
        safe_func = candidate.func_name.upper().replace("_", "-")
        finding_id = f"CONTRACT-ASYNC-RACE-{safe_func}"

        message = (
            f"[ASYNC_RACE] asyncio.gather/create_task in '{candidate.func_name}' "
            f"accesses shared mutable object(s) [{shared_str}] without asyncio.Lock "
            f"(LLM confidence: {confidence:.2f})"
        )

        detail = (
            f"Function: {candidate.func_name}\n"
            f"File: {candidate.file_path}:{candidate.gather_line}\n"
            f"Shared variables: {shared_str}\n"
            f"Lock detected: {candidate.has_lock}\n"
            f"LLM reasoning: {reasoning}\n"
            f"Fix: Protect shared mutable access with asyncio.Lock or use thread-safe"
            f" alternatives (e.g., asyncio.Queue, atomic operations)"
        )

        return Finding(
            id=finding_id,
            severity="high",
            message=message,
            location=f"{candidate.file_path}:{candidate.gather_line}",
            detail=detail,
            line=candidate.gather_line,
            is_blocker=False,
        )
