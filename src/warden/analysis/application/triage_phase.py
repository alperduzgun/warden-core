"""
TRIAGE Phase Orchestrator (Phase 0.5).
Executes the Adaptive Hybrid Triage strategy.
"""

import asyncio
import time
from typing import List, Dict, Any, Optional, Callable
import structlog
from pathlib import Path


from warden.validation.domain.frame import CodeFile
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.analysis.application.triage_service import TriageService
from warden.analysis.domain.triage_models import TriageDecision, TriageLane, RiskScore
from warden.llm.factory import create_client

logger = structlog.get_logger()

class TriagePhase:
    """
    Executes Adaptive Hybrid Triage.
    Routes files to Fast/Middle/Deep lanes based on risk scores.
    """
    
    def __init__(
        self,
        project_root: Path,
        progress_callback: Optional[Callable] = None,
        config: Optional[Dict[str, Any]] = None,
        llm_service: Optional[Any] = None
    ):
        self.project_root = project_root
        self.progress_callback = progress_callback
        self.config = config or {}
        
        # Use provided LLM service or create new one (Local/Fast pref)
        self.llm_service = llm_service or create_client()
        self.triage_service = TriageService(self.llm_service)
        
    async def execute_async(
        self,
        code_files: List[CodeFile],
        pipeline_context: PipelineContext
    ) -> Dict[str, Any]:
        """Execute Triage phase."""
        start_time = time.perf_counter()
        logger.info("triage_phase_started", file_count=len(code_files))
        
        if self.progress_callback:
            self.progress_callback("triage_started", {"total_files": len(code_files)})

        decisions = {}
        
        # Parallel execution with Semaphore to avoid overwhelming Local LLM
        # Default to 5 concurrent reqs (usually safe for Ollama)
        parallel_limit = self.config.get("triage_parallel_limit", 5)
        semaphore = asyncio.Semaphore(parallel_limit)
        
        async def process_file(file: CodeFile):
            async with semaphore:
                try:
                    decision = await self.triage_service.assess_risk_async(file)
                    return file.path, decision
                except Exception as e:
                    logger.error("triage_file_failed", file=file.path, error=str(e))
                    # Fallback decision (Middle lane as safe default)
                    fallback = TriageDecision(
                        file_path=str(file.path),
                        lane=TriageLane.MIDDLE,
                        risk_score=RiskScore(
                            score=5, 
                            confidence=0.0, 
                            reasoning=f"Error fallback: {str(e)}", 
                            category="error"
                        ),
                        processing_time_ms=0.0
                    )
                    return file.path, fallback

        tasks = [process_file(f) for f in code_files]
        if tasks:
            results = await asyncio.gather(*tasks)
            
            for path, decision in results:
                decisions[str(path)] = decision.model_dump()
        
        # Update pipeline context
        pipeline_context.triage_decisions = decisions
        
        # Stats
        fast_count = sum(1 for d in decisions.values() if d['lane'] == TriageLane.FAST)
        middle_count = sum(1 for d in decisions.values() if d['lane'] == TriageLane.MIDDLE)
        deep_count = sum(1 for d in decisions.values() if d['lane'] == TriageLane.DEEP)
        
        duration = time.perf_counter() - start_time
        
        logger.info(
            "triage_phase_completed",
            duration=duration,
            fast=fast_count,
            middle=middle_count,
            deep=deep_count
        )
        
        if self.progress_callback:
            self.progress_callback("triage_completed", {
                "duration": f"{duration:.2f}s",
                "stats": {"fast": fast_count, "middle": middle_count, "deep": deep_count}
            })
            
        return decisions
