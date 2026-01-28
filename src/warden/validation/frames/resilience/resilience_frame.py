"""
Resilience Architecture Analysis Frame (formerly Chaos Frame).

Validates architectural resilience using:
1. LSP-based pre-analysis (cheap, fast) - call hierarchy, error handler detection
2. LLM-based FMEA (expensive, deep) - only for complex patterns

Optimization: LSP first, LLM for edge cases only.
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


class ResilienceFrame(ValidationFrame):
    """
    Validation frame for Resilience Architecture Analysis (Chaos 2.0).
    
    This frame uses LLMs to perform Failure Mode & Effects Analysis (FMEA),
    identifying architectural weaknesses, critical paths, state consistency issues,
    and graceful degradation flaws.
    """
    
    # Metadata
    name = "Resilience Architecture Analysis"
    description = "LLM-driven Failure Mode & Effects Analysis (FMEA) for architectural resilience."
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

        # STEP 1: Quick pattern-based pre-analysis (free, fast)
        pattern_findings, has_resilience_code = await self._pre_analyze_patterns(code_file)
        findings.extend(pattern_findings)

        # STEP 2: LSP-based call hierarchy analysis (cheap, if available)
        if has_resilience_code:
            lsp_findings = await self._analyze_with_lsp(code_file)
            findings.extend(lsp_findings)

        # STEP 3: LLM deep analysis (expensive, only if needed)
        # Skip LLM if no resilience patterns found (nothing to analyze)
        if hasattr(self, 'llm_service') and self.llm_service and has_resilience_code:
            llm_findings = await self._analyze_with_llm(code_file)
            findings.extend(llm_findings)
        elif not has_resilience_code:
            logger.debug("resilience_no_patterns_found_skipping_llm", file=code_file.path)

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
                "method": "llm_fmea",
                "file_size": code_file.size_bytes,
                "line_count": code_file.line_count,
            },
        )

    async def _pre_analyze_patterns(self, code_file: CodeFile) -> tuple[List[Finding], bool]:
        """
        Quick pattern-based pre-analysis.

        Returns:
            (findings, has_resilience_code): Findings and whether file has resilience patterns
        """
        findings: List[Finding] = []
        pattern_matches: Dict[str, int] = {}

        content = code_file.content

        # Count resilience pattern matches
        for pattern_name, pattern in RESILIENCE_PATTERNS.items():
            matches = pattern.findall(content)
            if matches:
                pattern_matches[pattern_name] = len(matches)

        has_resilience_code = bool(pattern_matches)

        # Quick heuristic: try without except is suspicious
        try_count = len(RESILIENCE_PATTERNS["try_except"].findall(content))
        # Match except with optional exception type: except:, except Exception:, except (A, B):
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

        # Heuristic: async without timeout is risky
        async_count = len(re.findall(r'\basync\s+def\b', content))
        timeout_count = pattern_matches.get("timeout", 0)

        if async_count > 3 and timeout_count == 0:
            findings.append(Finding(
                id=f"{self.frame_id}-missing-timeout",
                severity="low",
                message=f"File has {async_count} async functions but no timeout handling",
                location=f"{code_file.path}:1",
                detail="Consider adding timeouts to prevent hanging operations",
                code=None
            ))

        logger.debug("resilience_pre_analysis_complete",
                    file=code_file.path,
                    patterns=pattern_matches,
                    findings=len(findings))

        return findings, has_resilience_code

    async def _analyze_with_lsp(self, code_file: CodeFile) -> List[Finding]:
        """
        Use LSP for structural resilience analysis.

        Checks:
        - Are error handlers called from critical paths?
        - Are retry/timeout decorators properly applied?
        """
        findings: List[Finding] = []

        try:
            from warden.lsp import get_semantic_analyzer

            analyzer = get_semantic_analyzer()

            # Find exception handler functions and check if they're used
            exception_pattern = re.compile(r'def\s+(handle_\w*error|on_\w*error|_handle_exception)\s*\(')
            for match in exception_pattern.finditer(code_file.content):
                func_name = match.group(1)
                line_num = code_file.content[:match.start()].count('\n')

                # Check if this handler is actually called
                is_used = await analyzer.is_symbol_used_async(
                    code_file.path, line_num, match.start(1) - match.start(),
                    content=code_file.content
                )

                if is_used is False:  # Explicitly False, not None
                    findings.append(Finding(
                        id=f"{self.frame_id}-unused-handler-{line_num}",
                        severity="medium",
                        message=f"Error handler '{func_name}' is defined but never called",
                        location=f"{code_file.path}:{line_num + 1}",
                        detail="Dead error handler - ensure it's connected to the error handling flow",
                        code=func_name
                    ))

            logger.debug("resilience_lsp_analysis_complete",
                        file=code_file.path,
                        findings=len(findings))

        except ImportError:
            logger.debug("resilience_lsp_not_available")
        except Exception as e:
            logger.warning("resilience_lsp_analysis_error", error=str(e))

        return findings

    async def _analyze_with_llm(self, code_file: CodeFile) -> List[Finding]:
        """
        Analyze code using LLM for Resilience FMEA (expensive, deep analysis).
        """
        from warden.llm.prompts.resilience import CHAOS_SYSTEM_PROMPT, generate_chaos_request
        from warden.llm.types import LlmRequest, AnalysisResult
        
        findings: List[Finding] = []
        try:
            logger.info("resilience_llm_analysis_started", file=code_file.path)
            
            client: ILlmClient = self.llm_service
            
            request = LlmRequest(
                system_prompt=CHAOS_SYSTEM_PROMPT,
                user_message=generate_chaos_request(code_file.content, code_file.language, code_file.path),
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
