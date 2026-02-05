"""
Fortification Phase Executor.
"""

import time
import traceback
from typing import List, Any

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import CodeFile
from warden.shared.infrastructure.logging import get_logger
from warden.pipeline.application.executors.base_phase_executor import BasePhaseExecutor

logger = get_logger(__name__)


def fort_get(obj: Any, key: str, default: Any = None) -> Any:
    """Helper to safely get values from both dicts and objects."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class FortificationExecutor(BasePhaseExecutor):
    """Executor for the FORTIFICATION phase."""

    async def execute_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute FORTIFICATION phase."""
        logger.info("executing_phase", phase="FORTIFICATION")

        if self.progress_callback:
            start_time = time.perf_counter()
            self.progress_callback("phase_started", {
                "phase": "FORTIFICATION",
                "phase_name": "FORTIFICATION"
            })

        try:
            from warden.fortification.application.fortification_phase import FortificationPhase

            # Get context from previous phases
            phase_context = context.get_context_for_phase("FORTIFICATION")

            # Skip if disabled in config
            if not getattr(self.config, 'enable_fortification', True):
                logger.info("fortification_phase_disabled_via_config")
                return

            # Respect global use_llm flag
            llm_service = self.llm_service if getattr(self.config, 'use_llm', True) else None

            phase = FortificationPhase(
                config=getattr(self.config, 'fortification_config', {}),
                context=phase_context,
                llm_service=llm_service,
                semantic_search_service=self.semantic_search_service,
                rate_limiter=self.rate_limiter
            )

            # Use findings from context (whether validated or raw)
            raw_findings = getattr(context, 'findings', []) or []
            
            # Convert objects to dicts expected by FortificationPhase
            validated_issues = []
            for f in raw_findings:
                # Handle Finding object or dict
                if hasattr(f, 'to_json'):
                    # Parse location for file path
                    file_path = f.location.split(':')[0] if f.location else ""
                    
                    # Map Finding object to Fortification Dictionary Contract
                    issue = {
                        "id": f.id,
                        "type": f.id.split('-')[0] if '-' in f.id else "issue", # Heuristic for type from ID
                        "severity": f.severity,
                        "message": f.message,
                        "detail": f.detail,
                        "file_path": file_path,
                        "line_number": f.line,
                        "code_snippet": f.code
                    }
                    validated_issues.append(issue)
                elif isinstance(f, dict):
                     validated_issues.append(f)

            if validated_issues is None:
                validated_issues = []

            result = await phase.execute_async(validated_issues)

            # Store results in context
            context.fortifications = result.fortifications
            context.applied_fixes = result.applied_fixes
            context.security_improvements = result.security_improvements

            # Link Fortifications back to Findings for Reporting
            from warden.validation.domain.frame import Remediation
            
            # Create a lookup for findings
            findings_map = {f.id: f for f in context.findings}
            
            for fort in result.fortifications:
                # Handle both object and dict (including camelCase from to_json)
                if isinstance(fort, dict):
                    fid = fort.get('finding_id') or fort.get('findingId')
                    title = fort.get('title', 'Security Fix')
                    suggested_code = fort.get('suggested_code') or fort.get('suggestedCode')
                    original_code = fort.get('original_code') or fort.get('originalCode')
                else:
                    fid = getattr(fort, 'finding_id', None)
                    title = getattr(fort, 'title', 'Security Fix')
                    suggested_code = getattr(fort, 'suggested_code', None)
                    original_code = getattr(fort, 'original_code', None)

                if fid and fid in findings_map:
                    finding = findings_map[fid]
                    # Create Remediation object (matching dataclass field names)
                    remediation = Remediation(
                        description=title,
                        code=suggested_code or "",
                        unified_diff=None # Can be generated if original_code exists
                    )
                    
                    # Log diff generation attempt
                    if original_code and suggested_code:
                         try:
                             import difflib
                             diff = difflib.unified_diff(
                                 original_code.splitlines(),
                                 suggested_code.splitlines(),
                                 fromfile='original',
                                 tofile='fixed',
                                 lineterm=''
                             )
                             remediation.unified_diff = '\n'.join(list(diff))
                         except (ValueError, TypeError, RuntimeError):  # Fortification isolated
                             pass
                    
                    # Assign to finding
                    finding.remediation = remediation

            # Add phase result
            context.add_phase_result("FORTIFICATION", {
                "fortifications_count": len(result.fortifications),
                "critical_fixes": len([
                    f for f in result.fortifications 
                    if fort_get(f, "severity") == "critical"
                ]),
                "auto_fixable": len([
                    f for f in result.fortifications 
                    if fort_get(f, "auto_fixable") or fort_get(f, "autoFixable")
                ]),
            })

            logger.info(
                "phase_completed",
                phase="FORTIFICATION",
                fortifications=len(result.fortifications),
            )

        except Exception as e:
            logger.error("phase_failed",
                        phase="FORTIFICATION",
                        error=str(e),
                        error_type=type(e).__name__,
                        traceback=traceback.format_exc())
            context.errors.append(f"FORTIFICATION failed: {str(e)}")

        if self.progress_callback:
            duration = time.perf_counter() - start_time
            fortification_data = {
                "phase": "FORTIFICATION",
                "phase_name": "FORTIFICATION",
                "duration": duration
            }
            # Check if LLM was used in this phase
            if self.llm_service and hasattr(context, 'fortifications') and context.fortifications:
                 fortification_data["llm_used"] = True
                 fortification_data["fixes_generated"] = len(context.fortifications)
            
            self.progress_callback("phase_completed", fortification_data)
