"""
Security Frame - Main frame class.

Detects SQL injection, XSS, secrets, and other security vulnerabilities.
Uses AST analysis, taint tracking, data flow analysis, and LLM verification.
"""

from __future__ import annotations

import html
import time
from typing import TYPE_CHECKING, Any

from warden.pipeline.application.orchestrator.result_aggregator import normalize_finding_to_dict
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.check import CheckRegistry, CheckResult, ValidationCheck
from warden.validation.domain.enums import (
    FrameApplicability,
    FrameCategory,
    FramePriority,
    FrameScope,
)
from warden.validation.domain.frame import (
    CodeFile,
    Finding,
    FrameResult,
    MachineContext,
    ValidationFrame,
)
from warden.validation.domain.mixins import BatchExecutable, CodeGraphAware, TaintAware
from warden.validation.infrastructure.check_loader import CheckLoader

from .ast_analyzer import extract_ast_context, format_ast_context
from .batch_processor import batch_verify_security_findings

if TYPE_CHECKING:
    from warden.pipeline.domain.pipeline_context import PipelineContext
from .data_flow_analyzer import analyze_data_flow, format_data_flow_context

logger = get_logger(__name__)


class SecurityFrame(ValidationFrame, BatchExecutable, TaintAware, CodeGraphAware):
    """
    Security validation frame - Critical security checks.

    This frame detects common security vulnerabilities:
    - SQL injection
    - XSS (Cross-Site Scripting)
    - Hardcoded secrets/credentials
    - Insecure patterns

    Priority: CRITICAL (blocks PR on failure)
    Applicability: All languages

    Implements:
    - BatchExecutable: For optimized batch processing with LLM call reduction
    """

    # Required metadata
    frame_id = "security"  # Class-level access: SecurityFrame.frame_id == "security"
    name = "Security Analysis"
    description = "Detects SQL injection, XSS, secrets, and other security vulnerabilities"
    category = FrameCategory.GLOBAL
    priority = FramePriority.CRITICAL
    scope = FrameScope.FILE_LEVEL
    is_blocker = True  # Block PR if critical security issues found
    version = "2.2.0"  # v2.2: Added source-to-sink taint analysis
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]  # Applies to all languages
    minimum_triage_lane: str = "middle_lane"  # Skip FAST files; LLM-heavy frame

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialize SecurityFrame with checks.

        Args:
            config: Frame configuration
        """
        super().__init__(config)

        # Shared taint paths (injected by pipeline via TaintAware mixin)
        self._taint_paths: dict[str, list] = {}

        # CodeGraphAware: injected by FrameRunner before execution
        self._code_graph: Any = None
        self._gap_report: Any = None

        # Check registry
        self.checks = CheckRegistry()

        # Register built-in checks
        self._register_builtin_checks()

        # Discover and register community checks
        self._discover_community_checks()

    def _register_builtin_checks(self) -> None:
        """Register built-in security checks."""
        import sys
        from pathlib import Path

        # Add current directory to path to allow imports from _internal
        current_dir = str(Path(__file__).parent)
        if current_dir not in sys.path:
            sys.path.append(current_dir)

        try:
            from _internal.crypto_check import WeakCryptoCheck
            from _internal.csrf_check import CSRFCheck
            from _internal.hardcoded_password_check import (
                HardcodedPasswordCheck,
            )
            from _internal.http_security_check import HTTPSecurityCheck
            from _internal.jwt_check import JWTMisconfigCheck
            from _internal.secrets_check import SecretsCheck
            from _internal.sql_injection_check import SQLInjectionCheck
            from _internal.xss_check import XSSCheck
        except ImportError:
            logger.error("Failed to import internal checks")
            return

        # Register all built-in checks
        self.checks.register(SQLInjectionCheck(self.config.get("sql_injection", {})))
        self.checks.register(XSSCheck(self.config.get("xss", {})))
        self.checks.register(SecretsCheck(self.config.get("secrets", {})))
        self.checks.register(HardcodedPasswordCheck(self.config.get("hardcoded_password", {})))
        self.checks.register(HTTPSecurityCheck(self.config.get("http_security", {})))
        self.checks.register(CSRFCheck(self.config.get("csrf", {})))
        self.checks.register(WeakCryptoCheck(self.config.get("weak_crypto", {})))
        self.checks.register(JWTMisconfigCheck(self.config.get("jwt_misconfiguration", {})))

        logger.info(
            "builtin_checks_registered",
            frame=self.name,
            count=len(self.checks),
        )

    def _discover_community_checks(self) -> None:
        """Discover and register external checks."""
        loader = CheckLoader(frame_id=self.frame_id)
        external_checks = loader.discover_all()

        for check_class in external_checks:
            try:
                # Get check-specific config from frame config
                check_config = self.config.get("checks", {}).get(
                    check_class.id,
                    {},  # type: ignore[attr-defined]
                )
                check_instance = check_class(config=check_config)
                self.checks.register(check_instance)

                logger.info(
                    "community_check_registered",
                    frame=self.name,
                    check=check_instance.name,
                )
            except (ImportError, AttributeError, TypeError, ValueError) as e:
                logger.error(
                    "community_check_registration_failed",
                    frame=self.name,
                    check=check_class.__name__ if hasattr(check_class, "__name__") else "unknown",
                    error=str(e),
                )

    def set_taint_paths(self, taint_paths: dict[str, list]) -> None:
        """TaintAware implementation — receive shared taint analysis results."""
        self._taint_paths = taint_paths

    def set_code_graph(self, code_graph: Any, gap_report: Any) -> None:
        """CodeGraphAware implementation — receive CodeGraph and GapReport."""
        self._code_graph = code_graph
        self._gap_report = gap_report

    async def execute_async(self, code_file: CodeFile, context: PipelineContext | None = None) -> FrameResult:
        """
        Execute all security checks on code file.

        Args:
            code_file: Code file to validate
            context: Optional pipeline context (Tier 2: Context-Awareness)

        Returns:
            FrameResult with aggregated findings from all checks
        """
        start_time = time.perf_counter()

        logger.info(
            "security_frame_started",
            file_path=code_file.path,
            language=code_file.language,
            enabled_checks=len(self.checks.get_enabled(self.config)),
        )

        # Get enabled checks
        enabled_checks = self.checks.get_enabled(self.config)

        # STEP 1: Execute pattern checks
        check_results: list[CheckResult] = []
        for check in enabled_checks:
            try:
                logger.debug(
                    "check_executing",
                    frame=self.name,
                    check=check.name,
                    file_path=code_file.path,
                )

                result = await check.execute_async(code_file)
                check_results.append(result)

                logger.debug(
                    "check_completed",
                    frame=self.name,
                    check=check.name,
                    passed=result.passed,
                    findings_count=len(result.findings),
                )

            except (RuntimeError, ValueError, TypeError) as e:
                logger.error(
                    "check_execution_failed",
                    frame=self.name,
                    check=check.name,
                    error=str(e),
                )
                # Continue with other checks even if one fails

        # STEP 2: Tree-sitter AST Analysis (Structural Vulnerability Detection)
        ast_context: dict[str, Any] = {}
        try:
            ast_context = await extract_ast_context(code_file)
        except Exception as e:
            logger.debug("ast_extraction_failed", error=str(e))

        # STEP 2.5: Taint Analysis (Source-to-Sink tracking)
        # Prefer shared results from TaintAnalysisService (pipeline pre-computed).
        # Fallback: inline analysis for standalone mode (no pipeline) or missing files.
        _TAINT_SUPPORTED_LANGUAGES = {"python", "javascript", "typescript", "go", "java"}
        taint_paths: list = []
        if code_file.language in _TAINT_SUPPORTED_LANGUAGES:
            if self._taint_paths and code_file.path in self._taint_paths:
                taint_paths = self._taint_paths[code_file.path]
                logger.debug("taint_from_shared_service", count=len(taint_paths), file=code_file.path)
            else:
                # Fallback: standalone mode (no pipeline) or file not in shared results
                try:
                    from pathlib import Path

                    from ._internal.taint_analyzer import TaintAnalyzer
                    from ._internal.taint_catalog import TaintCatalog

                    project_root = context.project_root if context and context.project_root else Path.cwd()
                    taint_config = self.config.get("taint", {})
                    catalog = TaintCatalog.load(project_root)
                    taint_analyzer = TaintAnalyzer(catalog=catalog, taint_config=taint_config)
                    taint_paths = taint_analyzer.analyze(code_file.content, code_file.language)
                    if taint_paths:
                        logger.info("taint_paths_detected", count=len(taint_paths), file=code_file.path)
                except Exception as e:
                    logger.debug("taint_analysis_failed", error=str(e))

        # STEP 3: LSP Data Flow Analysis (Taint Tracking)
        data_flow_context: dict[str, Any] = {}
        if check_results:  # Only analyze if we have findings
            try:
                data_flow_context = await analyze_data_flow(code_file, check_results)
            except Exception as e:
                logger.debug("data_flow_analysis_failed", error=str(e))

        # STEP 4: AI-Powered Security Verification
        _llm_mc_map: list[dict | None] = []
        if hasattr(self, "llm_service") and self.llm_service:
            try:
                logger.info("executing_llm_security_check", file=code_file.path)

                # Build context-aware prompt (Tier 1: Context-Awareness)
                semantic_context = ""

                # 1. Project Intelligence Context
                if hasattr(self, "project_intelligence") and self.project_intelligence:
                    pi = self.project_intelligence
                    semantic_context += "\n[PROJECT CONTEXT]:\n"

                    # Entry points (where untrusted data enters)
                    if hasattr(pi, "entry_points") and pi.entry_points:
                        entry_points_str = ", ".join(pi.entry_points[:5])
                        semantic_context += f"Entry Points: {entry_points_str}\n"

                    # Authentication patterns detected
                    if hasattr(pi, "auth_patterns") and pi.auth_patterns:
                        auth_str = ", ".join(pi.auth_patterns[:3])
                        semantic_context += f"Auth Patterns: {auth_str}\n"

                    # Critical sinks (dangerous operations)
                    if hasattr(pi, "critical_sinks") and pi.critical_sinks:
                        sinks_str = ", ".join(pi.critical_sinks[:5])
                        semantic_context += f"Critical Sinks: {sinks_str}\n"

                    # Framework detection (reduces FPs for framework-managed patterns)
                    if hasattr(pi, "detected_frameworks") and pi.detected_frameworks:
                        fw_str = ", ".join(pi.detected_frameworks[:3])
                        semantic_context += f"Framework: {fw_str}\n"

                    # Architecture description (LLM-generated project overview)
                    if hasattr(pi, "architecture") and pi.architecture:
                        semantic_context += f"\n[ARCHITECTURE]:\n{pi.architecture[:300]}\n"

                    logger.debug("project_intelligence_added_to_prompt", file=code_file.path)

                # 1x. Architectural Directives (human-authored rules from .warden/architecture.md)
                if hasattr(self, "architectural_directives") and self.architectural_directives:
                    semantic_context += f"\n[ARCHITECTURAL DIRECTIVES]:\n{self.architectural_directives[:500]}\n"

                # 1a. Spec Analysis Contracts (cross-frame: SpecFrame → SecurityFrame)
                if hasattr(self, "spec_analysis") and self.spec_analysis:
                    spec = self.spec_analysis
                    contracts = spec.get("contracts", {})
                    if contracts:
                        # Find relevant contracts for this file (path match or show top 5)
                        relevant: list[dict] = []
                        for _platform, platform_contracts in contracts.items():
                            if not isinstance(platform_contracts, list):
                                continue
                            for c in platform_contracts:
                                if not isinstance(c, dict):
                                    continue
                                # Match by file path or endpoint relevance
                                c_path = c.get("file", "") or c.get("path", "")
                                if c_path and code_file.path.endswith(c_path.lstrip("/")):
                                    relevant.insert(0, c)  # File match = high priority
                                elif len(relevant) < 5:
                                    relevant.append(c)
                        if relevant:
                            semantic_context += "\n[BUSINESS LOGIC CONTRACTS]:\n"
                            for c in relevant[:5]:
                                endpoint = c.get("endpoint", c.get("name", "unknown"))
                                method = c.get("method", "")
                                desc = c.get("description", c.get("detail", ""))[:120]
                                semantic_context += f"- {method} {endpoint}: {desc}\n"
                            logger.debug("spec_analysis_added_to_prompt", file=code_file.path, contracts=len(relevant))

                # 1b. File dependency context (import graph)
                if context and hasattr(context, "dependency_graph_forward"):
                    rel_path = code_file.path
                    try:
                        from pathlib import Path as _P

                        if context.project_root:
                            rel_path = str(_P(code_file.path).resolve().relative_to(context.project_root))
                    except (ValueError, TypeError):
                        pass
                    deps = context.dependency_graph_forward.get(rel_path, [])
                    dependents = context.dependency_graph_reverse.get(rel_path, [])
                    if deps:
                        semantic_context += f"Depends on: {', '.join(deps[:5])}\n"
                    if dependents:
                        semantic_context += f"Depended by: {', '.join(dependents[:5])}\n"

                # 2. Prior Findings Context (cross-frame awareness) - BATCH 2: Sanitized
                if hasattr(self, "prior_findings") and self.prior_findings:
                    # Normalize and filter findings for this file
                    file_findings = []
                    for f in self.prior_findings:
                        normalized = normalize_finding_to_dict(f)
                        if normalized.get("location", "").startswith(code_file.path):
                            file_findings.append(normalized)

                    if file_findings:
                        semantic_context += "\n[PRIOR FINDINGS ON THIS FILE]:\n"
                        for finding in file_findings[:3]:  # Limit to top 3
                            # BATCH 2: SANITIZE - Escape HTML, truncate, detect injection
                            raw_msg = finding.get("message", "")
                            raw_severity = finding.get("severity", "unknown")

                            # Truncate to prevent token overflow
                            msg = html.escape(raw_msg[:200])  # Max 200 chars
                            severity = html.escape(raw_severity[:20])  # Max 20 chars

                            # Detect prompt injection attempts
                            suspicious_patterns = [
                                "ignore previous",
                                "system:",
                                "[system",
                                "override",
                                "<script",
                                "javascript:",
                            ]
                            if any(pattern in msg.lower() for pattern in suspicious_patterns):
                                logger.warning(
                                    "prompt_injection_detected",
                                    file=code_file.path,
                                    finding_id=finding.get("id", "unknown"),
                                    action="sanitized",
                                )
                                msg = "[SANITIZED: Suspicious content removed]"

                            semantic_context += f"- [{severity}] {msg}\n"

                        logger.debug("prior_findings_added_to_prompt", file=code_file.path, count=len(file_findings))

                # 3. Cross-File Context via Semantic Search
                if (
                    hasattr(self, "semantic_search_service")
                    and self.semantic_search_service
                    and self.semantic_search_service.is_available()
                ):
                    try:
                        search_results = await self.semantic_search_service.search(
                            query=f"Security sensitive logic related to {code_file.path}", limit=3
                        )
                        if search_results:
                            semantic_context += "\n[Semantic Context from other files]:\n"
                            for res in search_results:
                                if res.chunk.file_path != code_file.path:
                                    semantic_context += (
                                        f"- File: {res.chunk.file_path}\n  Code: {res.chunk.content[:200]}...\n"
                                    )
                    except Exception as e:
                        logger.warning("security_semantic_search_failed", error=str(e))

                # Add Tree-sitter AST Context
                if ast_context:
                    ast_str = format_ast_context(ast_context)
                    if ast_str:
                        semantic_context += f"\n\n{ast_str}"
                        logger.debug(
                            "ast_context_added_to_llm",
                            dangerous_calls=len(ast_context.get("dangerous_calls", [])),
                            sql_queries=len(ast_context.get("sql_queries", [])),
                        )

                # Add LSP Data Flow Context (Taint Analysis)
                if data_flow_context:
                    data_flow_str = format_data_flow_context(data_flow_context)
                    if data_flow_str:
                        semantic_context += f"\n\n{data_flow_str}"
                        logger.debug(
                            "data_flow_context_added_to_llm",
                            tainted_paths=len(data_flow_context.get("tainted_paths", [])),
                            blast_radius=len(data_flow_context.get("blast_radius", [])),
                        )

                # Add Taint Analysis Context (source-to-sink paths)
                if taint_paths:
                    unsanitized = [p for p in taint_paths if not p.is_sanitized]
                    if unsanitized:
                        semantic_context += "\n\n[Taint Analysis - Source-to-Sink Paths (HIGH RISK)]:\n"
                        for tp in unsanitized[:5]:
                            transforms = getattr(tp, "transformations", [])
                            transform_str = f" via [{' -> '.join(transforms[:3])}]" if transforms else ""
                            semantic_context += (
                                f"  - SOURCE: {tp.source.name} (line {tp.source.line})"
                                f"{transform_str}"
                                f" -> SINK: {tp.sink.name} [{tp.sink_type}] (line {tp.sink.line})"
                                f" confidence={tp.confidence:.2f}\n"
                            )
                    sanitized = [p for p in taint_paths if p.is_sanitized]
                    if sanitized:
                        semantic_context += "\n[Taint Analysis - Sanitized Paths (lower risk)]:\n"
                        for tp in sanitized[:3]:
                            sanitizer_list = list(tp.sanitizers) if tp.sanitizers else ["unknown"]
                            semantic_context += (
                                f"  - {tp.source.name} -> {tp.sink.name} (sanitized by: {', '.join(sanitizer_list)})\n"
                            )
                    logger.debug(
                        "taint_context_added_to_llm",
                        unsanitized=len(unsanitized),
                        sanitized=len(sanitized),
                    )

                # Code graph symbol context (class/function signatures)
                if context and hasattr(context, "code_graph") and context.code_graph:
                    try:
                        from warden.analysis.services.symbol_context_formatter import (
                            format_file_symbols_for_prompt,
                        )

                        symbol_ctx = format_file_symbols_for_prompt(context.code_graph, code_file.path)
                        if symbol_ctx:
                            semantic_context += f"\n{symbol_ctx}"
                    except Exception as e:
                        logger.debug("symbol_context_failed", error=str(e))

                # Extract dangerous line numbers from AST + taint for targeting
                dangerous_lines: list[int] = []
                if ast_context:
                    for call in ast_context.get("dangerous_calls", []):
                        if isinstance(call, dict) and "line" in call:
                            dangerous_lines.append(call["line"])
                    for query in ast_context.get("sql_queries", []):
                        if isinstance(query, dict) and "line" in query:
                            dangerous_lines.append(query["line"])
                    for src in ast_context.get("input_sources", []):
                        if isinstance(src, dict) and "line" in src:
                            dangerous_lines.append(src["line"])

                if taint_paths:
                    for tp in taint_paths:
                        if hasattr(tp, "source") and hasattr(tp.source, "line"):
                            dangerous_lines.append(tp.source.line)
                        if hasattr(tp, "sink") and hasattr(tp.sink, "line"):
                            dangerous_lines.append(tp.sink.line)

                from warden.shared.utils.llm_context import BUDGET_SECURITY, prepare_code_for_llm, resolve_token_budget
                from warden.shared.utils.token_utils import truncate_content_for_llm

                budget = resolve_token_budget(
                    BUDGET_SECURITY,
                    context=context,
                    code_file_metadata=code_file.metadata,
                )
                use_fast_tier = budget.is_fast_tier
                truncated_code = prepare_code_for_llm(
                    code_file.content,
                    token_budget=budget,
                    target_lines=sorted(set(dangerous_lines)) if dangerous_lines else None,
                    file_path=code_file.path,
                    context=context,
                )

                truncated_semantic = truncate_content_for_llm(
                    semantic_context,
                    max_tokens=600,
                    preserve_start_lines=30,
                    preserve_end_lines=10,
                )
                truncated_context = truncated_code + "\n\n" + truncated_semantic

                original_length = len(code_file.content) + len(semantic_context)
                if len(truncated_context) < original_length:
                    logger.debug(
                        "llm_prompt_truncated",
                        file=code_file.path,
                        original_length=original_length,
                        truncated_length=len(truncated_context),
                    )

                response = await self.llm_service.analyze_security_async(
                    truncated_context, code_file.language, use_fast_tier=use_fast_tier
                )
                logger.info(
                    "llm_security_response_received",
                    response_count=len(response.get("findings", [])) if response else 0,
                )

                if response and isinstance(response, dict) and "findings" in response:
                    from warden.validation.domain.check import CheckFinding, CheckSeverity

                    llm_findings = []
                    for f in response["findings"]:
                        severity_map = {
                            "critical": CheckSeverity.CRITICAL,
                            "high": CheckSeverity.HIGH,
                            "medium": CheckSeverity.MEDIUM,
                            "low": CheckSeverity.LOW,
                        }
                        sev = f.get("severity", "medium").lower()
                        ai_finding = CheckFinding(
                            check_id="llm-security",
                            check_name="AI Security Analysis",
                            severity=severity_map.get(sev, CheckSeverity.MEDIUM),
                            message=f.get("message", "Potential issue detected"),
                            location=f"{code_file.path}:{f.get('line_number', 1)}",
                            suggestion=f.get("detail", "AI identified a potential vulnerability."),
                            code_snippet=None,
                            machine_context_raw=f.get("_machine_context"),
                        )
                        llm_findings.append(ai_finding)

                    if llm_findings:
                        llm_result = CheckResult(
                            check_id="llm-security-check",
                            check_name="LLM Enhanced Security Analysis",
                            passed=False,
                            findings=llm_findings,
                        )
                        check_results.append(llm_result)

            except (AttributeError, RuntimeError) as e:
                logger.error("llm_security_check_failed", error=str(e))

        # Convert unsanitized taint paths to findings (shared helper)
        if taint_paths:
            taint_result = self._convert_taint_paths_to_findings(taint_paths, code_file.path)
            if taint_result:
                check_results.append(taint_result)

        all_findings = self._aggregate_findings(check_results)

        # Post-aggregation: enrich findings with taint paths (Source-to-Sink tracking)
        if taint_paths:
            for finding in all_findings:
                if finding.location:
                    self._enrich_finding_with_taint(finding, taint_paths)

            enriched = sum(1 for f in all_findings if f.machine_context is not None)
            if enriched:
                logger.info("machine_context_populated", count=enriched, total=len(all_findings))

        # Determine frame status
        status = self._determine_status(all_findings)

        # Calculate duration
        duration = time.perf_counter() - start_time

        logger.info(
            "security_frame_completed",
            file_path=code_file.path,
            status=status,
            total_findings=len(all_findings),
            duration=f"{duration:.2f}s",
        )

        # Build metadata with data flow analysis results
        metadata: dict[str, Any] = {
            "checks_executed": len(check_results),
            "checks_passed": sum(1 for r in check_results if r.passed),
            "checks_failed": sum(1 for r in check_results if not r.passed),
            "check_results": [r.to_json() for r in check_results],
        }

        # Add AST analysis results if available
        if ast_context:
            metadata["ast_analysis"] = {
                "dangerous_calls_found": len(ast_context.get("dangerous_calls", [])),
                "sql_queries_found": len(ast_context.get("sql_queries", [])),
                "input_sources_found": len(ast_context.get("input_sources", [])),
            }

        # Add taint analysis results
        if taint_paths:
            metadata["taint_analysis"] = {
                "paths_found": len(taint_paths),
                "unsanitized": len([p for p in taint_paths if not p.is_sanitized]),
                "paths": [p.to_json() for p in taint_paths[:10]],  # Top 10
            }

        # Add data flow analysis results if available
        if data_flow_context:
            metadata["data_flow_analysis"] = {
                "tainted_paths_found": len(data_flow_context.get("tainted_paths", [])),
                "blast_radius_files": len(data_flow_context.get("blast_radius", [])),
                "data_sources_traced": len(data_flow_context.get("data_sources", [])),
            }
            # Include tainted paths for visibility (high-risk data flows)
            if data_flow_context.get("tainted_paths"):
                metadata["tainted_paths"] = data_flow_context["tainted_paths"]

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=duration,
            issues_found=len(all_findings),
            is_blocker=self.is_blocker and status == "failed",
            findings=all_findings,
            metadata=metadata,
        )

    async def execute_batch_async(self, code_files: list[CodeFile]) -> list[FrameResult]:
        """
        Execute security checks on multiple files with BATCH PROCESSING.

        Runs the full analysis pipeline (pattern checks, AST extraction, taint
        analysis, data flow analysis) per file -- matching ``execute_async`` --
        then batches the LLM verification step for 80-90% LLM call reduction.

        Args:
            code_files: List of code files to validate

        Returns:
            List of FrameResult (one per file)
        """
        if not code_files:
            return []

        logger.info("security_batch_started", file_count=len(code_files))
        batch_start = time.perf_counter()

        # PHASE 1: Full per-file analysis (pattern + AST + taint + data flow)
        findings_map: dict[str, list[Finding]] = {}
        check_results_map: dict[str, list[CheckResult]] = {}
        ast_context_map: dict[str, dict[str, Any]] = {}
        taint_paths_map: dict[str, list] = {}
        data_flow_context_map: dict[str, dict[str, Any]] = {}

        _TAINT_SUPPORTED_LANGUAGES = {"python", "javascript", "typescript", "go", "java"}

        error_files: set[str] = set()
        for code_file in code_files:
            try:
                # Get enabled checks
                enabled_checks = self.checks.get_enabled(self.config)

                # STEP 1: Execute pattern checks (fast!)
                check_results: list[CheckResult] = []
                for check in enabled_checks:
                    try:
                        result = await check.execute_async(code_file)
                        check_results.append(result)
                    except Exception as e:
                        logger.error("batch_check_failed", check=check.name, file=code_file.path, error=str(e))

                # STEP 2: Tree-sitter AST Analysis (structural vulnerability detection)
                ast_context: dict[str, Any] = {}
                try:
                    ast_context = await extract_ast_context(code_file)
                except Exception as e:
                    logger.debug("batch_ast_extraction_failed", file=code_file.path, error=str(e))
                ast_context_map[code_file.path] = ast_context

                # STEP 2.5: Taint analysis (prefer shared, fallback to inline)
                file_taint_paths: list = []
                if code_file.language in _TAINT_SUPPORTED_LANGUAGES:
                    file_taint_paths = []
                    if self._taint_paths and code_file.path in self._taint_paths:
                        file_taint_paths = self._taint_paths[code_file.path]
                    else:
                        try:
                            from pathlib import Path as _Path

                            from ._internal.taint_analyzer import TaintAnalyzer
                            from ._internal.taint_catalog import TaintCatalog

                            taint_config = self.config.get("taint", {})
                            project_root = _Path.cwd()
                            catalog = TaintCatalog.load(project_root)
                            taint_analyzer = TaintAnalyzer(catalog=catalog, taint_config=taint_config)
                            file_taint_paths = taint_analyzer.analyze(code_file.content, code_file.language)
                        except Exception as e:
                            logger.debug("batch_taint_analysis_failed", file=code_file.path, error=str(e))

                    if file_taint_paths:
                        taint_result = self._convert_taint_paths_to_findings(file_taint_paths, code_file.path)
                        if taint_result:
                            check_results.append(taint_result)
                taint_paths_map[code_file.path] = file_taint_paths

                # STEP 3: Data Flow Analysis (taint tracking via LSP)
                data_flow_context: dict[str, Any] = {}
                if check_results:
                    try:
                        data_flow_context = await analyze_data_flow(code_file, check_results)
                    except Exception as e:
                        logger.debug("batch_data_flow_analysis_failed", file=code_file.path, error=str(e))
                data_flow_context_map[code_file.path] = data_flow_context

                check_results_map[code_file.path] = check_results

                # Convert to findings (pass taint context for MachineContext enrichment)
                all_findings = self._aggregate_findings(check_results)
                if file_taint_paths:
                    for f in all_findings:
                        if f.location:
                            self._enrich_finding_with_taint(f, file_taint_paths)
                findings_map[code_file.path] = all_findings
            except Exception as e:
                logger.error("batch_file_failed", file=code_file.path, error=str(e))
                error_files.add(code_file.path)
                findings_map[code_file.path] = []
                check_results_map[code_file.path] = []

        # PHASE 2: Batch LLM Verification (if LLM available)
        if hasattr(self, "llm_service") and self.llm_service:
            batch_ctx = self._build_batch_context()
            findings_map = await batch_verify_security_findings(
                findings_map, code_files, self.llm_service, semantic_context=batch_ctx
            )

        # PHASE 3: Build Results
        results = []
        for code_file in code_files:
            findings = findings_map.get(code_file.path, [])
            check_results = check_results_map.get(code_file.path, [])

            status = "error" if code_file.path in error_files else self._determine_status(findings)

            metadata: dict[str, Any] = {
                "checks_executed": len(check_results),
                "checks_passed": sum(1 for r in check_results if r.passed),
                "checks_failed": sum(1 for r in check_results if not r.passed),
            }

            # Add AST analysis results if available
            file_ast = ast_context_map.get(code_file.path, {})
            if file_ast:
                metadata["ast_analysis"] = {
                    "dangerous_calls_found": len(file_ast.get("dangerous_calls", [])),
                    "sql_queries_found": len(file_ast.get("sql_queries", [])),
                    "input_sources_found": len(file_ast.get("input_sources", [])),
                }

            # Add taint analysis results
            file_taint = taint_paths_map.get(code_file.path, [])
            if file_taint:
                metadata["taint_analysis"] = {
                    "paths_found": len(file_taint),
                    "unsanitized": len([p for p in file_taint if not p.is_sanitized]),
                    "paths": [p.to_json() for p in file_taint[:10]],
                }

            # Add data flow analysis results if available
            file_data_flow = data_flow_context_map.get(code_file.path, {})
            if file_data_flow:
                metadata["data_flow_analysis"] = {
                    "tainted_paths_found": len(file_data_flow.get("tainted_paths", [])),
                    "blast_radius_files": len(file_data_flow.get("blast_radius", [])),
                    "data_sources_traced": len(file_data_flow.get("data_sources", [])),
                }
                if file_data_flow.get("tainted_paths"):
                    metadata["tainted_paths"] = file_data_flow["tainted_paths"]

            result = FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status=status,
                duration=0.1,  # Placeholder, will be overridden
                issues_found=len(findings),
                is_blocker=self.is_blocker and status == "failed",
                findings=findings,
                metadata=metadata,
            )
            results.append(result)

        batch_duration = time.perf_counter() - batch_start
        logger.info(
            "security_batch_completed",
            file_count=len(code_files),
            total_findings=sum(len(f) for f in findings_map.values()),
            duration=f"{batch_duration:.2f}s",
        )

        return results

    def _build_batch_context(self) -> str:
        """Build compact project-level context for batch LLM verification."""
        parts: list[str] = []
        if hasattr(self, "project_intelligence") and self.project_intelligence:
            pi = self.project_intelligence
            if hasattr(pi, "detected_frameworks") and pi.detected_frameworks:
                parts.append(f"Framework: {', '.join(pi.detected_frameworks[:3])}")
            if hasattr(pi, "entry_points") and pi.entry_points:
                parts.append(f"Entry points: {', '.join(pi.entry_points[:3])}")
            if hasattr(pi, "auth_patterns") and pi.auth_patterns:
                parts.append(f"Auth: {', '.join(pi.auth_patterns[:2])}")
        return "\n".join(parts)

    def _convert_taint_paths_to_findings(self, taint_paths: list, file_path: str) -> CheckResult | None:
        """Convert unsanitized taint paths to a CheckResult with findings.

        Reads ``confidence_threshold`` from ``self.config["taint"]`` with validated
        defaults from ``TAINT_DEFAULTS``.  Findings whose confidence >= threshold
        get HIGH severity **and** ``is_blocker=True``.
        """
        from warden.validation.domain.check import CheckFinding, CheckSeverity

        from ._internal.taint_analyzer import validate_taint_config

        taint_config = validate_taint_config(self.config.get("taint"))
        threshold = taint_config["confidence_threshold"]

        taint_findings: list[CheckFinding] = []
        for tp in taint_paths:
            if tp.is_sanitized:
                continue
            is_high_conf = tp.confidence >= threshold
            severity = CheckSeverity.HIGH if is_high_conf else CheckSeverity.MEDIUM
            taint_findings.append(
                CheckFinding(
                    check_id="taint-analysis",
                    check_name="Taint Analysis",
                    severity=severity,
                    message=(
                        f"Unsanitized data flow: {tp.source.name} (line {tp.source.line})"
                        f" -> {tp.sink.name} [{tp.sink_type}] (line {tp.sink.line})"
                    ),
                    location=f"{file_path}:{tp.sink.line}",
                    suggestion=f"Sanitize the tainted value before passing to {tp.sink.name}.",
                    code_snippet=None,
                    is_blocker=is_high_conf,
                )
            )
        if not taint_findings:
            return None
        return CheckResult(
            check_id="taint-analysis",
            check_name="Source-to-Sink Taint Analysis",
            passed=False,
            findings=taint_findings,
        )

    def _aggregate_findings(
        self,
        check_results: list[CheckResult],
        taint_context: list | None = None,
    ) -> list[Finding]:
        """
        Aggregate findings from all check results.

        Args:
            check_results: Results from all executed checks
            taint_context: Optional taint paths for MachineContext enrichment.
                When provided, each finding is enriched via
                ``_enrich_finding_with_taint``.  Prefer injecting taint data
                via the ``TaintAware`` mixin; this parameter exists for
                backward compatibility with direct callers.

        Returns:
            List of Finding objects
        """
        findings: list[Finding] = []

        for check_result in check_results:
            for check_finding in check_result.findings:
                # Convert CheckFinding to Frame-level Finding
                finding = Finding(
                    id=f"{self.frame_id}-{check_finding.check_id}-{len(findings)}",
                    severity=check_finding.severity.value,
                    message=f"[{check_finding.check_name}] {check_finding.message}",
                    location=check_finding.location,
                    detail=check_finding.suggestion,
                    code=check_finding.code_snippet,
                    is_blocker=check_finding.is_blocker,
                )

                # Populate explicitly tagged LLM context instances on creation
                if getattr(check_finding, "machine_context_raw", None):
                    mc_data = check_finding.machine_context_raw
                    finding.machine_context = MachineContext(
                        vulnerability_class=finding.id.split("-")[1] if "-" in finding.id else "unknown",
                        source=mc_data.get("source"),
                        sink=mc_data.get("sink"),
                        data_flow_path=mc_data.get("data_flow_path", []),
                    )

                findings.append(finding)

        # Enrich with taint data when provided directly (backward compat)
        if taint_context:
            for finding in findings:
                if finding.machine_context is None:
                    self._enrich_finding_with_taint(finding, taint_context)

        return findings

    @staticmethod
    def _enrich_finding_with_taint(finding: Finding, taint_paths: list) -> None:
        """Populate finding.machine_context from matching taint paths."""
        # Extract line number from finding location ("file.py:45" -> 45)
        line_num = finding.line
        if not line_num and ":" in finding.location:
            try:
                line_num = int(finding.location.rsplit(":", 1)[-1])
            except (ValueError, IndexError):
                return

        if not line_num:
            return

        # Find taint paths that cover this line (source or sink on/near this line)
        for tp in taint_paths:
            if not hasattr(tp, "source") or not hasattr(tp, "sink"):
                continue
            # Match if finding line is near source or sink (within 3 lines)
            source_match = abs(tp.source.line - line_num) <= 3
            sink_match = abs(tp.sink.line - line_num) <= 3
            if source_match or sink_match:
                vuln_class = "unknown"
                finding_id = finding.id
                if "-" in finding_id:
                    parts = finding_id.split("-")
                    # e.g. "security-sql-injection-0" -> "sql-injection"
                    if len(parts) >= 3:
                        vuln_class = "-".join(parts[1:-1])

                finding.machine_context = MachineContext(
                    vulnerability_class=vuln_class,
                    source=f"{tp.source.name} (line {tp.source.line})",
                    sink=f"{tp.sink.name} (line {tp.sink.line})",
                    sink_type=tp.sink.sink_type if hasattr(tp.sink, "sink_type") else None,
                    data_flow_path=[tp.source.name] + getattr(tp, "transformations", []) + [tp.sink.name],
                    sanitizers_applied=list(tp.sanitizers) if tp.sanitizers else [],
                )
                break  # Use first matching taint path

    def _determine_status(self, findings: list[Finding]) -> str:
        """
        Determine frame status based on findings.

        Args:
            findings: All findings from checks

        Returns:
            Status: 'passed', 'warning', or 'failed'
        """
        if not findings:
            return "passed"

        # Check for explicit blockers
        if any(f.is_blocker for f in findings):
            return "failed"

        # Count critical and high severity findings
        critical_count = sum(1 for f in findings if f.severity == "critical")
        high_count = sum(1 for f in findings if f.severity == "high")

        if critical_count > 0:
            return "failed"  # Critical issues = blocker
        elif high_count > 0:
            return "warning"  # High severity = warning
        else:
            return "passed"  # Only medium/low = passed

    def register_check(self, check: ValidationCheck) -> None:
        """
        Programmatically register a custom check.

        Args:
            check: ValidationCheck instance to register

        Example:
            >>> from my_checks import MyCustomCheck
            >>> security_frame = SecurityFrame()
            >>> security_frame.register_check(MyCustomCheck())
        """
        self.checks.register(check)
        logger.info(
            "check_registered_programmatically",
            frame=self.name,
            check=check.name,
        )
