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

    async def batch_assess_risk_async(self, code_files: list[CodeFile]) -> dict[str, TriageDecision]:
        """
        Assess risk for multiple files in batches.
        """
        start_time = time.time()
        decisions = {}
        files_to_process = []
        
        # 1. Fast Path: Process obvious files immediately
        for cf in code_files:
            if self._is_obviously_safe(cf):
                decisions[cf.path] = self._create_decision(
                    cf, TriageLane.FAST, 0, "Hard rule: Safe file type/content", start_time
                )
            else:
                files_to_process.append(cf)
        
        if not files_to_process:
            return decisions
            
        # 2. Batch Processing for remaining files
        # Estimate max files per batch based on content length
        # Avg file (truncated) = 1500 chars ~ 400 tokens
        # Context limit ~ 8000 (usually) -> Safe batch ~ 10-15 files
        BATCH_SIZE = 10
        chunks = [files_to_process[i:i + BATCH_SIZE] for i in range(0, len(files_to_process), BATCH_SIZE)]
        
        for chunk in chunks:
            try:
                batch_scores = await self._get_llm_batch_score_async(chunk)
                
                for cf in chunk:
                    # Match score or fallback
                    risk = batch_scores.get(cf.path)
                    if not risk:
                        # Fallback
                        logger.warning("triage_batch_missing_file", file=cf.path)
                        decisions[cf.path] = self._create_decision(
                            cf, TriageLane.MIDDLE, 5, "Batch fallback: Missing from LLM response", start_time
                        )
                    else:
                        lane = self._determine_lane(risk)
                        decisions[cf.path] = TriageDecision(
                            file_path=str(cf.path),
                            lane=lane,
                            risk_score=risk,
                            processing_time_ms=(time.time() - start_time) * 1000
                        )
            except Exception as e:
                logger.error("triage_batch_failed", error=str(e), chunk_size=len(chunk))
                # Fallback for entire chunk
                for cf in chunk:
                    decisions[cf.path] = self._create_decision(
                        cf, TriageLane.MIDDLE, 5, f"Batch error: {str(e)}", start_time
                    )
                    
        return decisions

    async def _get_llm_batch_score_async(self, code_files: list[CodeFile]) -> dict[str, RiskScore]:
        """Calls Local LLM to get risk scores for multiple files."""
        # Prepare batch prompt
        files_context = []
        for cf in code_files:
            # Truncate content specifically for triage context (imports usually enough for risk)
            # 1500 chars is plenty for triage
            content_snippet = cf.content[:1500].replace("```", "'''") 
            files_context.append(f"FILE: {cf.path}\nCODE:\n```{cf.language}\n{content_snippet}\n```\n---")
            
        context_str = "\n".join(files_context)
        
        prompt = f"""Analyze the following {len(code_files)} files.
        
FILES_TO_ANALYZE:
{context_str}

Respond with a JSON map where keys are file paths and values are risk objects.
Example:
{{
  "path/to/file.py": {{ "score": 3.0, "confidence": 0.9, "category": "DTO", "reasoning": "Simple data class" }},
  ...
}}
"""
        request = LlmRequest(
            system_prompt=self.SYSTEM_PROMPT + "\nIMPORTANT: Output a JSON MAP of file paths to risk objects.",
            user_message=prompt,
            use_fast_tier=True,
            temperature=0.1,
            max_tokens=2000 # Increased for batch output
        )
        
        response = await self.llm.send_async(request)
        
        if not response.success:
            raise RuntimeError(f"LLM batch failed: {response.error_message}")
            
        return self._parse_batch_response(response.content)

    def _parse_batch_response(self, content: str) -> dict[str, RiskScore]:
        """Parses batch JSON response."""
        try:
            json_str = self._extract_json(content)
            data = json.loads(json_str)
            
            results = {}
            for path, score_data in data.items():
                try:
                    # Normalize keys if needed (LLM might lowercase them)
                    if "risk_score" in score_data: score_data = score_data["risk_score"]
                    results[path] = RiskScore(**score_data)
                except Exception as e:
                    logger.warning("triage_batch_item_parse_failed", path=path, error=str(e))
                    results[path] = RiskScore(score=5, confidence=0, reasoning="Parse Error", category="error")
            
            return results
        except Exception as e:
            logger.error("triage_batch_json_parse_failed", error=str(e), content=content[:200])
            raise e

    def _is_obviously_safe(self, code_file: CodeFile) -> bool:
        """Heuristics to skip LLM entirely for obvious files."""
        path = str(code_file.path).lower()
        
        # Safe extensions
        if path.endswith(('.md', '.txt', '.json', '.yaml', '.yml', '.css', '.scss', '.html', '.xml', '.csv', '.lock')):
            return True
            
        # Safe directories
        if any(x in path for x in ['/tests/', '/test/', '/docs/', '/migrations/', '/node_modules/', '/dist/', '/build/']):
            return True

        if 'config' in path or 'settings' in path:
            return True
            
        # Small files
        if len(code_file.content) < 300: 
            return True
            
        # Complexity Heuristic (Simple line count proxy)
        if hasattr(code_file, 'line_count') and code_file.line_count < 30:
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
