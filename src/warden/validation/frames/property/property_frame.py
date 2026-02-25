"""
Property Frame - Logic validation and invariants.

Validates business logic correctness:
- Function preconditions/postconditions
- Class invariants
- State machine transitions
- Mathematical properties

Priority: HIGH
"""

import json as _json
import re
import time
from typing import Any

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

    # Property check patterns
    PATTERNS = {
        "division_no_zero_check": {
            "pattern": r"(?<!\/)\/\s*(\w+)(?!\s*(?:if|&&|\|\||\?|assert|\!=?\s*0))",
            "severity": "medium",
            "message": "Division operation without zero check",
            "suggestion": "Check divisor is not zero before division",
        },
        "comparison_always_true": {
            "pattern": r"if\s+true|if\s+True|while\s+true|while\s+True",
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

            request = LlmRequest(
                system_prompt=self.BATCH_SYSTEM_PROMPT,
                user_message=f"Analyze these {len(code_files)} files:\n\n{combined}",
                temperature=0.1,
                use_fast_tier=True,
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
        """Fallback: run LLM analysis file-by-file."""
        findings_map: dict[str, list[Finding]] = {f.path: [] for f in code_files}
        for code_file in code_files:
            try:
                llm_findings = await self._analyze_with_llm(code_file)
                findings_map[code_file.path] = llm_findings
            except Exception as e:
                logger.warning("property_serial_fallback_failed", file=code_file.path, error=str(e))
        return findings_map

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
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
                # Skip comments
                if line.strip().startswith(("#", "//", "/*", "*")):
                    continue

                matches = compiled_pattern.finditer(line)
                for _ in matches:
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

    def _check_assertions(self, code_file: CodeFile) -> list[Finding]:
        """Check for missing assertions in critical code."""
        findings: list[Finding] = []

        # Count assertions vs functions using pre-compiled patterns
        assertion_count = len(self._assertion_pattern.findall(code_file.content))
        function_count = len(self._function_pattern.findall(code_file.content))

        # If many functions but no assertions, warn
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

            from warden.shared.utils.llm_context import BUDGET_PROPERTY, prepare_code_for_llm, resolve_token_budget

            budget = resolve_token_budget(BUDGET_PROPERTY, is_fast_tier=True)
            truncated = prepare_code_for_llm(code_file.content, token_budget=budget)

            request = LlmRequest(
                system_prompt=self.SYSTEM_PROMPT,
                user_message=f"Analyze this {code_file.language} code:\n\n{truncated}",
                temperature=0.1,
                use_fast_tier=True,
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

                    for issue in result.issues:
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

                    logger.info("property_llm_analysis_completed", findings=len(findings), confidence=result.confidence)

                except Exception as e:
                    logger.warning("property_llm_parsing_failed", error=str(e), content_preview=content[:100])
            else:
                logger.warning("property_llm_request_failed", error=response.error_message)

        except ImportError:
            logger.debug("property_llm_not_available")
        except Exception as e:
            logger.error("property_llm_error", error=str(e))

        return findings
