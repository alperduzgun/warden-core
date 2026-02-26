"""
Frame runner for executing validation frames.

Handles the execution of individual frames with rules and dependencies.
"""

import asyncio
import inspect
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from warden.pipeline.domain.models import FrameResult, PipelineConfig, ValidationPipeline
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.error_handler import async_error_handler
from warden.shared.infrastructure.ignore_matcher import IgnoreMatcher
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile, Finding, ValidationFrame
from warden.validation.domain.frame import FrameResult as CodeFrameResult
from warden.validation.domain.mixins import (
    BatchExecutable,
    Cleanable,
    CodeGraphAware,
    DataFlowAware,
    LSPAware,
    ProjectContextAware,
    TaintAware,
)

from .dependency_checker import DependencyChecker
from .file_filter import FileFilter
from .findings_cache import FindingsCache
from .rule_executor import RuleExecutor
from .suppression_filter import SuppressionFilter

# Per-file timeout constants (proportional to file size, Bearer-inspired).
_FILE_TIMEOUT_MIN_S: float = 10.0  # floor for cloud providers (Groq, OpenAI, etc.)
_FILE_TIMEOUT_LOCAL_S: float = 120.0  # floor for local/slow providers (Ollama, Claude Code, Codex)
_FILE_TIMEOUT_MAX_S: float = 300.0  # ceiling: raised from 90s for local LLM inference
_FILE_BYTES_PER_SECOND: int = 15_000  # conservative parse + LLM throughput rate
_LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "claude_code", "codex"})

logger = get_logger(__name__)


@dataclass
class ContextInjectionMetrics:
    """Track context injection health."""

    frames_with_pi: int = 0
    frames_with_findings: int = 0
    pi_injection_errors: int = 0
    findings_injection_errors: int = 0
    total_injection_time_ms: float = 0.0


_context_metrics = ContextInjectionMetrics()


