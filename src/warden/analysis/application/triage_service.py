"""
Triage Service for Adaptive Hybrid Triage.
Uses Local LLM to assess file risk and complexity.
"""

import json
import time
import re
import structlog
from typing import Optional

from warden.llm.types import LlmRequest, LlmProvider
from warden.llm.providers.base import ILlmClient
from warden.validation.domain.frame import CodeFile
from warden.analysis.domain.triage_models import RiskScore, TriageLane, TriageDecision

logger = structlog.get_logger(__name__)

class TriageService:
    """
    Service for determining the analysis depth (Lane) for a code file.
    Uses Local LLM (The Sieve) to assign risk scores.
    """
    
    SYSTEM_PROMPT = """
    You are a Senior Security Architect acting as a Triage Gatekeeper.
    Your goal is to assess the SECURITY RISK and COMPLEXITY of the provided code.
    
    Analyze the code for:
    1. Security logic (Auth, Crypto, Input validation, SQL, Permissions)
    2. Business logic complexity (State management, External APIs, Data processing)
    3. Structural role (DTO, Config, UI, Test, Utility)
    
    Output strictly VALID JSON:
    {
        "score": <float 0.0-10.0>,
        "confidence": <float 0.0-1.0>,
        "category": "<string>",
        "reasoning": "<string>"
    }
    
    Scoring Guide:
    0-3: Safe (DTO, Config, UI).
    4-7: Suspicious (Logic, Controllers).
    8-10: Critical (Auth, Crypto, SQL).
    """

    def __init__(self, llm_client: ILlmClient):
        self.llm = llm_client

    async def assess_risk_async(self, code_file: CodeFile) -> TriageDecision:
        """
        Assess the risk of a file and decide the routing lane.
        """
        start_time = time.time()
        
        # 1. Hard Rules (Fastest Lane) - Pre-LLM optimization
        if self._is_obviously_safe(code_file):
            return self._create_decision(code_file, TriageLane.FAST, 0, "Hard rule: Safe file type/content", start_time)
            
        # 2. Local LLM Triage (The Sieve)
        try:
            risk_score = await self._get_llm_score_async(code_file)
        except Exception as e:
            logger.error("triage_llm_failed", error=str(e), file=code_file.path)
            # Fallback to Middle Lane on error to be safe
            return self._create_decision(
                code_file, 
                TriageLane.MIDDLE, 
                5, 
                f"Triage failed, fallback to Middle: {str(e)}", 
                start_time
            )

        # 3. Routing (The Router)
        lane = self._determine_lane(risk_score)
        
        return TriageDecision(
            file_path=str(code_file.path),
            lane=lane,
            risk_score=risk_score,
            processing_time_ms=(time.time() - start_time) * 1000
        )

    def _is_obviously_safe(self, code_file: CodeFile) -> bool:
        """Heuristics to skip LLM entirely for obvious files."""
        path = str(code_file.path).lower()
        
        # Safe extensions
        if path.endswith(('.md', '.txt', '.json', '.yaml', '.yml', '.css', '.scss', '.html')):
            return True
            
        # Safe directories
        if '/tests/' in path or '/test/' in path or '/docs/' in path:
            return True
            
        # Small files (DTOs usually)
        if len(code_file.content) < 200: 
            return True
            
        return False

    async def _get_llm_score_async(self, code_file: CodeFile) -> RiskScore:
        """Calls Local LLM to get risk score."""
        prompt = f"File Path: {code_file.path}\n\nCode:\n```{code_file.language}\n{code_file.content[:3000]}```"
        
        request = LlmRequest(
            system_prompt=self.SYSTEM_PROMPT,
            user_message=prompt,
            use_fast_tier=True,
            temperature=0.1,
            max_tokens=250
        )
        
        response = await self.llm.send_async(request)
        
        if not response.success:
            raise RuntimeError(f"LLM failed: {response.error_message}")
            
        return self._parse_response(response.content)

    def _parse_response(self, content: str) -> RiskScore:
        """Parses LLM JSON response with Chaos Hardening."""
        try:
            # 1. Extraction: Find JSON block even if LLM is chatty
            json_str = self._extract_json(content)
            
            # 2. Sanitization: Remove dangerous characters that break json.loads
            # (Sometimes Qwen adds control characters)
            json_str = re.sub(r'[\x00-\x1F\x7F]', '', json_str)
            
            data = json.loads(json_str)
            
            # 3. Validation: Use Pydantic to normalize (30 -> 3.0) and validate
            return RiskScore(**data)
            
        except Exception as e:
            logger.warning("triage_parse_failed", content=content[:200], error=str(e))
            # Fallback score (Safe enough for middle lane, high enough for attention)
            return RiskScore(
                score=5.0, 
                confidence=0.0, 
                reasoning=f"Parsing Error: {str(e)}", 
                category="chaos_fallback"
            )

    def _extract_json(self, text: str) -> str:
        """Regex-based JSON extraction to ignore LLM chatter."""
        # Simple balanced brace search
        match = re.search(r'(\{.*\})', text, re.DOTALL)
        if match:
            return match.group(1)
        
        # Fallback to cleaning markdown
        return text.replace("```json", "").replace("```", "").strip()

    def _determine_lane(self, risk: RiskScore) -> TriageLane:
        """Routing logic based on risk score."""
        if risk.score <= 3.5:
            return TriageLane.FAST
        elif risk.score <= 7.5:
            return TriageLane.MIDDLE
        else:
            return TriageLane.DEEP

    def _create_decision(self, code_file: CodeFile, lane: TriageLane, score: int, reason: str, start_time: float) -> TriageDecision:
        return TriageDecision(
            file_path=str(code_file.path),
            lane=lane,
            risk_score=RiskScore(score=score, confidence=1.0, reasoning=reason, category="heuristic"),
            processing_time_ms=(time.time() - start_time) * 1000
        )
