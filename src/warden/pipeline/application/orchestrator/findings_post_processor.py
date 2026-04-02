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


def _deduplicate_by_id(findings: list[Any]) -> list[Any]:
    """Lightweight dedup by finding ID + location to prevent re-sync inflation."""
    seen: set[str] = set()
    result: list[Any] = []
    for f in findings:
        fid = get_finding_attribute(f, "id", "")
        loc = get_finding_attribute(f, "location", "")
        key = f"{fid}:{loc}"
        if key not in seen:
            seen.add(key)
            result.append(f)
    return result


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

        # Attribute LLM calls in this phase to "verification" scope
        from warden.llm.metrics import get_global_metrics_collector

        metrics_collector = get_global_metrics_collector()

        with metrics_collector.frame_scope("verification"):
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
                        # Skip LLM verification for frames that declared supports_verification=False.
                        # These frames produce factual/structural findings (dead code, property violations,
                        # architectural gaps) that the security-focused verifier incorrectly rejects.
                        frame_supports_verification = (result_obj.metadata or {}).get("supports_verification", True)
                        if not frame_supports_verification:
                            logger.info(
                                "verification_skipped_frame_opt_out",
                                frame_id=frame_id,
                                findings_count=len(result_obj.findings),
                            )
                            verified_count += len(result_obj.findings)
                            continue

                        # Split: LLM-independent findings bypass verification (already LLM-analysed).
                        auto_verified = []
                        needs_verify = []
                        for f in result_obj.findings:
                            ds = f.detection_source if hasattr(f, "detection_source") else (f.get("detection_source") if isinstance(f, dict) else None)
                            if ds == "llm_independent":
                                auto_verified.append(f)
                            else:
                                needs_verify.append(f)

                        if auto_verified:
                            logger.info("verification_auto_pass_llm_independent", frame_id=frame_id, count=len(auto_verified))

                        findings_to_verify = [f.to_dict() if hasattr(f, "to_dict") else f for f in needs_verify]
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

                        final_findings = list(auto_verified)  # LLM-independent auto-pass
                        cached_count = 0

                        for f in needs_verify:
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

                        dropped = len(needs_verify) - len([f for f in final_findings if f not in auto_verified])
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
                        getattr(f, "id", None) or (f.get("id") if isinstance(f, dict) else None)
                        for f in context.findings
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

    def suppress_learned_false_positives(self, context: PipelineContext) -> None:
        """
        Pre-filter step: suppress findings that match learned FP patterns.

        Patterns are loaded once from .warden/learned_patterns.yaml.  A
        finding is suppressed when a pattern with confidence >= 0.8
        (occurrence_count >= 2) matches on all three of:
          - rule_id equality
          - file_path contains pattern.file_pattern (relative substring)
          - message contains pattern.message_pattern (substring)

        Logs a single ``learned_fp_suppressed`` event with the total count.
        """
        try:
            from warden.classification.application.llm_classification_phase import (
                LLMClassificationPhase,
            )

            patterns = LLMClassificationPhase._load_learned_patterns(self.project_root)
        except Exception as exc:
            logger.warning("learned_patterns_load_error", error=str(exc))
            return

        if not patterns:
            return

        # Only keep FP patterns with enough confidence to auto-suppress
        fp_patterns = [
            p for p in patterns
            if p.get("type") == "false_positive" and p.get("confidence", 0.0) >= 0.8
        ]
        if not fp_patterns:
            return

        total_suppressed = 0

        for _fid, f_res in context.frame_results.items():
            result_obj = f_res.get("result")
            if not result_obj or not result_obj.findings:
                continue

            filtered_findings = []
            for finding in result_obj.findings:
                rule_id = (
                    getattr(finding, "id", None)
                    or getattr(finding, "rule_id", None)
                    or (finding.get("id") if isinstance(finding, dict) else None)
                    or ""
                )
                file_path = (
                    getattr(finding, "file_path", None)
                    or getattr(finding, "path", None)
                    or getattr(finding, "location", None)  # Finding.location = "path:line"
                    or (finding.get("file_path") if isinstance(finding, dict) else None)
                    or (finding.get("location") if isinstance(finding, dict) else None)
                    or ""
                )
                message = (
                    getattr(finding, "message", None)
                    or (finding.get("message") if isinstance(finding, dict) else None)
                    or ""
                )

                suppressed = False
                for pat in fp_patterns:
                    pat_rule = pat.get("rule_id", "")
                    pat_file = pat.get("file_pattern", "")
                    pat_msg = pat.get("message_pattern", "")

                    rule_match = (not pat_rule) or (pat_rule == rule_id)
                    file_match = (not pat_file) or (pat_file in str(file_path))
                    msg_match = (not pat_msg) or (pat_msg in str(message))

                    if rule_match and file_match and msg_match:
                        suppressed = True
                        break

                if suppressed:
                    total_suppressed += 1
                else:
                    filtered_findings.append(finding)

            if len(filtered_findings) < len(result_obj.findings):
                result_obj.findings = filtered_findings
                result_obj.issues_found = len(filtered_findings)

                if (
                    not filtered_findings
                    and getattr(result_obj, "status", None) == "failed"
                    and not self._has_blocker_violations(result_obj)
                ):
                    result_obj.status = "passed"

        if total_suppressed > 0:
            logger.info("learned_fp_suppressed", count=total_suppressed)

            # Sync context.findings
            all_findings: list[Any] = []
            for f_res in context.frame_results.values():
                res = f_res.get("result")
                if res and res.findings:
                    all_findings.extend(res.findings)
            context.findings = _deduplicate_by_id(all_findings)

    def _resolve_baseline_path(self) -> Path:
        """Resolve the baseline file path from warden config, with fallback to default."""
        for config_candidate in [
            self.project_root / ".warden" / "config.yaml",
            self.project_root / "warden.yaml",
        ]:
            if config_candidate.exists():
                try:
                    import yaml

                    with open(config_candidate) as f:
                        raw = yaml.safe_load(f) or {}
                    raw_path = raw.get("baseline", {}).get("path", ".warden/baseline.json")
                    return self.project_root / raw_path
                except Exception:
                    pass
        return self.project_root / ".warden" / "baseline.json"

    def apply_baseline(self, context: PipelineContext) -> None:
        """Filter out existing issues present in baseline (legacy + module-based)."""
        baseline_path = self._resolve_baseline_path()
        baseline_dir = self.project_root / ".warden" / "baseline"

        if not baseline_path.exists() and not baseline_dir.is_dir():
            return

        settings = getattr(self.config, "settings", {})
        if settings.get("mode") == "strict" and not settings.get("use_baseline_in_strict", False):
            pass

        try:
            from warden.cli.commands.helpers.baseline_manager import (
                BaselineManager,
                _compute_finding_fingerprint,
            )

            known_fingerprints: set[str] = set()

            # Load from module-based baseline (v2.0) first
            baseline_dir = self.project_root / ".warden" / "baseline"
            if baseline_dir.is_dir():
                mgr = BaselineManager(self.project_root)
                known_fingerprints = mgr.get_fingerprints()
                logger.info("baseline_loaded_v2", fingerprints=len(known_fingerprints), source="module-based")

            # Fallback: load from legacy baseline.json
            if not known_fingerprints and baseline_path.exists():
                with open(baseline_path) as f:
                    baseline_data = json.load(f)
                for frame_res in baseline_data.get("frame_results", baseline_data.get("frameResults", [])):
                    for finding in frame_res.get("findings", []):
                        fp = _compute_finding_fingerprint(finding)
                        if fp:
                            known_fingerprints.add(fp)
                logger.info("baseline_loaded_legacy", fingerprints=len(known_fingerprints), source="legacy")

            if not known_fingerprints:
                return

            # Snapshot ALL findings before filtering — quality score uses this
            context.all_findings_pre_baseline = list(context.findings) if context.findings else []

            total_suppressed = 0
            baseline_suppressed_list: list[dict] = []

            for _fid, f_res in context.frame_results.items():
                result_obj = f_res.get("result")
                if not result_obj or not result_obj.findings:
                    continue

                filtered_findings = []
                for finding in result_obj.findings:
                    # Build dict for canonical fingerprint
                    f_dict = finding if isinstance(finding, dict) else {
                        "id": getattr(finding, "id", getattr(finding, "rule_id", "")),
                        "file_path": getattr(finding, "file_path", getattr(finding, "path", "")),
                        "message": getattr(finding, "message", ""),
                        "location": getattr(finding, "location", ""),
                        "severity": getattr(finding, "severity", "medium"),
                    }
                    fp = _compute_finding_fingerprint(f_dict)

                    if fp in known_fingerprints:
                        total_suppressed += 1
                        baseline_suppressed_list.append(f_dict)
                    else:
                        filtered_findings.append(finding)

                result_obj.findings = filtered_findings

                if (
                    not filtered_findings
                    and result_obj.status == "failed"
                    and not self._has_blocker_violations(result_obj)
                ):
                    result_obj.status = "passed"

            context.baseline_suppressed_count = total_suppressed
            context.baseline_suppressed_findings = baseline_suppressed_list

            if total_suppressed > 0:
                logger.info("baseline_applied", suppressed_issues=total_suppressed)

                all_findings = []
                for f_res in context.frame_results.values():
                    res = f_res.get("result")
                    if res and res.findings:
                        all_findings.extend(res.findings)
                context.findings = _deduplicate_by_id(all_findings)

                # CRITICAL: sync validated_issues so downstream phases
                # (Fortification, SARIF) operate on the filtered set.
                # Without this, fortification generates patches for
                # findings the user already accepted as technical debt.
                # validated_issues holds dicts, so match by rule_id:path key.
                if hasattr(context, "validated_issues") and context.validated_issues:
                    before_count = len(context.validated_issues)
                    context.validated_issues = [
                        vf for vf in context.validated_issues
                        if _compute_finding_fingerprint(vf) not in known_fingerprints
                    ]
                    logger.info(
                        "baseline_validated_issues_synced",
                        before=before_count,
                        after=len(context.validated_issues),
                        suppressed=before_count - len(context.validated_issues),
                    )

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

    def filter_by_diff_lines(self, context: PipelineContext) -> None:
        """
        Filter findings to only those on changed lines (diff-mode post-filter).

        If context.changed_lines is empty, skip — this is full-scan mode.
        Findings whose file appears in changed_lines but whose line is NOT in the
        changed set are removed. Findings in files NOT listed in changed_lines
        pass through unchanged (those files were scanned in full-scan context).
        """
        if not context.changed_lines:
            return

        total_filtered = 0

        for _fid, f_res in context.frame_results.items():
            result_obj = f_res.get("result")
            if not result_obj:
                continue

            current_findings = result_obj.findings
            if not current_findings:
                continue

            filtered_findings = []
            for finding in current_findings:
                # Extract file path from the finding
                fpath = getattr(finding, "file_path", None) or getattr(finding, "path", None)
                if fpath is None:
                    # Try parsing location string: "some/file.py:45"
                    location = getattr(finding, "location", "") or ""
                    if ":" in location:
                        fpath = location.rsplit(":", 1)[0]

                if fpath is None:
                    # Cannot determine file — pass through
                    filtered_findings.append(finding)
                    continue

                rel_path = self._normalize_path(str(fpath))

                if rel_path not in context.changed_lines:
                    # File not in diff map — pass through (full-scan file)
                    filtered_findings.append(finding)
                    continue

                # File is in diff map — only keep if line is changed
                line_num = getattr(finding, "line", 0)
                if line_num == 0:
                    # Try parsing line from location string
                    location = getattr(finding, "location", "") or ""
                    if ":" in location:
                        try:
                            line_num = int(location.rsplit(":", 1)[1])
                        except (ValueError, IndexError):
                            line_num = 0

                if line_num == 0 or line_num in context.changed_lines[rel_path]:
                    filtered_findings.append(finding)
                else:
                    total_filtered += 1

            if len(filtered_findings) < len(current_findings):
                result_obj.findings = filtered_findings
                result_obj.issues_found = len(filtered_findings)

                if (
                    not filtered_findings
                    and getattr(result_obj, "status", None) == "failed"
                    and not self._has_blocker_violations(result_obj)
                ):
                    result_obj.status = "passed"

        if total_filtered > 0:
            logger.info("diff_line_filter_applied", filtered_count=total_filtered)

            # Sync context.findings after line-level filtering
            all_findings: list[Any] = []
            for f_res in context.frame_results.values():
                res = f_res.get("result")
                if res and res.findings:
                    all_findings.extend(res.findings)
            context.findings = _deduplicate_by_id(all_findings)

    def _normalize_path(self, fpath: str) -> str:
        """Normalize a file path relative to project root."""
        try:
            abs_path = Path(fpath)
            if not abs_path.is_absolute():
                abs_path = self.project_root / fpath
            return str(abs_path.resolve().relative_to(self.project_root.resolve()))
        except (ValueError, OSError):
            return str(fpath)
