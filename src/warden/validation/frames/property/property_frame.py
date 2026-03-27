"""
Property Frame - Logic validation and invariants.

Validates business logic correctness:
- Function preconditions/postconditions
- Class invariants
- State machine transitions
- Mathematical properties

Priority: HIGH
"""

from __future__ import annotations

import json as _json
import re
import time
from typing import TYPE_CHECKING, Any

from warden.llm.prompts.tool_instructions import get_tool_enhanced_prompt
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.enums import (
    FrameApplicability,
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
from warden.validation.domain.mixins import BatchExecutable

if TYPE_CHECKING:
    from warden.pipeline.domain.pipeline_context import PipelineContext

logger = get_logger(__name__)


class PropertyFrame(ValidationFrame, BatchExecutable):
    """
    Property-based testing validation frame.

    This frame detects logic issues:
    - Missing precondition checks
    - Unvalidated state transitions
    - Invariant violations
    - Missing assertions
    - Logic inconsistencies

    Priority: HIGH
    Applicability: All languages
    """

    # Required metadata
    name = "Property Testing"
    description = "Validates business logic, invariants, and preconditions"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = False
    supports_verification = False  # Code-quality findings, not security risks — security verifier gives wrong verdicts
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]
    minimum_triage_lane: str = "middle_lane"  # Skip FAST files; LLM-heavy frame

    # Property check patterns
    PATTERNS = {
        "division_no_zero_check": {
            "pattern": r"(?:=|return)\s+[\w\.\(\)\[\]]+\s*\/\s*(\w+)(?!\s*(?:if|&&|\|\||\?|assert|\!=?\s*0))",
            "severity": "medium",
            "message": "Division operation without zero check",
            "suggestion": "Check divisor is not zero before division",
        },
        "comparison_always_true": {
            # Match if-true only. while-true is intentional (event loops, retry loops).
            "pattern": r"\bif\s+(?:true|True)\b(?!\s*(?:and|or|\||\&))",
            "severity": "low",
            "message": "Always-true condition detected",
            "suggestion": "Review logic - condition always evaluates to true",
        },
        "negative_index_possible": {
            "pattern": r"\[\s*-?\w+\s*-\s*\w+\s*\]",
            "severity": "medium",
            "message": "Array access with possible negative index",
            "suggestion": "Ensure index is non-negative",
        },
    }

    _SYSTEM_PROMPT_BASE = """You are an expert Formal Verification and Property Testing analyst. Analyze the provided code for logical errors, invariant violations, and precondition failures.

Focus on:
1. Invariant maintenance (class state consistency).
2. Precondition/Postcondition validation (contract violations).
3. Logical fallacies (always true/false conditions, dead code).
4. State machine transitions (illegal states, race conditions).
5. Mathematical properties (division by zero, overflow, precision loss).
6. Mutable-argument mutation in loops: dict.pop() / del / .remove() applied to a shared mutable argument inside a retry or iteration loop modifies the original collection on the first pass — subsequent iterations silently use a different value or fall back to a default.
7. Exception hierarchy gaps: a call site that can raise both ExceptionTypeA and ExceptionTypeB, where only ExceptionTypeA is caught — ExceptionTypeB propagates uncaught and crashes the caller.
8. Inert template-literal syntax: string literals containing "${var}", "{{var}}", or similar substitution markers that are valid in another language but never interpolated in the current one — the variable is never substituted, and the literal string is used as-is.
9. Unbounded concurrent I/O: asyncio.gather / Promise.all / goroutine fan-out with no semaphore or rate-limit, where fan-out count scales with input size, can saturate connections or memory.

KNOWN SAFE PATTERNS — do NOT flag these as issues:
- Python's `contextvars.ContextVar` (PEP 567): This is the official async-safe per-task state mechanism since Python 3.7. It is designed specifically for use in asyncio, FastAPI, Starlette, and other async frameworks. Never flag ContextVar usage as an async safety concern, thread safety issue, or race condition.
- Python f-strings and str.format(): these DO interpolate — never flag them as "inert template syntax".

Output must be a valid JSON object with the following structure:
{
    "score": <0-10 integer, 10 is verified>,
    "confidence": <0.0-1.0 float>,
    "summary": "<brief summary of findings>",
    "issues": [
        {
            "severity": "critical|high|medium|low",
            "category": "logic",
            "title": "<short title>",
            "description": "<detailed description>",
            "line": <line number>,
            "confidence": <0.0-1.0>,
            "evidenceQuote": "<exact code triggering issue>",
            "codeSnippet": "<surrounding code>"
        }
    ]
}"""

    SYSTEM_PROMPT = get_tool_enhanced_prompt(_SYSTEM_PROMPT_BASE)

    BATCH_SIZE = 3  # Conservative for subprocess-based providers (Claude Code)

    BATCH_SYSTEM_PROMPT = """You are an expert Formal Verification and Property Testing analyst. Analyze the provided code files for logical errors, invariant violations, and precondition failures.

Focus on (in addition to standard logic analysis):
- Mutable-argument mutation in loops: dict.pop() / del / .remove() on a shared mutable argument inside a retry or iteration loop modifies the collection on the first pass — subsequent iterations silently use a different value.
- Exception hierarchy gaps: a call site that can raise multiple exception types where only a subset is caught — sibling exceptions propagate uncaught.
- Inert template-literal syntax: "${var}" or "{{var}}" patterns that look like substitution markers but are never interpolated in the current language context.
- Unbounded concurrent I/O: asyncio.gather / Promise.all / goroutine fan-out with no semaphore where fan-out scales with input size.

KNOWN SAFE PATTERNS — do NOT flag these as issues:
- Python's `contextvars.ContextVar` (PEP 567): This is the official async-safe per-task state mechanism since Python 3.7. It is designed specifically for use in asyncio, FastAPI, Starlette, and other async frameworks. Never flag ContextVar usage as an async safety concern, thread safety issue, or race condition.
- Python f-strings and str.format(): these DO interpolate — never flag them as "inert template syntax".

For EACH file, output a JSON object. Return a JSON array where each element corresponds to a file:
[
  {
    "file_idx": 0,
    "score": <0-10 integer>,
    "confidence": <0.0-1.0>,
    "summary": "<brief summary>",
    "issues": [
      {
        "severity": "critical|high|medium|low",
        "category": "logic",
        "title": "<short title>",
        "description": "<detailed description>",
        "line": <line number>,
        "confidence": <0.0-1.0>,
        "evidenceQuote": "<exact code triggering issue>"
      }
    ]
  }
]"""

    # Guard patterns that indicate a division is already protected.
    # Evaluated against the division line itself and up to 2 preceding lines.
    _DIVISION_GUARD_PATTERNS: list[re.Pattern] = [
        # Ternary / inline guard: `… / x if x else …`  or  `result if x else 0`
        re.compile(r"\bif\b.+\belse\b"),
        # Explicit zero-inequality guards: `if x != 0`, `if x > 0`, `if x >= 1`
        re.compile(r"if\s+\w[\w.\[\]()]*\s*(?:!=|>|>=)\s*0"),
        # Truthy guard: `if x:` / `if len(x):` / `if len(x) > 0`
        re.compile(r"if\s+(?:len\s*\()?[\w.\[\]()]+\s*\)?(?:\s*(?:>|>=)\s*\d+)?\s*:"),
        # try/except ZeroDivisionError in surrounding context
        re.compile(r"except\s+ZeroDivisionError"),
        # or-fallback: `x or 1`, `denominator or default`
        re.compile(r"\w[\w.\[\]()]*\s+or\s+\w"),
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize PropertyFrame."""
        super().__init__(config)

        # Pre-compile all patterns once for performance (KISS optimization)
        self._compiled_patterns = {
            check_id: {
                **check_config,
                "compiled": re.compile(check_config["pattern"]),
            }
            for check_id, check_config in self.PATTERNS.items()
        }

        # Pre-compile assertion check patterns
        self._assertion_pattern = re.compile(r"\bassert\b|Assert\.|assertThat")
        self._function_pattern = re.compile(r"def\s+\w+|function\s+\w+|public\s+\w+\s+\w+\(")

    async def execute_batch_async(self, code_files: list[CodeFile], context: Any = None) -> list[FrameResult]:
        """
        Execute property checks on multiple files with batch LLM processing.

        Pattern checks run per-file (fast). LLM analysis batches multiple files
        into a single prompt for subprocess-based providers.

        Falls back to serial execution on batch parse failure.
        """
        if not code_files:
            return []

        batch_start = time.perf_counter()
        logger.info("property_batch_started", file_count=len(code_files))

        # Phase 1: Pattern checks per file (fast, no LLM)
        pattern_findings_map: dict[str, list[Finding]] = {}
        assertion_findings_map: dict[str, list[Finding]] = {}

        for code_file in code_files:
            findings: list[Finding] = []
            for check_id, check_config in self._compiled_patterns.items():
                findings.extend(
                    self._check_pattern_compiled(
                        code_file=code_file,
                        check_id=check_id,
                        compiled_pattern=check_config["compiled"],
                        severity=check_config["severity"],
                        message=check_config["message"],
                        suggestion=check_config.get("suggestion"),
                    )
                )
            pattern_findings_map[code_file.path] = findings
            assertion_findings_map[code_file.path] = self._check_assertions(code_file)

        # Phase 2: Batch LLM analysis (if available)
        llm_findings_map: dict[str, list[Finding]] = {f.path: [] for f in code_files}
        if hasattr(self, "llm_service") and self.llm_service:
            llm_findings_map = await self._batch_llm_analysis(code_files)

        # Phase 3: Build results
        results: list[FrameResult] = []
        for code_file in code_files:
            all_findings = (
                pattern_findings_map.get(code_file.path, [])
                + assertion_findings_map.get(code_file.path, [])
                + llm_findings_map.get(code_file.path, [])
            )
            # Drop known false-positive patterns (e.g. ContextVar flagged as async-unsafe)
            all_findings = self._filter_known_false_positives(all_findings)
            # Drop low-value architectural noise from LLM (cache TTL, transport fallback, …)
            all_findings = self._filter_llm_noise(all_findings)
            status = self._determine_status(all_findings)
            results.append(
                FrameResult(
                    frame_id=self.frame_id,
                    frame_name=self.name,
                    status=status,
                    duration=time.perf_counter() - batch_start,
                    issues_found=len(all_findings),
                    is_blocker=False,
                    findings=all_findings,
                    metadata={
                        "checks_executed": len(self.PATTERNS) + 1,
                        "file_size": code_file.size_bytes,
                        "line_count": code_file.line_count,
                        "batch_mode": True,
                    },
                )
            )

        batch_duration = time.perf_counter() - batch_start
        logger.info(
            "property_batch_completed",
            file_count=len(code_files),
            total_findings=sum(r.issues_found for r in results),
            duration=f"{batch_duration:.2f}s",
        )
        return results

    async def _batch_llm_analysis(self, code_files: list[CodeFile]) -> dict[str, list[Finding]]:
        """Run batched LLM analysis across multiple files."""
        findings_map: dict[str, list[Finding]] = {f.path: [] for f in code_files}

        # Guard: skip LLM on slow local providers (mirrors llm_phase_base threshold).
        from warden.llm.provider_speed_benchmark import (
            ProviderSpeedBenchmarkService,
            get_benchmark_service,
        )

        _PROPERTY_MIN_VIABLE_TOKENS = 80  # Must match _MIN_VIABLE_TOKENS in llm_phase_base
        if ProviderSpeedBenchmarkService._is_local_provider(self.llm_service):
            _svc = get_benchmark_service()
            _safe = await _svc.get_safe_max_tokens(self.llm_service, phase_timeout_s=120.0, default_max_tokens=800)
            if hasattr(self.llm_service, "set_safe_num_predict"):
                self.llm_service.set_safe_num_predict(_safe)
            if _safe < _PROPERTY_MIN_VIABLE_TOKENS:
                logger.warning(
                    "llm_skipped_budget_below_viable",
                    phase="property",
                    max_tokens=_safe,
                    min_viable=_PROPERTY_MIN_VIABLE_TOKENS,
                    note="fallback_to_rules",
                )
                return findings_map

        try:
            from warden.llm.types import LlmRequest
            from warden.shared.utils.llm_context import BUDGET_PROPERTY, prepare_code_for_llm, resolve_token_budget

            # Build combined prompt
            budget = resolve_token_budget(BUDGET_PROPERTY, is_fast_tier=True)
            parts = []
            for idx, cf in enumerate(code_files):
                parts.append(f"=== FILE {idx}: {cf.path} ({cf.language}) ===")
                parts.append(prepare_code_for_llm(cf.content, token_budget=budget))
                parts.append("")

            combined = "\n".join(parts)

            # Use the safe token budget computed above for local providers; cloud gets 800.
            _output_max = _safe if ProviderSpeedBenchmarkService._is_local_provider(self.llm_service) else 800
            request = LlmRequest(
                system_prompt=self.BATCH_SYSTEM_PROMPT,
                user_message=f"Analyze these {len(code_files)} files:\n\n{combined}",
                temperature=0.1,
                use_fast_tier=True,
                max_tokens=_output_max,
            )

            response = await self.llm_service.send_with_tools_async(request)

            if response.success and response.content:
                self._parse_batch_llm_response(response.content, code_files, findings_map)
            else:
                logger.warning("property_batch_llm_failed", error=response.error_message)
                # Fallback: serial LLM analysis
                findings_map = await self._serial_llm_fallback(code_files)

        except Exception as e:
            logger.error("property_batch_llm_error", error=str(e))
            # Fallback: serial LLM analysis
            try:
                findings_map = await self._serial_llm_fallback(code_files)
            except Exception:
                pass

        return findings_map

    def _parse_batch_llm_response(
        self, content: str, code_files: list[CodeFile], findings_map: dict[str, list[Finding]]
    ) -> None:
        """Parse batch LLM JSON response into per-file findings."""
        # Strip markdown code fences
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        try:
            data = _json.loads(content)
        except _json.JSONDecodeError:
            # Try recovering valid entries from truncated JSON array
            data = self._recover_truncated_json_array(content)
            if not data:
                logger.warning("property_batch_parse_failed", content_preview=content[:200])
                return
            logger.info(
                "property_batch_partial_recovery",
                recovered_items=len(data),
            )

        if not isinstance(data, list):
            data = [data]

        from warden.llm.types import AnalysisResult

        for item in data:
            if not isinstance(item, dict):
                continue
            file_idx = item.get("file_idx", -1)
            if not (0 <= file_idx < len(code_files)):
                continue

            code_file = code_files[file_idx]
            try:
                result = AnalysisResult.from_json(item)
                for issue in result.issues:
                    if not self._validate_llm_line_reference(
                        finding_message=issue.title,
                        finding_title=issue.description,
                        code_content=code_file.content,
                        reported_line=issue.line,
                    ):
                        logger.debug(
                            "property_batch_llm_line_hallucination_dropped",
                            file=code_file.path,
                            file_idx=file_idx,
                            reported_line=issue.line,
                            title=issue.title,
                        )
                        continue
                    findings_map[code_file.path].append(
                        Finding(
                            id=f"{self.frame_id}-llm-batch-{file_idx}-{issue.line}",
                            severity=issue.severity,
                            message=issue.title,
                            location=f"{code_file.path}:{issue.line}",
                            detail=issue.description,
                            code=issue.evidence_quote,
                        )
                    )
            except Exception as e:
                logger.warning("property_batch_item_parse_failed", file_idx=file_idx, error=str(e))

    @staticmethod
    def _recover_truncated_json_array(content: str) -> list[dict] | None:
        """Try to recover valid entries from a truncated JSON array.

        LLM responses may be cut off mid-token. This finds the last complete
        object in the array and parses everything up to that point.
        """
        content = content.strip()
        if not content.startswith("["):
            return None

        # Find last complete object by searching for "}," or "}\n]" backwards
        last_brace = content.rfind("}")
        if last_brace < 0:
            return None

        # Try parsing [... up to last complete }]
        candidate = content[: last_brace + 1].rstrip(",").rstrip() + "]"
        try:
            data = _json.loads(candidate)
            if isinstance(data, list) and data:
                return data
        except _json.JSONDecodeError:
            pass

        return None

    async def _serial_llm_fallback(self, code_files: list[CodeFile]) -> dict[str, list[Finding]]:
        """Fallback: run LLM analysis on all files concurrently (bounded to 3 parallel)."""
        import asyncio as _asyncio

        findings_map: dict[str, list[Finding]] = {f.path: [] for f in code_files}
        sem = _asyncio.Semaphore(3)

        async def _analyze_one(code_file: CodeFile) -> tuple[str, list[Finding]]:
            async with sem:
                try:
                    return code_file.path, await self._analyze_with_llm(code_file)
                except Exception as e:
                    logger.warning("property_serial_fallback_failed", file=code_file.path, error=str(e))
                    return code_file.path, []

        results = await _asyncio.gather(*[_analyze_one(cf) for cf in code_files])
        for path, finds in results:
            findings_map[path] = finds
        return findings_map

    async def execute_async(self, code_file: CodeFile, context: PipelineContext | None = None) -> FrameResult:
        """
        Execute property testing checks on code file.

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with findings
        """
        start_time = time.perf_counter()

        logger.info(
            "property_frame_started",
            file_path=code_file.path,
            language=code_file.language,
        )

        findings = []

        # Run pattern-based checks using pre-compiled patterns
        for check_id, check_config in self._compiled_patterns.items():
            pattern_findings = self._check_pattern_compiled(
                code_file=code_file,
                check_id=check_id,
                compiled_pattern=check_config["compiled"],
                severity=check_config["severity"],
                message=check_config["message"],
                suggestion=check_config.get("suggestion"),
            )
            findings.extend(pattern_findings)

        # Run LLM analysis if available
        if hasattr(self, "llm_service") and self.llm_service:
            llm_findings = await self._analyze_with_llm(code_file)
            findings.extend(llm_findings)

        # Check for assertion usage (good practice)
        assertion_findings = self._check_assertions(code_file)
        findings.extend(assertion_findings)

        # Drop known false-positive patterns (e.g. ContextVar flagged as async-unsafe)
        findings = self._filter_known_false_positives(findings)
        # Drop low-value architectural noise from LLM (cache TTL, transport fallback, …)
        findings = self._filter_llm_noise(findings)

        # Determine status
        status = self._determine_status(findings)

        duration = time.perf_counter() - start_time

        logger.info(
            "property_frame_completed",
            file_path=code_file.path,
            status=status,
            total_findings=len(findings),
            duration=f"{duration:.2f}s",
        )

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=duration,
            issues_found=len(findings),
            is_blocker=False,
            findings=findings,
            metadata={
                "checks_executed": len(self.PATTERNS) + 1,  # +1 for assertion check
                "file_size": code_file.size_bytes,
                "line_count": code_file.line_count,
            },
        )

    def _check_pattern_compiled(
        self,
        code_file: CodeFile,
        check_id: str,
        compiled_pattern: re.Pattern,
        severity: str,
        message: str,
        suggestion: str | None = None,
    ) -> list[Finding]:
        """Check for pattern matches in code using pre-compiled pattern."""
        findings: list[Finding] = []

        try:
            lines = code_file.content.split("\n")

            for line_num, line in enumerate(lines, start=1):
                # Skip comments, decorators, string-only lines, and logging/print statements
                stripped = line.strip()
                if stripped.startswith(("#", "//", "/*", "*", "@")):
                    continue
                if stripped.startswith(("'", '"')) or stripped.startswith(("f'", 'f"', "b'", 'b"')):
                    continue
                if stripped.startswith(("console.print", "print(", "logger.", "log.", "logging.")):
                    continue

                matches = compiled_pattern.finditer(line)
                for _ in matches:
                    # For division checks: skip guarded divisions AND pathlib / operator
                    if check_id == "division_no_zero_check":
                        if self._has_division_guard(lines, line_num):
                            continue
                        # Pathlib Path / operator is concatenation, not arithmetic
                        if "Path" in line or "path" in line or "__file__" in line:
                            continue

                    finding = Finding(
                        id=f"{self.frame_id}-{check_id}-{line_num}",
                        severity=severity,
                        message=message,
                        location=f"{code_file.path}:{line_num}",
                        detail=suggestion,
                        code=line.strip(),
                    )
                    findings.append(finding)

        except Exception as e:
            logger.error(
                "pattern_check_failed",
                check_id=check_id,
                error=str(e),
            )

        return findings

    def _has_division_guard(self, lines: list[str], line_num: int) -> bool:
        """Return True when a division on *line_num* is already guarded.

        Inspects the division line itself and up to 2 lines before it for any
        of the patterns defined in ``_DIVISION_GUARD_PATTERNS``.  This catches:

        * Inline ternary guards: ``sum(x) / len(x) if x else 0.0``
        * Preceding if-checks:  ``if denominator != 0:``
        * Truthy guards:        ``if values:``
        * try/except blocks:    ``except ZeroDivisionError``
        * or-fallbacks:         ``divisor or 1``
        """
        # lines is 0-indexed; line_num is 1-indexed
        start = max(0, line_num - 3)  # up to 2 lines before (inclusive)
        end = line_num  # line_num - 1 is the match line (0-indexed)
        context = " ".join(lines[start:end])
        return any(p.search(context) for p in self._DIVISION_GUARD_PATTERNS)

    @staticmethod
    def _is_test_file(file_path: str) -> bool:
        """Return True if the file path looks like a test file.

        Covers Python, JavaScript/TypeScript, Go, Ruby, and Java conventions.
        """
        path_lower = file_path.lower().replace("\\", "/")
        parts = path_lower.split("/")
        filename = parts[-1]

        # Directory-level indicators
        test_dir_names = {"tests", "test", "__tests__", "spec", "specs", "e2e", "integration"}
        if any(part in test_dir_names for part in parts[:-1]):
            return True

        # Filename-level indicators
        test_filename_patterns = (
            "test_",    # Python: test_foo.py
            "_test.",   # Python/Go: foo_test.py, foo_test.go
            ".test.",   # JS/TS: foo.test.ts
            ".spec.",   # JS/TS: foo.spec.ts
            "_spec.",   # Ruby: foo_spec.rb
            "spec_",    # Less common prefix
        )
        return any(pat in filename for pat in test_filename_patterns)

    def _check_assertions(self, code_file: CodeFile) -> list[Finding]:
        """Check for missing assertions in test code.

        Assertions belong in test files. Flagging their absence in production
        code generates low-value noise on every real-world project, so this
        check is skipped entirely for non-test files.
        """
        findings: list[Finding] = []

        # Only meaningful for test files — production code is not expected to
        # use assert statements for contract validation.
        if not self._is_test_file(code_file.path):
            return findings

        # Count assertions vs functions using pre-compiled patterns
        assertion_count = len(self._assertion_pattern.findall(code_file.content))
        function_count = len(self._function_pattern.findall(code_file.content))

        # If many test functions but no assertions, warn
        if function_count > 10 and assertion_count == 0:
            finding = Finding(
                id=f"{self.frame_id}-no-assertions",
                severity="low",
                message=f"File has {function_count} functions but no assertions",
                location=f"{code_file.path}:1",
                detail="Consider adding assertions or Pydantic validation to validate invariants and preconditions",
                code=None,
            )
            findings.append(finding)

        return findings

    # Patterns whose titles/descriptions indicate a known false-positive category.
    # Each entry is (title_fragment, description_fragment) — both are checked
    # case-insensitively. A finding is suppressed when ANY entry matches.
    _KNOWN_FP_PATTERNS: list[tuple[str, str]] = [
        # ContextVar is the official Python async-safe state mechanism (PEP 567).
        ("contextvar", "async"),
        ("contextvar", "thread"),
        ("contextvar", "race"),
        ("contextvar", "safety"),
        ("contextvar", "safe"),
        # Exception hierarchy — FP when the handler is a broad base class that covers all cases.
        ("exception hierarchy", "base exception"),
        ("exception hierarchy", "catches all"),
        # Inert template literal — FP for f-strings and str.format() which DO interpolate.
        ("template", "f-string"),
        ("template", "format_map"),
        ("inert template", "f-string"),
        # Unbounded gather — FP when a semaphore is already present in the same scope.
        ("unbounded", "semaphore"),
        ("concurrency", "bounded"),
    ]

    # Keywords that, when present in a LOW-severity LLM finding's combined
    # title+description text, indicate architectural style noise rather than an
    # actionable defect.  A finding is suppressed when ANY noise keyword matches
    # AND no security-sensitive keyword is also present.
    _NOISE_KEYWORDS: frozenset[str] = frozenset(
        {
            "hardcoded constant",
            "hardcoded cache",
            "hardcoded ttl",
            "cache ttl",
            "transport fallback",
            "fallback without validation",
            "magic number",
            "configuration constant",
            "missing configuration",
            "without configuration",
            "not configurable",
            "not externalized",
            "externalize",
            "should be configurable",
            # Exception hierarchy noise — vague reports that don't name the uncaught exception type.
            "may not be caught",
            "might not be caught",
            "could raise other exceptions",
            # Inert template noise — reports on non-interpolating string contexts without proof.
            "may not be interpolated",
            "might not be interpolated",
            "template syntax not evaluated",
        }
    )

    # If any of these security-sensitive terms appear in the same finding,
    # the finding is NOT suppressed regardless of noise-keyword matches.
    _SECURITY_EXEMPT_KEYWORDS: frozenset[str] = frozenset(
        {
            "password",
            "passwd",
            "secret",
            "api key",
            "apikey",
            "token",
            "credential",
            "private key",
            "encryption key",
            "auth",
            "bearer",
            "jwt",
            "oauth",
        }
    )

    def _filter_known_false_positives(self, findings: list[Finding]) -> list[Finding]:
        """Drop findings that match known false-positive patterns.

        This is a defense-in-depth layer: the LLM prompts already instruct the
        model not to flag these patterns, but this filter catches any residual
        cases where the model ignores that guidance.
        """
        filtered: list[Finding] = []
        for finding in findings:
            title_lower = (finding.message or "").lower()
            desc_lower = (finding.detail or "").lower()
            combined = title_lower + " " + desc_lower

            suppressed = False
            for title_frag, desc_frag in self._KNOWN_FP_PATTERNS:
                if title_frag in combined and desc_frag in combined:
                    logger.debug(
                        "property_fp_suppressed",
                        finding_id=finding.id,
                        message=finding.message,
                        reason=f"matches known-safe pattern: {title_frag!r}+{desc_frag!r}",
                    )
                    suppressed = True
                    break

            if not suppressed:
                filtered.append(finding)

        return filtered

    def _filter_llm_noise(self, findings: list[Finding]) -> list[Finding]:
        """Drop low-value architectural noise from LLM-generated findings.

        Keeps any finding that is:
          - severity medium, high, or critical (always kept), OR
          - severity low/info but contains security-sensitive keywords
            (password, secret, token, credential, key, auth, jwt, …).

        Drops severity low/info findings whose combined title+description
        contain a known architectural-noise keyword (hardcoded constant,
        cache TTL, transport fallback, magic number, configuration …) AND
        no security-sensitive keyword.
        """
        filtered: list[Finding] = []
        for finding in findings:
            severity = (finding.severity or "low").lower()

            # Always keep medium+ findings — they are actionable.
            if severity not in ("low", "info"):
                filtered.append(finding)
                continue

            combined = ((finding.message or "") + " " + (finding.detail or "")).lower()

            # Exempt from suppression if any security-sensitive term is present.
            if any(sec in combined for sec in self._SECURITY_EXEMPT_KEYWORDS):
                filtered.append(finding)
                continue

            # Suppress if a noise keyword matches.
            matched_noise = next((kw for kw in self._NOISE_KEYWORDS if kw in combined), None)
            if matched_noise:
                logger.debug(
                    "property_llm_noise_suppressed",
                    finding_id=finding.id,
                    message=finding.message,
                    noise_keyword=matched_noise,
                )
                continue

            filtered.append(finding)

        return filtered

    # ------------------------------------------------------------------
    # LLM line-reference validation
    # (implementation lives in warden.shared.utils.finding_utils)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_llm_line_reference(
        finding_message: str,
        finding_title: str,
        code_content: str,
        reported_line: int,
        window: int = 3,
    ) -> bool:
        """Delegate to the shared line-reference validator.

        See ``warden.shared.utils.finding_utils.validate_llm_line_reference``
        for full documentation.
        """
        from warden.shared.utils.finding_utils import validate_llm_line_reference

        return validate_llm_line_reference(
            finding_message=finding_message,
            finding_title=finding_title,
            code_content=code_content,
            reported_line=reported_line,
            window=window,
        )

    def _determine_status(self, findings: list[Finding]) -> str:
        """Determine frame status based on findings."""
        if not findings:
            return "passed"

        # Count high severity
        high_count = sum(1 for f in findings if f.severity == "high")

        if high_count > 3:
            return "failed"  # Many high severity issues
        elif high_count > 0:
            return "warning"  # Some high severity
        else:
            return "passed"  # Only medium/low

    async def _analyze_with_llm(self, code_file: CodeFile) -> list[Finding]:
        """Analyze code using LLM for deeper property verification."""
        findings: list[Finding] = []
        try:
            import json

            from warden.llm.types import AnalysisResult, LlmRequest

            logger.info("property_llm_analysis_started", file=code_file.path)

            client = self.llm_service

            from warden.llm.provider_speed_benchmark import ProviderSpeedBenchmarkService, get_benchmark_service
            from warden.shared.utils.llm_context import BUDGET_PROPERTY, prepare_code_for_llm, resolve_token_budget

            budget = resolve_token_budget(BUDGET_PROPERTY, is_fast_tier=True)
            truncated = prepare_code_for_llm(code_file.content, token_budget=budget)

            if ProviderSpeedBenchmarkService._is_local_provider(client):
                _svc = get_benchmark_service()
                _output_max = await _svc.get_safe_max_tokens(client, phase_timeout_s=45.0, default_max_tokens=400)
                if hasattr(client, "set_safe_num_predict"):
                    client.set_safe_num_predict(_output_max)
            else:
                _output_max = 800

            request = LlmRequest(
                system_prompt=self.SYSTEM_PROMPT,
                user_message=f"Analyze this {code_file.language} code:\n\n{truncated}",
                temperature=0.1,
                use_fast_tier=True,
                max_tokens=_output_max,
            )

            response = await client.send_with_tools_async(request)

            if response.success and response.content:
                # Handle markdown code blocks if present
                content = response.content
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[0].strip()

                try:
                    data = json.loads(content)
                    result = AnalysisResult.from_json(data)

                    raw_count = 0
                    dropped_count = 0
                    for issue in result.issues:
                        raw_count += 1
                        if not self._validate_llm_line_reference(
                            finding_message=issue.title,
                            finding_title=issue.description,
                            code_content=code_file.content,
                            reported_line=issue.line,
                        ):
                            logger.debug(
                                "property_llm_line_hallucination_dropped",
                                file=code_file.path,
                                reported_line=issue.line,
                                title=issue.title,
                            )
                            dropped_count += 1
                            continue
                        findings.append(
                            Finding(
                                id=f"{self.frame_id}-llm-{issue.line}",
                                severity=issue.severity,
                                message=issue.title,
                                location=f"{code_file.path}:{issue.line}",
                                detail=issue.description,
                                code=issue.evidence_quote,
                            )
                        )

                    logger.info(
                        "property_llm_analysis_completed",
                        findings=len(findings),
                        confidence=result.confidence,
                        raw_issues=raw_count,
                        line_hallucinations_dropped=dropped_count,
                    )

                except Exception as e:
                    logger.warning("property_llm_parsing_failed", error=str(e), content_preview=content[:100])
            else:
                logger.warning("property_llm_request_failed", error=response.error_message)

        except ImportError:
            logger.debug("property_llm_not_available")
        except Exception as e:
            logger.error("property_llm_error", error=str(e))

        return findings