class FrameRunner:
    """Executes individual validation frames with rules and dependencies."""

    def __init__(
        self,
        config: PipelineConfig | None = None,
        progress_callback: Callable | None = None,
        rule_executor: RuleExecutor | None = None,
        llm_service: Any | None = None,
        semantic_search_service: Any | None = None,
    ):
        self.config = config or PipelineConfig()
        self.progress_callback = progress_callback
        self.rule_executor = rule_executor or RuleExecutor()
        self.llm_service = llm_service
        self.semantic_search_service = semantic_search_service
        self.ignore_matcher: IgnoreMatcher | None = None
        self._findings_cache: FindingsCache | None = None

    @async_error_handler(fallback_value=None, log_level="error", context_keys=["frame_id"], reraise=False)
    async def execute_frame_with_rules_async(
        self,
        context: PipelineContext,
        frame: ValidationFrame,
        code_files: list[CodeFile],
        pipeline: ValidationPipeline,
    ) -> FrameResult | None:
        """
        Execute a frame with PRE/POST rules.

        Uses centralized error handler to ensure frame failures are logged
        and don't crash the entire pipeline.
        """
        skip_result = DependencyChecker.check_frame_dependencies(context, frame)
        if skip_result:
            logger.info(
                "frame_skipped_dependencies",
                frame_id=frame.frame_id,
                reason=skip_result.metadata.get("skip_reason") if skip_result.metadata else "unknown",
            )
            context.frame_results[frame.frame_id] = {
                "result": skip_result,
                "pre_violations": [],
                "post_violations": [],
            }
            if self.progress_callback:
                self.progress_callback(
                    "frame_completed",
                    {
                        "frame_id": frame.frame_id,
                        "frame_name": frame.name,
                        "status": "skipped",
                        "findings": 0,
                        "duration": 0.0,
                        "skip_reason": skip_result.metadata.get("skip_reason") if skip_result.metadata else None,
                    },
                )
            return skip_result

        frame_start_time = time.perf_counter()

        if self.ignore_matcher is None:
            project_root = getattr(context, "project_root", None) or Path.cwd()
            use_gitignore = getattr(self.config, "use_gitignore", True)
            frame_ignores = self._collect_frame_ignores()
            self.ignore_matcher = IgnoreMatcher(project_root, use_gitignore=use_gitignore, frame_ignores=frame_ignores)

        frame_id = frame.frame_id
        original_count = len(code_files)
        files_for_frame = [
            cf for cf in code_files if not self.ignore_matcher.should_ignore_for_frame(Path(cf.path), frame_id)
        ]

        if len(files_for_frame) < original_count:
            logger.info(
                "frame_specific_ignore",
                frame=frame_id,
                ignored=original_count - len(files_for_frame),
                remaining=len(files_for_frame),
            )

        frame_rules = self.config.frame_rules.get(frame.frame_id) if self.config.frame_rules else None

        # Always apply triage routing so that pre-rules, frame execution, and
        # post-rules all operate on the same (triage-filtered) file set.
        files_for_frame = FileFilter.apply_triage_routing(context, frame, files_for_frame)
        code_files = files_for_frame

        # Skip frame entirely when triage routed away every file.
        # Avoids the overhead of LLM service setup, PI injection, and a
        # frame execution that would process 0 files.
        if not code_files:
            skip_result = FrameResult(
                frame_id=frame.frame_id,
                frame_name=frame.name,
                status="skipped",
                duration=time.perf_counter() - frame_start_time,
                issues_found=0,
                is_blocker=False,
                findings=[],
            )
            context.frame_results[frame.frame_id] = {
                "result": skip_result,
                "pre_violations": [],
                "post_violations": [],
            }
            if self.progress_callback:
                self.progress_callback(
                    "frame_completed",
                    {
                        "frame_id": frame.frame_id,
                        "frame_name": frame.name,
                        "status": "skipped",
                        "findings": 0,
                        "duration": skip_result.duration,
                    },
                )
            logger.info(
                "frame_skipped_triage_no_files",
                frame_id=frame.frame_id,
                frame_name=frame.name,
            )
            return skip_result

        if self.llm_service:
            frame.llm_service = self.llm_service
            # Enable agentic loop with project context
            project_root = getattr(context, "project_root", None) or Path.cwd()
            if hasattr(self.llm_service, "_project_root"):
                self.llm_service._project_root = project_root

        if self.semantic_search_service:
            frame.semantic_search_service = self.semantic_search_service

        # Inject project_intelligence for context-aware analysis (BATCH 2: Validated)
        # BATCH 3: Add metrics tracking
        if hasattr(context, "project_intelligence") and context.project_intelligence:
            pi_start_time = time.perf_counter()
            try:
                pi = context.project_intelligence

                # Validate structure before injecting
                if not isinstance(pi, object):
                    logger.warning(
                        "project_intelligence_wrong_type",
                        frame_id=frame.frame_id,
                        type=type(pi).__name__,
                        action="skipped_injection",
                    )
                    _context_metrics.pi_injection_errors += 1
                elif (
                    not hasattr(pi, "entry_points")
                    or not hasattr(pi, "auth_patterns")
                    or not hasattr(pi, "critical_sinks")
                ):
                    logger.warning(
                        "project_intelligence_incomplete",
                        frame_id=frame.frame_id,
                        has_entry_points=hasattr(pi, "entry_points"),
                        has_auth_patterns=hasattr(pi, "auth_patterns"),
                        has_critical_sinks=hasattr(pi, "critical_sinks"),
                        action="injected_anyway",
                    )
                    # Still inject it - frames can handle incomplete data
                    frame.project_intelligence = context.project_intelligence
                    _context_metrics.frames_with_pi += 1
                    injection_time_ms = (time.perf_counter() - pi_start_time) * 1000
                    _context_metrics.total_injection_time_ms += injection_time_ms
                    logger.debug(
                        "project_intelligence_injected",
                        frame_id=frame.frame_id,
                        has_entry_points=hasattr(pi, "entry_points"),
                        has_auth_patterns=hasattr(pi, "auth_patterns"),
                        injection_time_ms=injection_time_ms,
                    )
                else:
                    # Valid - inject it
                    frame.project_intelligence = context.project_intelligence
                    _context_metrics.frames_with_pi += 1
                    injection_time_ms = (time.perf_counter() - pi_start_time) * 1000
                    _context_metrics.total_injection_time_ms += injection_time_ms
                    logger.debug(
                        "project_intelligence_injected",
                        frame_id=frame.frame_id,
                        has_entry_points=bool(getattr(pi, "entry_points", [])),
                        has_auth_patterns=bool(getattr(pi, "auth_patterns", [])),
                        injection_time_ms=injection_time_ms,
                    )
            except Exception as e:
                _context_metrics.pi_injection_errors += 1
                injection_time_ms = (time.perf_counter() - pi_start_time) * 1000
                _context_metrics.total_injection_time_ms += injection_time_ms
                logger.error(
                    "project_intelligence_injection_failed",
                    frame_id=frame.frame_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    injection_time_ms=injection_time_ms,
                    action="frame_continues_without_context",
                )

        # Inject architectural directives from .warden/architecture.md (Gap 4: global directives)
        # Read once per pipeline run, not per-file. Provides human-authored architectural rules.
        project_root = getattr(context, "project_root", None) or Path.cwd()
        arch_file_candidates = [
            project_root / ".warden" / "rules" / "architecture.md",
            project_root / ".warden" / "architecture.md",
        ]
        for arch_path in arch_file_candidates:
            if arch_path.is_file():
                try:
                    arch_content = arch_path.read_text(encoding="utf-8")[:500]
                    if arch_content.strip():
                        frame.architectural_directives = arch_content.strip()
                        logger.debug(
                            "architectural_directives_injected",
                            frame_id=frame.frame_id,
                            source=str(arch_path),
                            chars=len(arch_content),
                        )
                except Exception as e:
                    logger.debug("architectural_directives_read_failed", error=str(e))
                break

        # Inject prior findings for cross-frame awareness (Tier 1: Context-Awareness)
        # BATCH 3: Add metrics tracking
        if hasattr(context, "findings") and context.findings:
            findings_start_time = time.perf_counter()
            try:
                frame.prior_findings = context.findings
                _context_metrics.frames_with_findings += 1
                injection_time_ms = (time.perf_counter() - findings_start_time) * 1000
                _context_metrics.total_injection_time_ms += injection_time_ms
                logger.debug(
                    "prior_findings_injected",
                    frame_id=frame.frame_id,
                    findings_count=len(context.findings),
                    injection_time_ms=injection_time_ms,
                )
            except Exception as e:
                _context_metrics.findings_injection_errors += 1
                injection_time_ms = (time.perf_counter() - findings_start_time) * 1000
                _context_metrics.total_injection_time_ms += injection_time_ms
                logger.error(
                    "prior_findings_injection_failed",
                    frame_id=frame.frame_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    injection_time_ms=injection_time_ms,
                )

        if isinstance(frame, ProjectContextAware):
            # Prefer the dedicated project_context field (set by pre_analysis_executor).
            # Fall back to project_type for legacy compatibility (it may hold the full object).
            project_context = getattr(context, "project_context", None) or getattr(context, "project_type", None)
            if project_context and hasattr(project_context, "service_abstractions"):
                frame.set_project_context(project_context)

        # Inject spec_analysis into SecurityFrame (Gap 1: cross-frame context)
        # SpecFrame populates project_context.spec_analysis with API contracts;
        # SecurityFrame uses it to understand business logic constraints.
        project_context = getattr(context, "project_context", None)
        if project_context and getattr(project_context, "spec_analysis", None):
            spec = project_context.spec_analysis
            if spec and isinstance(spec, dict) and spec.get("contracts"):
                frame.spec_analysis = spec
                logger.debug(
                    "spec_analysis_injected",
                    frame_id=frame.frame_id,
                    contract_count=len(spec.get("contracts", {})),
                )

        # Inject taint paths into TaintAware frames
        if isinstance(frame, TaintAware):
            if hasattr(context, "taint_paths") and context.taint_paths:
                try:
                    frame.set_taint_paths(context.taint_paths)
                    logger.debug(
                        "taint_paths_injected",
                        frame_id=frame.frame_id,
                        files_with_paths=len(context.taint_paths),
                    )
                except Exception as e:
                    logger.error(
                        "taint_injection_failed",
                        frame_id=frame.frame_id,
                        error=str(e),
                    )

        # Inject Data Dependency Graph into DataFlowAware frames
        if isinstance(frame, DataFlowAware):
            if hasattr(context, "data_dependency_graph") and context.data_dependency_graph is not None:
                try:
                    frame.set_data_dependency_graph(context.data_dependency_graph)
                    logger.debug(
                        "ddg_injected",
                        frame_id=frame.frame_id,
                        writes=len(context.data_dependency_graph.writes),
                        reads=len(context.data_dependency_graph.reads),
                    )
                except Exception as e:
                    logger.error(
                        "ddg_injection_failed",
                        frame_id=frame.frame_id,
                        error=str(e),
                    )

        # Inject LSP context into LSPAware frames
        if isinstance(frame, LSPAware):
            if hasattr(context, "chain_validation") and context.chain_validation:
                try:
                    cv = context.chain_validation
                    lsp_context = {
                        "dead_symbols": getattr(cv, "dead_symbols", []),
                        "confirmed": getattr(cv, "confirmed", 0),
                        "unconfirmed": getattr(cv, "unconfirmed", 0),
                        "lsp_available": getattr(cv, "lsp_available", False),
                        "chain_validation": cv,
                    }
                    frame.set_lsp_context(lsp_context)
                    logger.debug("lsp_context_injected", frame_id=frame.frame_id)
                except Exception as e:
                    logger.error(
                        "lsp_injection_failed",
                        frame_id=frame.frame_id,
                        error=str(e),
                    )

        # Inject CodeGraph and GapReport into CodeGraphAware frames
        if isinstance(frame, CodeGraphAware):
            if hasattr(context, "code_graph") and context.code_graph is not None:
                try:
                    frame.set_code_graph(context.code_graph, getattr(context, "gap_report", None))
                    logger.debug(
                        "code_graph_injected",
                        frame_id=frame.frame_id,
                        has_gap_report=context.gap_report is not None,
                    )
                except Exception as e:
                    logger.error(
                        "code_graph_injection_failed",
                        frame_id=frame.frame_id,
                        error=str(e),
                    )

        pre_violations = []
        if frame_rules and frame_rules.pre_rules:
            logger.info("executing_pre_rules", frame_id=frame.frame_id, rule_count=len(frame_rules.pre_rules))
            pre_violations = await self.rule_executor.execute_rules_async(frame_rules.pre_rules, code_files)

            if pre_violations and RuleExecutor.has_blocker_violations(pre_violations):
                if frame_rules.on_fail == "stop":
                    logger.error("pre_rules_failed_stopping", frame_id=frame.frame_id)

                    failure_result = FrameResult(
                        frame_id=frame.frame_id,
                        frame_name=frame.name,
                        status="failed",
                        duration=time.perf_counter() - frame_start_time,
                        issues_found=0,  # Frame did not execute; rule violations tracked separately
                        is_blocker=True,
                        findings=[],
                        pre_rule_violations=pre_violations,
                        metadata={"failure_reason": "pre_rules_blocker_violation"},
                    )

                    pipeline.frames_executed += 1
                    pipeline.frames_failed += 1

                    context.frame_results[frame.frame_id] = {
                        "result": failure_result,
                        "pre_violations": pre_violations,
                        "post_violations": [],
                    }

                    return failure_result

        if self.progress_callback:
            self.progress_callback(
                "frame_started",
                {
                    "frame_id": frame.frame_id,
                    "frame_name": frame.name,
                },
            )

        # Inject cached AST parse results into code file metadata
        if context.ast_cache:
            for cf in code_files:
                if cf.path in context.ast_cache:
                    if cf.metadata is None:
                        cf.metadata = {}
                    cf.metadata["_cached_parse_result"] = context.ast_cache[cf.path]

        # Get metrics collector for per-frame cost attribution
        from warden.llm.metrics import get_global_metrics_collector

        metrics_collector = get_global_metrics_collector()

        # Wrap the entire frame execution in frame_scope for automatic LLM attribution
        with metrics_collector.frame_scope(frame.frame_id):
            try:
                frame_findings = []
                files_scanned = 0
                execution_errors = 0

                # Lazy-initialise cross-scan findings cache
                if self._findings_cache is None:
                    _project_root = getattr(context, "project_root", None) or Path.cwd()
                    force_scan = getattr(self.config, "force_scan", False)
                    if not force_scan:
                        self._findings_cache = FindingsCache(_project_root)

                # Hoist signature check outside closure — inspect.signature is
                # expensive and the result is stable for the lifetime of the frame.
                _frame_accepts_context = "context" in inspect.signature(frame.execute_async).parameters

                async def execute_single_file_async(c_file: CodeFile) -> CodeFrameResult | None:
                    file_context = context.file_contexts.get(c_file.path)
                    if file_context and getattr(file_context, "is_unchanged", False):
                        # Only trust cache if frame was already executed in this pipeline run
                        if frame.frame_id in context.frame_results:
                            logger.debug("skipping_unchanged_file", file=c_file.path, frame=frame.frame_id)
                            return None

                    # Cross-scan findings cache: skip LLM if content unchanged since last scan
                    if self._findings_cache is not None and c_file.content:
                        cached_findings: list[Finding] | None = self._findings_cache.get_findings(
                            frame.frame_id, str(c_file.path), c_file.content
                        )
                        if cached_findings is not None:
                            logger.debug(
                                "findings_cache_hit",
                                frame=frame.frame_id,
                                file=c_file.path,
                                cached_findings=len(cached_findings),
                            )
                            if self.progress_callback:
                                self.progress_callback(
                                    "progress_update",
                                    {"increment": 1, "frame_id": frame.frame_id, "file": c_file.path, "cached": True},
                                )
                            if not cached_findings:
                                return None  # clean file — no FrameResult needed

                            # Derive status and is_blocker from the actual finding severities —
                            # never hardcode: blocker findings must remain blockers on replay.
                            has_critical = any(f.severity == "critical" for f in cached_findings)
                            has_high = any(f.severity == "high" for f in cached_findings)
                            cached_status = "failed" if has_critical else "warning"
                            cached_is_blocker = any(f.is_blocker for f in cached_findings)

                            return CodeFrameResult(
                                frame_id=frame.frame_id,
                                frame_name=frame.name,
                                status=cached_status,
                                duration=0.0,
                                issues_found=len(cached_findings),
                                is_blocker=cached_is_blocker,
                                findings=cached_findings,
                                metadata={"from_cache": True},
                            )

                    # Per-file dynamic timeout: proportional to file size with min/max bounds.
                    # Prevents a single large file from monopolising the scan budget.
                    try:
                        file_size = len(c_file.content.encode("utf-8", errors="replace")) if c_file.content else 0
                    except Exception:
                        file_size = 0

                    # Use a higher floor for local/slow providers (Ollama, Claude Code, Codex)
                    # since inference latency is 19-60s even for tiny files.
                    # WARDEN_FILE_TIMEOUT_MIN env var allows manual override.
                    _provider = str(
                        getattr(getattr(context, "llm_config", None), "provider", "")
                        or getattr(context, "llm_provider", "")
                        or os.environ.get("WARDEN_LLM_PROVIDER", "")
                    ).lower()
                    _env_min = os.environ.get("WARDEN_FILE_TIMEOUT_MIN")
                    if _env_min:
                        _timeout_min = float(_env_min)
                    elif _provider in _LOCAL_PROVIDERS:
                        _timeout_min = _FILE_TIMEOUT_LOCAL_S
                    else:
                        _timeout_min = _FILE_TIMEOUT_MIN_S

                    per_file_timeout = max(
                        _timeout_min,
                        min(file_size / _FILE_BYTES_PER_SECOND, _FILE_TIMEOUT_MAX_S),
                    )

                    try:
                        coro = (
                            frame.execute_async(c_file, context=context)
                            if _frame_accepts_context
                            else frame.execute_async(c_file)
                        )
                        result = await asyncio.wait_for(coro, timeout=per_file_timeout)

                        # Persist findings to cross-scan cache on success
                        if self._findings_cache is not None and result is not None and c_file.content:
                            self._findings_cache.put_findings(
                                frame.frame_id, str(c_file.path), c_file.content, result.findings or []
                            )

                        if self.progress_callback:
                            self.progress_callback(
                                "progress_update", {"increment": 1, "frame_id": frame.frame_id, "file": c_file.path}
                            )
                        return result
                    except asyncio.TimeoutError:
                        logger.warning(
                            "frame_file_timeout",
                            frame=frame.frame_id,
                            file=c_file.path,
                            timeout_s=per_file_timeout,
                            file_size_kb=round(file_size / 1024, 1),
                        )
                        if self.progress_callback:
                            self.progress_callback("progress_update", {"increment": 1, "error": True})
                        return None
                    except Exception as ex:
                        logger.error(
                            "frame_file_execution_error", frame=frame.frame_id, file=c_file.path, error=str(ex)
                        )
                        if self.progress_callback:
                            self.progress_callback("progress_update", {"increment": 1, "error": True})
                        return None

                if code_files:
                    if len(code_files) > 1:
                        logger.debug(
                            "frame_batch_execution_start", frame_id=frame.frame_id, files_to_scan=len(code_files)
                        )

                    files_to_scan = []
                    cached_files = 0

                    for cf in code_files:
                        ctx = context.file_contexts.get(cf.path)
                        if ctx and getattr(ctx, "is_unchanged", False):
                            cached_files += 1
                            logger.debug("skipping_unchanged_file_batch", file=cf.path, frame=frame.frame_id)
                        else:
                            files_to_scan.append(cf)

                    if cached_files > 0:
                        log_func = logger.info if len(files_to_scan) > 0 else logger.debug
                        log_func(
                            "smart_caching_active",
                            skipped=cached_files,
                            remaining=len(files_to_scan),
                            frame=frame.frame_id,
                        )

                        if self.progress_callback:
                            self.progress_callback(
                                "progress_update",
                                {
                                    "increment": cached_files,
                                    "frame_id": frame.frame_id,
                                    "details": f"Skipped {cached_files} cached files",
                                },
                            )

                    if not files_to_scan:
                        # Only trust cache if this frame was previously executed in this pipeline run.
                        # On first run, stale cache state (e.g. from a different scan context) can cause
                        # all files to appear unchanged, leading to 0 findings and a false "passed" status.
                        frame_was_run = frame.frame_id in context.frame_results
                        if frame_was_run:
                            logger.debug("all_files_cached_skipping_batch", frame=frame.frame_id)
                            f_results = []
                        else:
                            logger.info(
                                "cache_override_first_run",
                                frame=frame.frame_id,
                                reason="no prior results in this pipeline run",
                            )
                            files_to_scan = list(code_files)

                    if files_to_scan:
                        try:
                            if isinstance(frame, BatchExecutable):
                                f_results = []
                                total_files_to_scan = len(files_to_scan)
                                CHUNK_SIZE = 5

                                for i in range(0, total_files_to_scan, CHUNK_SIZE):
                                    chunk = files_to_scan[i : i + CHUNK_SIZE]
                                    chunk_results = await asyncio.wait_for(
                                        frame.execute_batch_async(chunk),
                                        timeout=getattr(self.config, "frame_timeout", 300.0),
                                    )
                                    if chunk_results:
                                        f_results.extend(chunk_results)
                                        if self.progress_callback:
                                            self.progress_callback(
                                                "progress_update",
                                                {
                                                    "increment": len(chunk_results),
                                                    "frame_id": frame.frame_id,
                                                    "phase": f"Validating {frame.name}",
                                                },
                                            )
                            else:
                                f_results = []
                                for cf in files_to_scan:
                                    result = await execute_single_file_async(cf)
                                    if result:
                                        f_results.append(result)

                            if isinstance(frame, Cleanable):
                                await frame.cleanup()

                            if f_results:
                                files_scanned = len(f_results)
                                total_findings_from_batch = sum(
                                    len(res.findings) if res and res.findings else 0 for res in f_results
                                )

                                logger.info(
                                    "frame_batch_execution_complete",
                                    frame_id=frame.frame_id,
                                    results_count=files_scanned,
                                    total_findings=total_findings_from_batch,
                                )

                                for res in f_results:
                                    if res and res.findings:
                                        frame_findings.extend(res.findings)

                        except asyncio.TimeoutError:
                            logger.warning("frame_batch_execution_timeout", frame=frame.frame_id)
                            execution_errors += 1
                        except Exception as ex:
                            logger.error("frame_batch_execution_error", frame=frame.frame_id, error=str(ex))
                            execution_errors += 1

                status = "passed"
                if any(f.severity == "critical" for f in frame_findings):
                    status = "failed"
                elif any(f.severity == "high" for f in frame_findings):
                    status = "warning"

                frame_duration = time.perf_counter() - frame_start_time

                coverage = self._calculate_coverage(code_files, frame_findings)

                result_metadata = {
                    "files_scanned": files_scanned,
                    "execution_errors": execution_errors,
                    "coverage": coverage,
                    "findings_found": len(frame_findings),
                    "findings_fixed": 0,
                    "trend": 0,
                    "supports_verification": getattr(frame, "supports_verification", True),
                }

                if hasattr(frame, "batch_summary") and frame.batch_summary:
                    result_metadata["llm_filter_summary"] = frame.batch_summary

                if hasattr(frame, "config") and frame.config and "suppressions" in frame.config:
                    suppressions = frame.config["suppressions"]
                    if suppressions and frame_findings:
                        findings_before = len(frame_findings)
                        frame_findings = SuppressionFilter.apply_config_suppressions(frame_findings, suppressions, context=context)
                        findings_after = len(frame_findings)

                        if findings_before != findings_after:
                            logger.info(
                                "suppression_applied",
                                frame_id=frame.frame_id,
                                suppressed=findings_before - findings_after,
                            )

                frame_result = FrameResult(
                    frame_id=frame.frame_id,
                    frame_name=frame.name,
                    status=status,
                    duration=frame_duration,
                    issues_found=len(frame_findings),
                    is_blocker=frame.is_blocker and status == "failed",
                    findings=frame_findings,
                    metadata=result_metadata,
                )

                pipeline.frames_executed += 1
                if status == "failed":
                    pipeline.frames_failed += 1
                else:
                    pipeline.frames_passed += 1

                if files_scanned > 0 or len(frame_result.findings) > 0:
                    logger.info(
                        "frame_executed_successfully",
                        frame_id=frame.frame_id,
                        files_scanned=files_scanned,
                        findings=len(frame_result.findings),
                    )
                else:
                    logger.debug(
                        "frame_executed_successfully", frame_id=frame.frame_id, files_scanned=files_scanned, findings=0
                    )

            except asyncio.TimeoutError:
                logger.error("frame_timeout", frame_id=frame.frame_id)
                frame_result = FrameResult(
                    frame_id=frame.frame_id,
                    frame_name=frame.name,
                    status="timeout",
                    findings=[],
                )
                pipeline.frames_failed += 1
            except Exception as e:
                _healed = False
                # Try self-healing for ImportError/ModuleNotFoundError
                if isinstance(e, (ImportError, ModuleNotFoundError)):
                    _healed = await self._try_heal_import_error(e, frame.frame_id)
                    if _healed:
                        try:
                            retry_files = files_to_scan if files_to_scan else code_files
                            for cf in retry_files:
                                result = await execute_single_file_async(cf)
                                if result:
                                    if result.findings:
                                        frame_findings.extend(result.findings)
                                    files_scanned += 1
                            logger.info(
                                "frame_healed_and_retried",
                                frame_id=frame.frame_id,
                                files_scanned=files_scanned,
                                findings=len(frame_findings),
                            )
                        except Exception as retry_err:
                            logger.error(
                                "frame_retry_after_healing_failed",
                                frame_id=frame.frame_id,
                                error=str(retry_err),
                            )
                            _healed = False  # Retry failed, fall through to error

                if not _healed:
                    logger.error(
                        "frame_execution_error", frame_id=frame.frame_id, error=str(e), error_type=type(e).__name__
                    )
                    frame_result = FrameResult(
                        frame_id=frame.frame_id,
                        frame_name=frame.name,
                        status="error",
                        findings=[],
                    )
                    pipeline.frames_failed += 1

        post_violations = []
        if frame_rules and frame_rules.post_rules:
            post_violations = await self.rule_executor.execute_rules_async(frame_rules.post_rules, code_files)

            if post_violations and RuleExecutor.has_blocker_violations(post_violations):
                if frame_rules.on_fail == "stop":
                    logger.error("post_rules_failed_stopping", frame_id=frame.frame_id)
                    frame_result.status = "failed"
                    frame_result.is_blocker = True
                    pipeline.frames_failed += 1

        # Distinguish between "no rules configured" (None) and "rules ran, no violations" ([])
        has_pre_rules = frame_rules and frame_rules.pre_rules
        has_post_rules = frame_rules and frame_rules.post_rules
        frame_result.pre_rule_violations = pre_violations if has_pre_rules else None
        frame_result.post_rule_violations = post_violations if has_post_rules else None

        # If any blocker violations exist (regardless of on_fail), mark frame as failed.
        # on_fail="continue" means execution continues, but the result is still a failure.
        all_violations = (pre_violations or []) + (post_violations or [])
        if all_violations and RuleExecutor.has_blocker_violations(all_violations):
            if frame_result.status != "failed":
                frame_result.status = "failed"
                frame_result.is_blocker = True
                pipeline.frames_failed += 1

        # Rule violations are tracked separately in pre/post_rule_violations.
        # Do NOT extend frame_result.findings — the pipeline result builder
        # aggregates rule violations into total_findings independently.

        context.frame_results[frame.frame_id] = {
            "result": frame_result,
            "pre_violations": pre_violations,
            "post_violations": post_violations,
        }

        # BATCH 3: Log context injection summary
        total_injections = _context_metrics.frames_with_pi + _context_metrics.frames_with_findings
        if total_injections > 0:
            total_errors = _context_metrics.pi_injection_errors + _context_metrics.findings_injection_errors
            avg_time_ms = _context_metrics.total_injection_time_ms / max(1, total_injections)
            logger.info(
                "context_injection_summary",
                frames_with_pi=_context_metrics.frames_with_pi,
                frames_with_findings=_context_metrics.frames_with_findings,
                total_errors=total_errors,
                avg_injection_time_ms=round(avg_time_ms, 2),
                total_injection_time_ms=round(_context_metrics.total_injection_time_ms, 2),
            )

        if self.progress_callback:
            self.progress_callback(
                "frame_completed",
                {
                    "frame_id": frame.frame_id,
                    "frame_name": frame.name,
                    "status": frame_result.status,
                    "findings": len(frame_result.findings) if hasattr(frame_result, "findings") else 0,
                    "duration": getattr(frame_result, "duration", 0.0),
                },
            )

        return frame_result

    async def _try_heal_import_error(self, error: Exception, frame_id: str) -> bool:
        """Attempt to self-heal an ImportError during frame execution."""
        try:
            from warden.self_healing import SelfHealingOrchestrator

            diagnostic = SelfHealingOrchestrator()
            result = await diagnostic.diagnose_and_fix(
                error,
                context=f"Frame execution: {frame_id}",
            )

            if result.fixed:
                logger.info(
                    "frame_import_error_healed",
                    frame_id=frame_id,
                    packages_installed=result.packages_installed,
                )
                return True

            if result.diagnosis:
                logger.warning(
                    "frame_import_error_diagnosis",
                    frame_id=frame_id,
                    diagnosis=result.diagnosis,
                )
            return False

        except Exception as heal_err:
            logger.debug(
                "frame_self_healing_failed",
                frame_id=frame_id,
                error=str(heal_err),
            )
            return False

    def _collect_frame_ignores(self) -> dict[str, list[str]]:
        """Collect frame-specific ignore patterns from frames_config."""
        frame_ignores: dict[str, list[str]] = {}
        frames_config = getattr(self.config, "frames_config", None)
        if not frames_config:
            return frame_ignores

        config_dict = frames_config if isinstance(frames_config, dict) else {}
        for frame_id, frame_cfg in config_dict.items():
            if isinstance(frame_cfg, dict):
                patterns = frame_cfg.get("ignore_patterns", [])
            else:
                patterns = getattr(frame_cfg, "ignore_patterns", [])
            if patterns:
                frame_ignores[frame_id] = list(patterns)

        return frame_ignores

    def _calculate_coverage(self, code_files: list[CodeFile], findings: list[Any]) -> float:
        """
        Calculate frame coverage percentage based on quality.
        Coverage = (Files without critical/high issues / Total files) * 100
        """
        if not code_files:
            return 0.0

        total_files = len(code_files)
        affected_files = set()

        for f in findings:
            severity = getattr(f, "severity", "").lower()
            if severity in ["critical", "high"]:
                if hasattr(f, "file_path") and f.file_path:
                    affected_files.add(f.file_path)
                elif hasattr(f, "location") and f.location:
                    path = f.location.split(":")[0]
                    affected_files.add(path)

        clean_files = total_files - len(affected_files)
        return (clean_files / total_files) * 100
