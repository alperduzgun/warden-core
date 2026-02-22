"""
Fortification Phase Executor.
"""

import time
import traceback
from typing import Any

from warden.pipeline.application.executors.base_phase_executor import BasePhaseExecutor
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.logging import get_logger
from warden.shared.utils.finding_utils import get_finding_attribute
from warden.validation.domain.frame import CodeFile

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
        code_files: list[CodeFile],
    ) -> None:
        """Execute FORTIFICATION phase."""
        logger.info("executing_phase", phase="FORTIFICATION")

        start_time = time.perf_counter()

        def _emit(status: str) -> None:
            if self.progress_callback:
                self.progress_callback("progress_update", {"status": status})

        try:
            from warden.fortification.application.fortification_phase import FortificationPhase

            # Get context from previous phases
            phase_context = context.get_context_for_phase("FORTIFICATION")

            # Skip if disabled in config
            if not getattr(self.config, "enable_fortification", True):
                logger.info("fortification_phase_disabled_via_config")
                return

            # Respect global use_llm flag
            llm_service = self.llm_service if getattr(self.config, "use_llm", True) else None

            phase = FortificationPhase(
                config=getattr(self.config, "fortification_config", {}),
                context=phase_context,
                llm_service=llm_service,
                semantic_search_service=self.semantic_search_service,
                rate_limiter=self.rate_limiter,
            )

            # Use validated_issues (FP-filtered) instead of raw findings (Tier 1: Context-Awareness)
            # ResultAggregator already filters false positives and creates validated_issues
            raw_findings = getattr(context, "validated_issues", [])

            # Fallback to findings if validated_issues not available (shouldn't happen in normal flow)
            if not raw_findings:
                raw_findings = getattr(context, "findings", []) or []
                logger.warning(
                    "fortification_using_raw_findings",
                    reason="validated_issues_empty",
                    findings_count=len(raw_findings),
                )

            # Convert objects to dicts expected by FortificationPhase (BATCH 1: Type Safety)
            _emit(f"Normalizing {len(raw_findings)} findings for patch generation")
            from warden.pipeline.application.orchestrator.result_aggregator import normalize_finding_to_dict

            normalization_success = 0
            normalization_failures = []

            validated_issues = []
            for f in raw_findings:
                try:
                    # Normalize all findings to dicts (handles both Finding objects and dicts)
                    normalized = normalize_finding_to_dict(f)

                    # BATCH 3: Validate contract fields
                    required_fields = ["id", "severity", "message", "file_path"]
                    missing_fields = [field for field in required_fields if not normalized.get(field)]

                    if missing_fields:
                        logger.warning(
                            "finding_missing_fields",
                            finding_id=normalized.get("id", "unknown"),
                            missing_fields=missing_fields,
                        )
                        normalization_failures.append(normalized.get("id", "unknown"))
                        continue

                    # Map to Fortification Dictionary Contract
                    issue = {
                        "id": normalized.get("id", "unknown"),
                        "type": normalized.get("type", "unknown"),
                        "severity": normalized.get("severity", "low"),
                        "message": normalized.get("message", ""),
                        "detail": normalized.get("message", ""),  # Use message as detail if detail not present
                        "file_path": normalized.get("file_path", "unknown"),
                        "line_number": int(normalized.get("location", "unknown:0").split(":")[-1])
                        if ":" in normalized.get("location", "unknown:0")
                        else 0,
                        "code_snippet": normalized.get("code_snippet", ""),
                    }
                    validated_issues.append(issue)
                    normalization_success += 1
                except Exception as e:
                    normalization_failures.append(get_finding_attribute(f, "id", "unknown"))
                    logger.error("finding_normalization_exception", error=str(e))

            # BATCH 3: Log normalization summary
            if normalization_failures:
                logger.info(
                    "fortification_normalization_summary",
                    success=normalization_success,
                    failures=len(normalization_failures),
                    failure_ids=normalization_failures[:5],
                )

            if not validated_issues:
                logger.info("fortification_skipped", reason="no_findings_to_fortify")
                context.add_phase_result(
                    "FORTIFICATION",
                    {
                        "fortifications_count": 0,
                        "critical_fixes": 0,
                        "auto_fixable": 0,
                    },
                )
                return

            _emit(f"Generating fix patches for {len(validated_issues)} issues")
            result = await phase.execute_async(validated_issues)

            # Store results in context
            context.fortifications = result.fortifications
            context.applied_fixes = result.applied_fixes
            context.security_improvements = result.security_improvements

            # Link Fortifications back to Findings for Reporting
            # Build map from the same validated_issues sent to LLM (guarantees ID match)
            findings_map = {}
            for issue in validated_issues:
                fid = issue.get("id", "unknown")
                if fid in findings_map:
                    logger.warning(
                        "fortification_duplicate_finding_id",
                        finding_id=fid,
                    )
                findings_map[fid] = issue

            # BATCH 3: Track fortification linking metrics
            linked_count = 0
            unlinked_count = 0
            unlinked_ids = []

            for fort in result.fortifications:
                # Handle both object and dict (including camelCase from to_json)
                if isinstance(fort, dict):
                    fid = fort.get("finding_id") or fort.get("findingId")
                    title = fort.get("title", "Security Fix")
                    suggested_code = fort.get("suggested_code") or fort.get("suggestedCode")
                    original_code = fort.get("original_code") or fort.get("originalCode")
                else:
                    fid = getattr(fort, "finding_id", None)
                    title = getattr(fort, "title", "Security Fix")
                    suggested_code = getattr(fort, "suggested_code", None)
                    original_code = getattr(fort, "original_code", None)

                if fid and fid in findings_map:
                    # BATCH 3: Track successful linking
                    linked_count += 1
                    finding = findings_map[fid]

                    # Generate unified diff if both code versions available
                    unified_diff = None
                    if original_code and suggested_code:
                        try:
                            import difflib

                            diff = difflib.unified_diff(
                                original_code.splitlines(),
                                suggested_code.splitlines(),
                                fromfile="original",
                                tofile="fixed",
                                lineterm="",
                            )
                            unified_diff = "\n".join(list(diff))
                        except (ValueError, TypeError, RuntimeError):  # Fortification isolated
                            pass

                    # Assign remediation (dict-compatible — findings_map contains dicts)
                    finding["remediation"] = {
                        "description": title,
                        "code": suggested_code or "",
                        "unified_diff": unified_diff,
                    }
                else:
                    # BATCH 3: Track unlinked fortifications
                    unlinked_count += 1
                    unlinked_ids.append(fid)
                    logger.warning(
                        "fortification_unlinked",
                        fortification_id=fid,
                        reason="finding_not_in_map",
                    )

            # Add phase result (BATCH 3: Include linking metrics)
            total_forts = len(result.fortifications)
            link_success_rate = linked_count / max(1, total_forts) if total_forts > 0 else 0.0
            context.add_phase_result(
                "FORTIFICATION",
                {
                    "fortifications_total": total_forts,
                    "fortifications_linked": linked_count,
                    "fortifications_unlinked": unlinked_count,
                    "link_success_rate": round(link_success_rate, 3),
                    "critical_fixes": len([f for f in result.fortifications if fort_get(f, "severity") == "critical"]),
                    "auto_fixable": len(
                        [f for f in result.fortifications if fort_get(f, "auto_fixable") or fort_get(f, "autoFixable")]
                    ),
                },
            )

            logger.info(
                "phase_completed",
                phase="FORTIFICATION",
                fortifications=len(result.fortifications),
            )

        except Exception as e:
            logger.error(
                "phase_failed",
                phase="FORTIFICATION",
                error=str(e),
                error_type=type(e).__name__,
                traceback=traceback.format_exc(),
            )
            context.errors.append(f"FORTIFICATION failed: {e!s}")

        if self.progress_callback:
            duration = time.perf_counter() - start_time
            fortification_data = {"phase": "FORTIFICATION", "phase_name": "FORTIFICATION", "duration": duration}
            # Check if LLM was used in this phase
            if self.llm_service and hasattr(context, "fortifications") and context.fortifications:
                fortification_data["llm_used"] = True
                fortification_data["fixes_generated"] = len(context.fortifications)

            self.progress_callback("phase_completed", fortification_data)
