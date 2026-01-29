"""
Chaos Engineering Analysis Frame.

Applies chaos engineering principles to code:
1. Detect external dependencies (network, DB, files, queues)
2. Simulate failure scenarios (timeout, error, resource exhaustion)
3. Identify MISSING resilience patterns (not validate existing ones)

Philosophy: "Everything will fail. The question is HOW and WHEN."
The LLM acts as a chaos engineer, deciding what failures to simulate
based on the code's context and dependencies.
"""

import re
import time
from typing import List, Dict, Any, Optional

from warden.validation.domain.frame import (
    ValidationFrame,
    FrameResult,
    Finding,
    CodeFile,
)
from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
    FrameApplicability,
)
from warden.shared.infrastructure.logging import get_logger
from warden.llm.providers.base import ILlmClient

logger = get_logger(__name__)

# Pre-compiled resilience patterns for fast detection
RESILIENCE_PATTERNS = {
    "try_except": re.compile(r'\btry\s*:', re.MULTILINE),
    "retry": re.compile(r'\bretry|@retry|with_retry|retries\s*=', re.IGNORECASE),
    "timeout": re.compile(r'\btimeout|@timeout|with_timeout|asyncio\.wait_for', re.IGNORECASE),
    "circuit_breaker": re.compile(r'circuit.?breaker|@circuit|CircuitBreaker', re.IGNORECASE),
    "fallback": re.compile(r'\bfallback|@fallback|default_value|or\s+default', re.IGNORECASE),
    "health_check": re.compile(r'health.?check|liveness|readiness|/health', re.IGNORECASE),
}

# Pre-compiled chaos triggers (external dependencies that can fail)
CHAOS_TRIGGERS = {
    "network_calls": re.compile(r'\b(requests\.|httpx\.|aiohttp\.|urllib|fetch\(|\.get\(|\.post\()', re.IGNORECASE),
    "database_ops": re.compile(r'\b(cursor\.|execute\(|query\(|session\.|\.commit\(|\.rollback\(|SELECT|INSERT|UPDATE|DELETE)', re.IGNORECASE),
    "file_io": re.compile(r'\b(open\(|Path\(|\.read\(|\.write\(|os\.path|shutil\.)', re.IGNORECASE),
    "external_process": re.compile(r'\b(subprocess\.|Popen|os\.system|run\()', re.IGNORECASE),
    "async_operations": re.compile(r'\basync\s+def\b|\bawait\b', re.IGNORECASE),
    "message_queues": re.compile(r'\b(kafka|rabbitmq|redis|celery|pubsub|queue)', re.IGNORECASE),
    "cloud_services": re.compile(r'\b(boto3|azure|gcloud|s3\.|dynamodb|lambda)', re.IGNORECASE),
}


