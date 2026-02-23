"""Post-processing for pipeline findings: verification, baseline, and state consistency."""

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from warden.analysis.services.finding_verifier import FindingVerificationService
from warden.llm.factory import create_client
from warden.pipeline.domain.enums import PipelineStatus
from warden.pipeline.domain.models import PipelineConfig, ValidationPipeline
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.error_handler import async_error_handler
from warden.shared.infrastructure.logging import get_logger
from warden.shared.utils.finding_utils import get_finding_attribute

logger = get_logger(__name__)


class FindingsPostProcessor:
    """Verification, baseline filtering, and state consistency for pipeline findings."""

    def __init__(
        self,
        config: PipelineConfig,
        project_root: Path,
        llm_service: Any | None = None,
        progress_callback: Callable | None = None,
    ):
        self.config = config
        self.project_root = project_root
        self.llm_service = llm_service
        self._progress_callback = progress_callback

    @property
    def progress_callback(self) -> Callable | None:
        return self._progress_callback

    @progress_callback.setter
    def progress_callback(self, value: Callable | None) -> None:
        self._progress_callback = value

    @async_error_handler(
        fallback_value=None,
        log_level="warning",
        context_keys=["pipeline_id"],
        reraise=False,
    )
    async def verify_findings_async(self, context: PipelineContext) -> None:
        """
        LLM-based false positive reduction (Phase 3.5: Verification).

        Uses centralized error handler to prevent verification failures from blocking pipeline.
        """
        logger.info("phase_started", phase="VERIFICATION")

        try:
            verify_llm = self.llm_service or create_client()
            verify_mem_manager = getattr(self.config, "memory_manager", None)

            verifier = FindingVerificationService(
                llm_client=verify_llm,
                memory_manager=verify_mem_manager,
                enabled=True,
            )

            verified_count = 0
            dropped_count = 0

            for frame_id, frame_res in context.frame_results.items():
                result_obj = frame_res.get("result")
                if result_obj and result_obj.findings:
                    findings_to_verify = [f.to_dict() if hasattr(f, "to_dict") else f for f in result_obj.findings]
                    total_findings = len(findings_to_verify)

                    logger.info(
                        "finding_verification_started",
                        frame_id=frame_id,
                        findings_count=len(findings_to_verify),
                    )

                    verified_findings_dicts = await verifier.verify_findings_async(findings_to_verify, context)
                    verified_ids = {f["id"] for f in verified_findings_dicts}

                    if self._progress_callback:
                        self._progress_callback(
                            "progress_update",
                            {"increment": total_findings, "phase": f"Verified {frame_id}"},
                        )

                    final_findings = []
                    cached_count = 0

                    for f in result_obj.findings:
                        fid = f.get("id") if isinstance(f, dict) else f.id
                        if fid in verified_ids:
                            final_findings.append(f)
                            if any(
                                vf.get("verification_metadata", {}).get("cached")
                                for vf in verified_findings_dicts
                                if vf["id"] == fid
                            ):
                                cached_count += 1
                        else:
                            # Track dropped findings as false positives
                            if hasattr(context, "false_positives"):
                                context.false_positives.append(fid)

                    dropped = len(result_obj.findings) - len(final_findings)
                    dropped_count += dropped
                    verified_count += len(final_findings)

                    result_obj.findings = final_findings
                    result_obj.issues_found = len(final_findings)

                    # Correct stale frame status after FP filtering
                    # BUT preserve intentional failures (rule blocker violations)
                    if (
                        not final_findings
                        and getattr(result_obj, "status", None) == "failed"
                        and not self._has_blocker_violations(result_obj)
                    ):
                        result_obj.status = "passed"
                        logger.info(
                            "frame_status_corrected",
                            frame_id=frame_id,
                            old_status="failed",
                            new_status="passed",
                            reason="all_findings_filtered_by_verification",
                        )

                    logger.info(
                        "finding_verification_complete",
                        frame_id=frame_id,
                        total=total_findings,
                        verified=len(final_findings),
                        dropped=dropped,
                        cached=cached_count,
                    )

            # Synchronize globally in context
            all_verified = []
            for fr in context.frame_results.values():
                res = fr.get("result")
                if res and res.findings:
                    all_verified.extend(res.findings)
            context.findings = all_verified

            # Re-sync validated_issues — remove findings dropped by verification
            if context.validated_issues:
                surviving_ids = {
                    getattr(f, "id", None) or (f.get("id") if isinstance(f, dict) else None) for f in context.findings
                }
                before_count = len(context.validated_issues)
                context.validated_issues = [vi for vi in context.validated_issues if vi.get("id") in surviving_ids]
                if len(context.validated_issues) < before_count:
                    logger.info(
                        "validated_issues_synced",
                        before=before_count,
                        after=len(context.validated_issues),
                        reason="verification_filtering",
                    )

            logger.info(
                "verification_phase_completed",
                total_verified=verified_count,
                total_dropped=dropped_count,
            )

        except Exception as e:
            import traceback

            logger.warning(
                "verification_phase_failed",
                error=str(e),
                type=type(e).__name__,
                traceback=traceback.format_exc(),
            )

    def apply_baseline(self, context: PipelineContext) -> None:
        """Filter out existing issues present in baseline."""
        baseline_path = self.project_root / ".warden" / "baseline.json"

        if not baseline_path.exists():
            return

        settings = getattr(self.config, "settings", {})
        if settings.get("mode") == "strict" and not settings.get("use_baseline_in_strict", False):
            pass

        try:
            with open(baseline_path) as f:
                baseline_data = json.load(f)

            known_issues = set()
            for frame_res in baseline_data.get("frame_results", []):
                for finding in frame_res.get("findings", []):
                    rid = get_finding_attribute(finding, "rule_id")
                    fpath = get_finding_attribute(finding, "file_path") or get_finding_attribute(finding, "path")

                    if not fpath:
                        continue

                    rel_path = self._normalize_path(fpath)

                    if rid:
                        known_issues.add(f"{rid}:{rel_path}")

            if not known_issues:
                return

            logger.info("baseline_loaded", known_issues_count=len(known_issues))

            total_suppressed = 0

            for _fid, f_res in context.frame_results.items():
                result_obj = f_res.get("result")
                if not result_obj:
                    continue

                current_findings = result_obj.findings
                if not current_findings:
                    continue

                filtered_findings = []
                suppressed_in_frame = 0

                for finding in current_findings:
                    rid = getattr(finding, "rule_id", getattr(finding, "check_id", None))
                    fpath = getattr(finding, "file_path", getattr(finding, "path", str(context.file_path)))

                    rel_path = self._normalize_path(fpath)
                    key = f"{rid}:{rel_path}"

                    if key in known_issues:
                        suppressed_in_frame += 1
                        total_suppressed += 1
                    else:
                        filtered_findings.append(finding)

                result_obj.findings = filtered_findings

                if (
                    not filtered_findings
                    and result_obj.status == "failed"
                    and not self._has_blocker_violations(result_obj)
                ):
                    result_obj.status = "passed"

            if total_suppressed > 0:
                logger.info("baseline_applied", suppressed_issues=total_suppressed)

                all_findings = []
                for f_res in context.frame_results.values():
                    res = f_res.get("result")
                    if res and res.findings:
                        all_findings.extend(res.findings)
                context.findings = all_findings

        except Exception as e:
            logger.warning("baseline_application_failed", error=str(e))

    def ensure_state_consistency(
        self,
        context: PipelineContext,
        pipeline: ValidationPipeline,
    ) -> None:
        """
        Ensure pipeline context is in consistent state before returning.
        Fixes: Lying state machine (incomplete phases marked as complete).
        """
        try:
            if not pipeline.completed_at:
                pipeline.completed_at = datetime.now()

            frame_results = getattr(context, "frame_results", {})
            failed_frames = []
            passed_frames = []

            for fr_id, fr_dict in frame_results.items():
                result_obj = fr_dict.get("result")
                if not result_obj:
                    continue

                status = getattr(result_obj, "status", None)
                remaining_findings = getattr(result_obj, "findings", [])

                # Recalculate: frame marked "failed" but all findings were filtered → correct to "passed"
                # Only correct if: (a) no blocker violations, AND (b) evidence of filtering
                # (issues_found was synced to 0 by verify/baseline — if still >0, frame failed
                # for its own reasons, not because of leftover findings)
                issues_found = getattr(result_obj, "issues_found", 0)
                was_filtered = status == "failed" and not remaining_findings and issues_found == 0
                if was_filtered and not self._has_blocker_violations(result_obj):
                    result_obj.status = "passed"
                    logger.info(
                        "frame_status_corrected",
                        frame_id=fr_id,
                        old_status="failed",
                        new_status="passed",
                        reason="all_findings_filtered",
                    )
                    passed_frames.append(fr_dict)
                elif status == "failed":
                    failed_frames.append(fr_dict)
                elif status == "passed":
                    passed_frames.append(fr_dict)

            # Determine if any failed frames are blockers
            has_blocker_failures = any(getattr(fr_dict.get("result"), "is_blocker", False) for fr_dict in failed_frames)

            if failed_frames and pipeline.status == PipelineStatus.COMPLETED:
                # COMPLETED but has failures → escalate appropriately
                if has_blocker_failures:
                    pipeline.status = PipelineStatus.FAILED
                else:
                    pipeline.status = PipelineStatus.COMPLETED_WITH_FAILURES
                logger.warning(
                    "state_inconsistency_detected",
                    expected_status=pipeline.status.name,
                    actual_status="COMPLETED",
                    failed_frames=len(failed_frames),
                    has_blocker=has_blocker_failures,
                )
            elif has_blocker_failures and pipeline.status == PipelineStatus.COMPLETED_WITH_FAILURES:
                # Blocker failure in COMPLETED_WITH_FAILURES → must be FAILED
                logger.warning(
                    "state_inconsistency_detected",
                    expected_status="FAILED",
                    actual_status=pipeline.status,
                    failed_frames=len(failed_frames),
                )
                pipeline.status = PipelineStatus.FAILED
            elif not failed_frames and pipeline.status in (
                PipelineStatus.FAILED,
                PipelineStatus.COMPLETED_WITH_FAILURES,
            ):
                # All frames passed after post-filtering — correct pipeline status
                if not context.errors:
                    logger.info(
                        "pipeline_status_corrected",
                        old_status=pipeline.status.value,
                        new_status="COMPLETED",
                        reason="all_frame_findings_filtered",
                    )
                    pipeline.status = PipelineStatus.COMPLETED

            if pipeline.status == PipelineStatus.FAILED and not context.errors:
                context.errors.append("Pipeline marked FAILED but no errors recorded")

            pipeline.frames_passed = len(passed_frames)
            pipeline.frames_failed = len(failed_frames)

            logger.info(
                "state_consistency_verified",
                pipeline_id=context.pipeline_id,
                status=pipeline.status.value,
                frames_passed=pipeline.frames_passed,
                frames_failed=pipeline.frames_failed,
            )

        except Exception as e:
            logger.error("state_consistency_check_failed", error=str(e))

    @staticmethod
    def _has_blocker_violations(result_obj: Any) -> bool:
        """Check if a FrameResult was intentionally marked as failed.

        Covers three cases:
        1. Pre-rule blocker: metadata.failure_reason set
        2. Post-rule blocker: post_rule_violations with is_blocker=True
        3. Frame-level blocker: is_blocker=True on the FrameResult itself

        These must NOT be auto-corrected to "passed" by FP filtering or
        state consistency — they represent real enforcement decisions.
        """
        # Case 1: metadata failure_reason (set by pre-rule blocker path)
        metadata = getattr(result_obj, "metadata", {}) or {}
        if metadata.get("failure_reason") in (
            "pre_rules_blocker_violation",
            "post_rules_blocker_violation",
        ):
            return True

        # Case 2: actual violation lists (post-rule and combined blocker paths)
        for attr in ("pre_rule_violations", "post_rule_violations"):
            violations = getattr(result_obj, attr, None)
            if violations:
                if any(getattr(v, "is_blocker", False) for v in violations):
                    return True

        # Case 3: frame itself marked as blocker AND failed
        if getattr(result_obj, "is_blocker", False) and getattr(result_obj, "status", None) == "failed":
            return True

        return False

    def _normalize_path(self, fpath: str) -> str:
        """Normalize a file path relative to project root."""
        try:
            abs_path = Path(fpath)
            if not abs_path.is_absolute():
                abs_path = self.project_root / fpath
            return str(abs_path.resolve().relative_to(self.project_root.resolve()))
        except (ValueError, OSError):
            return str(fpath)
