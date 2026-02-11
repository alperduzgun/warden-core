"""
Resilience Architecture Analysis Frame (formerly Chaos Frame).

Validates architectural resilience using LLM-based Failure Mode & Effects Analysis (FMEA).
"""

import time
from typing import List, Dict, Any

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

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """
        Execute resilience analysis on code file.

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
            llm_service_type=str(type(getattr(self, 'llm_service', None))) if hasattr(self, 'llm_service') else "N/A"
        )

        findings: List[Finding] = []

        # Run LLM analysis if available (PRIMARY METHOD)
        if hasattr(self, 'llm_service') and self.llm_service:
            llm_findings = await self._analyze_with_llm(code_file)
            findings.extend(llm_findings)
        else:
            logger.warning("resilience_llm_not_available_skipping_analysis")

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

    async def _analyze_with_llm(self, code_file: CodeFile) -> List[Finding]:
        """
        Analyze code using LLM for Resilience FMEA.
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
                temperature=0.2  # Slightly higher for creative scenario generation
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