class ResilienceFrame(ValidationFrame):
    """
    Chaos Engineering Analysis Frame.

    Applies chaos engineering principles: simulate failures, find missing resilience.

    APPROACH:
    1. Detect chaos triggers (external dependencies that can fail)
    2. Let LLM simulate failure scenarios based on context
    3. Report MISSING resilience patterns (timeout, retry, circuit breaker, fallback)

    The LLM acts as a chaos engineer - it decides what to test based on the code.
    """

    # Metadata
    name = "Chaos Engineering Analysis"
    description = "Chaos engineering: simulate failures, find missing resilience patterns."
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = False  # Not blocking for now as it's advisory
    version = "2.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """Initialize Resilience Frame."""
        super().__init__(config)
        
        # Load System Prompt
        try:
            from warden.llm.prompts.resilience import CHAOS_SYSTEM_PROMPT
            self.system_prompt = CHAOS_SYSTEM_PROMPT
        except ImportError:
            logger.warning("resilience_prompt_import_failed")
            self.system_prompt = "You are a Resilience Engineer."

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        """
        Execute resilience analysis on code file.

        Strategy: LSP pre-analysis (cheap) → LLM deep analysis (expensive, only if needed)

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with findings
        """
        start_time = time.perf_counter()

        logger.info(
            "resilience_analysis_started",
            file_path=code_file.path,
            language=code_file.language,
            has_llm_service=hasattr(self, 'llm_service'),
        )

        findings: List[Finding] = []

        # STEP 1: Quick pre-analysis - detect chaos triggers (external dependencies)
        pattern_findings, chaos_context = await self._pre_analyze_patterns(code_file)
        findings.extend(pattern_findings)

        worth_chaos_analysis = bool(chaos_context.get("triggers"))

        # STEP 2: LSP-based structural analysis (cheap, if file has dependencies)
        if worth_chaos_analysis:
            lsp_findings = await self._analyze_with_lsp(code_file)
            findings.extend(lsp_findings)

        # STEP 3: LLM chaos engineering analysis (AI decides what to check)
        # CHAOS APPROACH: If file has external dependencies → LLM simulates failures
        # LLM will decide what resilience patterns are NEEDED (not validate existing ones)
        if hasattr(self, 'llm_service') and self.llm_service and worth_chaos_analysis:
            llm_findings = await self._analyze_with_llm(code_file, chaos_context)
            findings.extend(llm_findings)
        elif not worth_chaos_analysis:
            logger.debug("resilience_no_external_deps_skipping", file=code_file.path)

        # Determine status
        status = self._determine_status(findings)

        duration = time.perf_counter() - start_time

        logger.info(
            "resilience_analysis_completed",
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
            is_blocker=self.is_blocker,
            findings=findings,
            metadata={
                "method": "chaos_engineering",
                "file_size": code_file.size_bytes,
                "line_count": code_file.line_count,
                "chaos_triggers": chaos_context.get("triggers", {}),
                "existing_patterns": chaos_context.get("existing_patterns", {}),
            },
        )

    async def _pre_analyze_patterns(self, code_file: CodeFile) -> tuple[List[Finding], Dict[str, Any]]:
        """
        Quick pattern-based pre-analysis for chaos engineering.

        CHAOS ENGINEERING APPROACH:
        - Don't look for "retry/timeout exists" → that's pattern validation
        - Look for "external dependencies exist" → that needs chaos analysis
        - LLM decides what resilience patterns are NEEDED, not what EXISTS

        Returns:
            (findings, chaos_context): Findings and context for LLM (triggers, existing patterns)
        """
        findings: List[Finding] = []
        content = code_file.content

        # Count chaos triggers (things that CAN fail) - uses pre-compiled CHAOS_TRIGGERS
        trigger_counts: Dict[str, int] = {}
        for trigger_name, pattern in CHAOS_TRIGGERS.items():
            matches = pattern.findall(content)
            if matches:
                trigger_counts[trigger_name] = len(matches)

        # Also count existing resilience patterns (for context, not gating)
        resilience_counts: Dict[str, int] = {}
        for pattern_name, pattern in RESILIENCE_PATTERNS.items():
            matches = pattern.findall(content)
            if matches:
                resilience_counts[pattern_name] = len(matches)

        # Quick structural findings (obvious issues)
        try_count = len(RESILIENCE_PATTERNS["try_except"].findall(content))
        except_count = len(re.findall(r'\bexcept\b.*:', content))

        if try_count > 0 and except_count == 0:
            findings.append(Finding(
                id=f"{self.frame_id}-bare-try",
                severity="medium",
                message="Try block without exception handling detected",
                location=f"{code_file.path}:1",
                detail="Consider adding proper exception handling for resilience",
                code=None
            ))

        # Build chaos context for LLM
        chaos_context: Dict[str, Any] = {
            "triggers": trigger_counts,  # What can fail
            "existing_patterns": resilience_counts,  # What protection exists
            "dependencies": list(trigger_counts.keys()),  # For LLM prompt
        }

        logger.debug("resilience_pre_analysis_complete",
                    file=code_file.path,
                    chaos_triggers=trigger_counts,
                    resilience_patterns=resilience_counts,
                    findings=len(findings))

        return findings, chaos_context

    async def _analyze_with_lsp(self, code_file: CodeFile) -> List[Finding]:
        """
        Use LSP for structural resilience analysis (cheap, before LLM).

        Checks:
        1. Unused error handlers (dead code)
        2. Fallback functions not connected
        3. Retry/timeout decorators on wrong functions
        4. Async functions calling external APIs without timeout (no LSP needed)

        Uses 10s timeout per LSP call to fail fast.
        """
        import asyncio
        findings: List[Finding] = []

        # Check 4 doesn't need LSP - do it first (instant)
        self._check_async_without_timeout_sync(code_file, findings)

        try:
            from warden.lsp import get_semantic_analyzer

            analyzer = get_semantic_analyzer()

            # Run LSP checks with individual timeouts (fail fast)
            lsp_timeout = 10.0  # 10s per check, not 30s

            # Collect all checks to run
            checks = [
                self._check_unused_handlers(analyzer, code_file, findings),
                self._check_unused_fallbacks(analyzer, code_file, findings),
                self._check_decorated_functions(analyzer, code_file, findings),
            ]

            # Run with timeout - if LSP is slow, skip gracefully
            try:
                await asyncio.wait_for(
                    asyncio.gather(*checks, return_exceptions=True),
                    timeout=lsp_timeout * 3  # Total timeout for all checks
                )
            except asyncio.TimeoutError:
                logger.warning("resilience_lsp_timeout_skipping", file=code_file.path)

            logger.debug("resilience_lsp_analysis_complete",
                        file=code_file.path,
                        findings=len(findings))

        except ImportError:
            logger.debug("resilience_lsp_not_available")
        except Exception as e:
            logger.warning("resilience_lsp_analysis_error", error=str(e))

        return findings

    def _check_async_without_timeout_sync(self, code_file: CodeFile, findings: List[Finding]) -> None:
        """Check async functions calling external services without timeout (no LSP needed)."""
        # Find async functions that likely call external APIs
        external_call_pattern = re.compile(
            r'async\s+def\s+(\w+)\s*\([^)]*\)[^:]*:'
            r'(?:(?!async\s+def).)*?'  # Content until next async def
            r'(?:await\s+(?:self\.)?(?:client|http|session|request|api|fetch)\.\w+)',
            re.DOTALL
        )

        content = code_file.content

        for match in external_call_pattern.finditer(content):
            func_name = match.group(1)
            func_content = match.group(0)
            line_num = content[:match.start()].count('\n')

            # Check if this function has timeout wrapper
            has_timeout = (
                'wait_for' in func_content or
                'timeout=' in func_content or
                '@timeout' in content[max(0, match.start()-50):match.start()]
            )

            if not has_timeout:
                findings.append(Finding(
                    id=f"{self.frame_id}-async-no-timeout-{line_num}",
                    severity="medium",
                    message=f"Async function '{func_name}' calls external service without timeout",
                    location=f"{code_file.path}:{line_num + 1}",
                    detail="External API calls should have timeouts to prevent hanging",
                    code=func_name
                ))

    async def _check_unused_handlers(self, analyzer, code_file: CodeFile, findings: List[Finding]) -> None:
        """Check for error handlers that are never called."""
        exception_pattern = re.compile(r'def\s+(handle_\w*error|on_\w*error|_handle_exception|error_callback)\s*\(')

        for match in exception_pattern.finditer(code_file.content):
            func_name = match.group(1)
            line_num = code_file.content[:match.start()].count('\n')

            is_used = await analyzer.is_symbol_used_async(
                code_file.path, line_num, match.start(1) - match.start(),
                content=code_file.content
            )

            if is_used is False:
                findings.append(Finding(
                    id=f"{self.frame_id}-unused-handler-{line_num}",
                    severity="medium",
                    message=f"Error handler '{func_name}' is defined but never called",
                    location=f"{code_file.path}:{line_num + 1}",
                    detail="Dead error handler - ensure it's connected to the error handling flow",
                    code=func_name
                ))

    async def _check_unused_fallbacks(self, analyzer, code_file: CodeFile, findings: List[Finding]) -> None:
        """Check for fallback functions that are never called."""
        fallback_pattern = re.compile(r'def\s+(fallback_\w+|get_default_\w+|_fallback)\s*\(')

        for match in fallback_pattern.finditer(code_file.content):
            func_name = match.group(1)
            line_num = code_file.content[:match.start()].count('\n')

            is_used = await analyzer.is_symbol_used_async(
                code_file.path, line_num, match.start(1) - match.start(),
                content=code_file.content
            )

            if is_used is False:
                findings.append(Finding(
                    id=f"{self.frame_id}-unused-fallback-{line_num}",
                    severity="medium",
                    message=f"Fallback function '{func_name}' is defined but never used",
                    location=f"{code_file.path}:{line_num + 1}",
                    detail="Fallback should be called in error handling paths",
                    code=func_name
                ))

    async def _check_decorated_functions(self, analyzer, code_file: CodeFile, findings: List[Finding]) -> None:
        """Check if @retry/@timeout decorated functions are actually called."""
        # Find functions with resilience decorators
        decorated_pattern = re.compile(r'@(?:retry|timeout|circuit_?breaker)\s*(?:\([^)]*\))?\s*\n\s*(?:async\s+)?def\s+(\w+)')

        for match in decorated_pattern.finditer(code_file.content):
            func_name = match.group(1)
            line_num = code_file.content[:match.end()].count('\n')

            is_used = await analyzer.is_symbol_used_async(
                code_file.path, line_num, 4,  # After 'def '
                content=code_file.content
            )

            if is_used is False:
                findings.append(Finding(
                    id=f"{self.frame_id}-unused-decorated-{line_num}",
                    severity="low",
                    message=f"Decorated function '{func_name}' has resilience decorator but is never called",
                    location=f"{code_file.path}:{line_num + 1}",
                    detail="Function with @retry/@timeout/@circuit_breaker is dead code",
                    code=func_name
                ))

    async def _check_async_without_timeout(self, analyzer, code_file: CodeFile, findings: List[Finding]) -> None:
        """Check async functions that call external services without timeout."""
        # Find async functions that likely call external APIs
        external_call_pattern = re.compile(
            r'async\s+def\s+(\w+)\s*\([^)]*\)[^:]*:'
            r'(?:(?!async\s+def).)*?'  # Content until next async def
            r'(?:await\s+(?:self\.)?(?:client|http|session|request|api|fetch)\.\w+)',
            re.DOTALL
        )

        content = code_file.content

        for match in external_call_pattern.finditer(content):
            func_name = match.group(1)
            func_content = match.group(0)
            line_num = content[:match.start()].count('\n')

            # Check if this function has timeout wrapper
            has_timeout = (
                'wait_for' in func_content or
                'timeout=' in func_content or
                '@timeout' in content[max(0, match.start()-50):match.start()]
            )

            if not has_timeout:
                findings.append(Finding(
                    id=f"{self.frame_id}-async-no-timeout-{line_num}",
                    severity="medium",
                    message=f"Async function '{func_name}' calls external service without timeout",
                    location=f"{code_file.path}:{line_num + 1}",
                    detail="External API calls should have timeouts to prevent hanging",
                    code=func_name
                ))

    async def _analyze_with_llm(self, code_file: CodeFile, chaos_context: Optional[Dict[str, Any]] = None) -> List[Finding]:
        """
        Analyze code using LLM for chaos engineering (expensive, context-aware).

        Args:
            code_file: Code to analyze
            chaos_context: Detected triggers and existing patterns from pre-analysis
        """
        from warden.llm.prompts.resilience import CHAOS_SYSTEM_PROMPT, generate_chaos_request
        from warden.llm.types import LlmRequest, AnalysisResult

        findings: List[Finding] = []
        try:
            logger.info("resilience_llm_analysis_started",
                       file=code_file.path,
                       triggers=chaos_context.get("triggers") if chaos_context else None)

            client: ILlmClient = self.llm_service

            # Pass chaos context to LLM so it knows what dependencies to focus on
            request = LlmRequest(
                system_prompt=CHAOS_SYSTEM_PROMPT,
                user_message=generate_chaos_request(
                    code_file.content,
                    code_file.language,
                    code_file.path,
                    context=chaos_context
                ),
                temperature=0.0,  # Idempotency (deterministic scenarios)
            )
            
            response = await client.send_async(request)
            
            if response.success and response.content:
                # Use robust shared JSON parser
                from warden.shared.utils.json_parser import parse_json_from_llm
                json_data = parse_json_from_llm(response.content)
                
                if json_data:
                    try:
                        # Parse result with Pydantic
                        result = AnalysisResult.from_json(json_data)
                        
                        for issue in result.issues:
                            findings.append(Finding(
                                id=f"{self.frame_id}-resilience-{issue.line}",
                                severity=issue.severity,
                                message=issue.title,
                                location=f"{code_file.path}:{issue.line}",
                                detail=f"{issue.description}\n\nSuggestion: {issue.suggestion}",
                                code=issue.evidence_quote
                            ))
                        
                        logger.info("resilience_llm_analysis_completed", 
                                  findings=len(findings), 
                                  confidence=result.confidence,
                                  resilience_score=result.score)
                                  
                    except (ValueError, TypeError, KeyError) as e:
                        logger.warning("resilience_llm_parsing_failed", error=str(e), content_preview=response.content[:100])
                else:
                    logger.warning("resilience_llm_response_not_json", content_preview=response.content[:100])
            else:
                 logger.warning("resilience_llm_request_failed", error=response.error_message)

        except (RuntimeError, AttributeError, ValueError) as e:
            logger.error("resilience_llm_error", error=str(e))
            
        return findings

    def _determine_status(self, findings: List[Finding]) -> str:
        """Determine frame status based on findings."""
        if not findings:
            return "passed"

        critical_count = sum(1 for f in findings if f.severity == "critical")
        high_count = sum(1 for f in findings if f.severity == "high")

        if critical_count > 0:
            return "failed"
        elif high_count > 0:
            return "warning"
        
        return "passed"
