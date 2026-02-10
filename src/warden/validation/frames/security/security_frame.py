"""
Security Frame - Critical security validation.

Built-in checks:
- SQL Injection detection
- XSS (Cross-Site Scripting) detection
- Secrets/credentials detection
- Hardcoded passwords detection

Enhanced with:
- Tree-sitter AST analysis (structural vulnerability detection)
- LSP data flow analysis (taint tracking)
- Semantic search cross-file context
- LLM-powered deep analysis

Pipeline: Pattern → Tree-sitter → LSP → VectorDB → LLM

Priority: CRITICAL (blocker)
"""

import asyncio
import re
import time
from typing import List, Dict, Any, Optional, Tuple

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
from warden.validation.domain.check import CheckRegistry, CheckResult
from warden.validation.infrastructure.check_loader import CheckLoader
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class SecurityFrame(ValidationFrame):
    """
    Security validation frame - Critical security checks.

    This frame detects common security vulnerabilities:
    - SQL injection
    - XSS (Cross-Site Scripting)
    - Hardcoded secrets/credentials
    - Insecure patterns

    Priority: CRITICAL (blocks PR on failure)
    Applicability: All languages
    """

    # Required metadata
    name = "Security Analysis"
    description = "Detects SQL injection, XSS, secrets, and other security vulnerabilities"
    category = FrameCategory.GLOBAL
    priority = FramePriority.CRITICAL
    scope = FrameScope.FILE_LEVEL
    is_blocker = True  # Block PR if critical security issues found
    version = "2.1.0"  # v2.1: Added Tree-sitter AST + LSP data flow for full pipeline
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]  # Applies to all languages

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize SecurityFrame with checks.

        Args:
            config: Frame configuration
        """
        super().__init__(config)

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
            from _internal.sql_injection_check import SQLInjectionCheck
            from _internal.xss_check import XSSCheck
            from _internal.secrets_check import SecretsCheck
            from _internal.hardcoded_password_check import (
                HardcodedPasswordCheck,
            )
        except ImportError:
            logger.error("Failed to import internal checks")
            return

        # Register all built-in checks
        self.checks.register(SQLInjectionCheck(self.config.get("sql_injection", {})))
        self.checks.register(XSSCheck(self.config.get("xss", {})))
        self.checks.register(SecretsCheck(self.config.get("secrets", {})))
        self.checks.register(
            HardcodedPasswordCheck(self.config.get("hardcoded_password", {}))
        )

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
                    check_class.id, {}  # type: ignore[attr-defined]
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
                    check=check_class.__name__ if hasattr(check_class, '__name__') else "unknown",
                    error=str(e),
                )

    # =========================================================================
    # Tree-sitter AST Analysis (Structural Vulnerability Detection)
    # =========================================================================

    async def _extract_ast_context(self, code_file: CodeFile) -> Dict[str, Any]:
        """
        Extract AST context using Tree-sitter for structural analysis.

        Detects:
        - Function calls with string concatenation (potential injection)
        - Dangerous function usage (eval, exec, subprocess)
        - Unvalidated input flows

        Returns:
            Dict with AST-extracted security context
        """
        ast_context: Dict[str, Any] = {
            "dangerous_calls": [],
            "string_concatenations": [],
            "input_sources": [],
            "sql_queries": [],
        }

        try:
            from warden.ast.application.provider_registry import ASTProviderRegistry
            from warden.ast.domain.enums import CodeLanguage

            # Get language enum
            try:
                lang = CodeLanguage(code_file.language.lower())
            except ValueError:
                logger.debug("ast_unsupported_language", language=code_file.language)
                return ast_context

            # Get AST provider
            registry = ASTProviderRegistry()
            provider = registry.get_provider(lang)

            if not provider:
                logger.debug("ast_no_provider", language=lang)
                return ast_context

            # Ensure grammar is available (auto-install if needed)
            if hasattr(provider, 'ensure_grammar'):
                await provider.ensure_grammar(lang)

            # Parse with timeout
            result = await asyncio.wait_for(
                provider.parse(code_file.content, lang),
                timeout=5.0
            )

            if not result.ast_root:
                return ast_context

            # Walk AST and extract security-relevant nodes
            self._walk_ast_for_security(result.ast_root, ast_context, code_file.content)

            logger.debug(
                "ast_security_context_extracted",
                dangerous_calls=len(ast_context["dangerous_calls"]),
                sql_queries=len(ast_context["sql_queries"]),
                input_sources=len(ast_context["input_sources"])
            )

        except asyncio.TimeoutError:
            logger.debug("ast_extraction_timeout", file=code_file.path)
        except Exception as e:
            logger.debug("ast_extraction_failed", error=str(e))

        return ast_context

    def _walk_ast_for_security(self, node: Any, context: Dict[str, Any], source: str) -> None:
        """Walk AST and extract security-relevant patterns."""
        if node is None:
            return

        node_type = getattr(node, 'type', '') or ''

        # Detect dangerous function calls
        if node_type in ('call_expression', 'call'):
            call_name = self._get_call_name(node)
            if call_name:
                # Check for dangerous functions
                dangerous_funcs = {'eval', 'exec', 'compile', 'subprocess', 'shell',
                                   'system', 'popen', 'spawn', 'execfile'}
                if any(d in call_name.lower() for d in dangerous_funcs):
                    line = getattr(node, 'start_point', (0,))[0] if hasattr(node, 'start_point') else 0
                    context["dangerous_calls"].append({
                        "function": call_name,
                        "line": line,
                        "risk": "high"
                    })

                # Check for SQL-related calls
                sql_funcs = {'execute', 'executemany', 'raw', 'query', 'cursor'}
                if any(s in call_name.lower() for s in sql_funcs):
                    line = getattr(node, 'start_point', (0,))[0] if hasattr(node, 'start_point') else 0
                    context["sql_queries"].append({
                        "function": call_name,
                        "line": line
                    })

        # Detect string concatenation in potentially dangerous contexts
        if node_type in ('binary_expression', 'binary_operator'):
            if hasattr(node, 'text'):
                text = node.text.decode() if isinstance(node.text, bytes) else str(node.text)
                if '+' in text and ('"' in text or "'" in text):
                    line = getattr(node, 'start_point', (0,))[0] if hasattr(node, 'start_point') else 0
                    context["string_concatenations"].append({
                        "line": line,
                        "snippet": text[:100]
                    })

        # Detect input sources
        if node_type in ('call_expression', 'call', 'attribute'):
            call_name = self._get_call_name(node) or ''
            input_patterns = {'request', 'input', 'argv', 'stdin', 'getenv', 'form', 'params'}
            if any(p in call_name.lower() for p in input_patterns):
                line = getattr(node, 'start_point', (0,))[0] if hasattr(node, 'start_point') else 0
                context["input_sources"].append({
                    "source": call_name,
                    "line": line
                })

        # Recurse into children
        children = getattr(node, 'children', []) or []
        for child in children:
            self._walk_ast_for_security(child, context, source)

    def _get_call_name(self, node: Any) -> Optional[str]:
        """Extract function/method name from call node."""
        for attr in ('function', 'callee', 'name', 'method'):
            child = getattr(node, attr, None)
            if child:
                if hasattr(child, 'text'):
                    return child.text.decode() if isinstance(child.text, bytes) else str(child.text)
                if hasattr(child, 'name'):
                    return str(child.name)
        return None

    def _format_ast_context(self, ast_context: Dict[str, Any]) -> str:
        """Format AST context for LLM prompt."""
        lines = []

        if ast_context.get("dangerous_calls"):
            lines.append("[Dangerous Function Calls (AST)]:")
            for call in ast_context["dangerous_calls"][:5]:
                lines.append(f"  - {call['function']} at line {call['line']} (risk: {call['risk']})")

        if ast_context.get("sql_queries"):
            lines.append("\n[SQL Query Locations (AST)]:")
            for q in ast_context["sql_queries"][:5]:
                lines.append(f"  - {q['function']} at line {q['line']}")

        if ast_context.get("input_sources"):
            lines.append("\n[Input Sources (AST)]:")
            for src in ast_context["input_sources"][:5]:
                lines.append(f"  - {src['source']} at line {src['line']}")

        return "\n".join(lines) if lines else ""

    # =========================================================================
    # LSP Data Flow Analysis (Taint Tracking)
    # =========================================================================

    async def _analyze_data_flow(
        self,
        code_file: CodeFile,
        findings: List["CheckResult"]
    ) -> Dict[str, Any]:
        """
        Analyze data flow using LSP for taint tracking.

        For each finding:
        - Track callers (who uses the vulnerable code - blast radius)
        - Track callees (where does untrusted data come from - data sources)

        Returns:
            Dict with data flow context for each finding
        """
        data_flow_context: Dict[str, Any] = {
            "tainted_paths": [],
            "blast_radius": [],
            "data_sources": []
        }

        try:
            from warden.lsp import get_semantic_analyzer
            analyzer = get_semantic_analyzer()
        except ImportError:
            logger.debug("lsp_not_available_for_data_flow")
            return data_flow_context
        except Exception as e:
            logger.debug("lsp_init_failed", error=str(e))
            return data_flow_context

        # Extract function names and lines from findings
        sensitive_locations = self._extract_sensitive_locations(code_file, findings)

        for location in sensitive_locations[:5]:  # Limit to 5 locations
            try:
                # Get callers (blast radius - who uses this vulnerable code)
                callers = await asyncio.wait_for(
                    analyzer.get_callers_async(
                        code_file.path,
                        location["line"],
                        location.get("column", 0),
                        content=code_file.content
                    ),
                    timeout=5.0
                )
                if callers:
                    data_flow_context["blast_radius"].extend([
                        {
                            "vulnerable_at": f"{code_file.path}:{location['line']}",
                            "called_from": c.name,
                            "caller_file": c.location,
                            "finding_type": location.get("type", "unknown")
                        }
                        for c in callers[:3]
                    ])

                # Get callees (data sources - where does data come from)
                callees = await asyncio.wait_for(
                    analyzer.get_callees_async(
                        code_file.path,
                        location["line"],
                        location.get("column", 0),
                        content=code_file.content
                    ),
                    timeout=5.0
                )
                if callees:
                    data_flow_context["data_sources"].extend([
                        {
                            "vulnerable_at": f"{code_file.path}:{location['line']}",
                            "data_from": c.name,
                            "source_file": c.location,
                            "finding_type": location.get("type", "unknown")
                        }
                        for c in callees[:3]
                    ])

            except asyncio.TimeoutError:
                logger.debug("lsp_data_flow_timeout", location=location)
            except Exception as e:
                logger.debug("lsp_data_flow_error", location=location, error=str(e))

        # Identify tainted paths (data flow from untrusted source to sink)
        if data_flow_context["data_sources"]:
            for source in data_flow_context["data_sources"]:
                # Check if source is from untrusted origin (request, user input, etc.)
                source_name = source.get("data_from", "").lower()
                if any(keyword in source_name for keyword in [
                    "request", "input", "param", "query", "body", "form",
                    "user", "args", "kwargs", "data", "payload"
                ]):
                    data_flow_context["tainted_paths"].append({
                        "source": source["data_from"],
                        "sink": source["vulnerable_at"],
                        "risk": "high" if "sql" in source.get("finding_type", "").lower() else "medium"
                    })

        logger.debug("data_flow_analysis_complete",
                    blast_radius=len(data_flow_context["blast_radius"]),
                    data_sources=len(data_flow_context["data_sources"]),
                    tainted_paths=len(data_flow_context["tainted_paths"]))

        return data_flow_context

    def _extract_sensitive_locations(
        self,
        code_file: CodeFile,
        check_results: List["CheckResult"]
    ) -> List[Dict[str, Any]]:
        """Extract line numbers and types from check findings for LSP analysis."""
        locations = []

        for result in check_results:
            for finding in result.findings:
                # Parse location string (format: "path:line" or "path:line:col")
                loc_str = finding.location
                if ":" in loc_str:
                    parts = loc_str.split(":")
                    try:
                        line = int(parts[-1]) if len(parts) >= 2 else 1
                        column = int(parts[-1]) if len(parts) >= 3 else 0
                        locations.append({
                            "line": line,
                            "column": column,
                            "type": finding.check_id,
                            "message": finding.message
                        })
                    except ValueError:
                        continue

        return locations

    def _format_data_flow_context(self, data_flow: Dict[str, Any]) -> str:
        """Format data flow context for LLM prompt."""
        lines = []

        if data_flow.get("tainted_paths"):
            lines.append("[Tainted Data Paths (HIGH RISK)]:")
            for path in data_flow["tainted_paths"][:3]:
                lines.append(f"  - {path['source']} -> {path['sink']} (risk: {path['risk']})")

        if data_flow.get("blast_radius"):
            lines.append("\n[Blast Radius - Code affected by vulnerabilities]:")
            for br in data_flow["blast_radius"][:3]:
                lines.append(f"  - {br['called_from']} in {br['caller_file']}")

        if data_flow.get("data_sources"):
            lines.append("\n[Data Sources - Where vulnerable data originates]:")
            for ds in data_flow["data_sources"][:3]:
                lines.append(f"  - {ds['data_from']} from {ds['source_file']}")

        return "\n".join(lines) if lines else ""

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        """
        Execute all security checks on code file.

        Args:
            code_file: Code file to validate

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

        # Execute all enabled checks

        # Execute all enabled checks
        check_results: List[CheckResult] = []
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
        ast_context: Dict[str, Any] = {}
        try:
            ast_context = await self._extract_ast_context(code_file)
        except Exception as e:
            logger.debug("ast_extraction_failed", error=str(e))

        # STEP 3: LSP Data Flow Analysis (Taint Tracking)
        data_flow_context: Dict[str, Any] = {}
        if check_results:  # Only analyze if we have findings
            try:
                data_flow_context = await self._analyze_data_flow(code_file, check_results)
            except Exception as e:
                logger.debug("data_flow_analysis_failed", error=str(e))

        # AI-Powered Security Verification (Real Implementation)
        if hasattr(self, 'llm_service') and self.llm_service:
            try:
                logger.info("executing_llm_security_check", file=code_file.path)
                
                # Get Cross-File Context via Semantic Search
                semantic_context = ""
                if hasattr(self, 'semantic_search_service') and self.semantic_search_service and self.semantic_search_service.is_available():
                    try:
                        search_results = await self.semantic_search_service.search(
                            query=f"Security sensitive logic related to {code_file.path}",
                            limit=3
                        )
                        if search_results:
                            semantic_context = "\n[Semantic Context from other files]:\n"
                            for res in search_results:
                                if res.chunk.file_path != code_file.path:
                                    semantic_context += f"- File: {res.chunk.file_path}\n  Code: {res.chunk.content[:200]}...\n"
                    except Exception as e:
                        logger.warning("security_semantic_search_failed", error=str(e))

                # Add Tree-sitter AST Context
                ast_str = ""
                if ast_context:
                    ast_str = self._format_ast_context(ast_context)
                    if ast_str:
                        semantic_context += f"\n\n{ast_str}"
                        logger.debug("ast_context_added_to_llm",
                                    dangerous_calls=len(ast_context.get("dangerous_calls", [])),
                                    sql_queries=len(ast_context.get("sql_queries", [])))

                # Add LSP Data Flow Context (Taint Analysis)
                data_flow_str = ""
                if data_flow_context:
                    data_flow_str = self._format_data_flow_context(data_flow_context)
                    if data_flow_str:
                        semantic_context += f"\n\n{data_flow_str}"
                        logger.debug("data_flow_context_added_to_llm",
                                    tainted_paths=len(data_flow_context.get("tainted_paths", [])),
                                    blast_radius=len(data_flow_context.get("blast_radius", [])))

                
                # Determine tier from metadata (Adaptive Hybrid Triage)
                use_fast_tier = False
                if code_file.metadata and code_file.metadata.get('triage_lane') == 'middle_lane':
                    use_fast_tier = True
                    logger.debug("using_fast_tier_for_security_analysis", file=code_file.path)

                # Use the shared JSON parsing utility (which we will create next) or a robust method
                # for now using a direct call pattern assuming service has structured output or we parse it
                response = await self.llm_service.analyze_security_async(
                    code_file.content + semantic_context, 
                    code_file.language,
                    use_fast_tier=use_fast_tier
                )
                logger.info("llm_security_response_received", response_count=len(response.get('findings', [])) if response else 0)
                
                if response and isinstance(response, dict) and 'findings' in response:
                    from warden.validation.domain.check import CheckFinding, CheckSeverity
                    llm_findings = []
                    for f in response['findings']:
                        severity_map = {
                            'critical': CheckSeverity.CRITICAL,
                            'high': CheckSeverity.HIGH,
                            'medium': CheckSeverity.MEDIUM,
                            'low': CheckSeverity.LOW
                        }
                        sev = f.get('severity', 'medium').lower()
                        ai_finding = CheckFinding(
                            check_id="llm-security",
                            check_name="AI Security Analysis",
                            severity=severity_map.get(sev, CheckSeverity.MEDIUM),
                            message=f.get('message', 'Potential issue detected'),
                            location=f"{code_file.path}:{f.get('line_number', 1)}",
                            suggestion=f.get('detail', 'AI identified a potential vulnerability.'),
                            code_snippet=None
                        )
                        llm_findings.append(ai_finding)
                    
                    if llm_findings:
                        llm_result = CheckResult(
                            check_id="llm-security-check",
                            check_name="LLM Enhanced Security Analysis",
                            passed=False,
                            findings=llm_findings
                        )
                        check_results.append(llm_result)

            except (AttributeError, RuntimeError) as e:
                logger.error("llm_security_check_failed", error=str(e))
        
        all_findings = self._aggregate_findings(check_results)

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
        metadata: Dict[str, Any] = {
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

    async def execute_batch_async(self, code_files: List[CodeFile]) -> List[FrameResult]:
        """
        Execute security checks on multiple files with BATCH PROCESSING.

        Pattern: OrphanFrame-style batch processing for 80-90% LLM call reduction.

        Args:
            code_files: List of code files to validate

        Returns:
            List of FrameResult (one per file)
        """
        if not code_files:
            return []

        logger.info("security_batch_started", file_count=len(code_files))
        batch_start = time.perf_counter()

        # PHASE 1: Pattern/AST Analysis (Fast, per-file)
        findings_map: Dict[str, List[Finding]] = {}
        check_results_map: Dict[str, List[CheckResult]] = {}

        for code_file in code_files:
            # Get enabled checks
            enabled_checks = self.checks.get_enabled(self.config)

            # Execute pattern checks (fast!)
            check_results: List[CheckResult] = []
            for check in enabled_checks:
                try:
                    result = await check.execute_async(code_file)
                    check_results.append(result)
                except Exception as e:
                    logger.error("batch_check_failed", check=check.name, file=code_file.path, error=str(e))

            check_results_map[code_file.path] = check_results

            # Convert to findings
            all_findings = self._aggregate_findings(check_results)
            findings_map[code_file.path] = all_findings

        # PHASE 2: Batch LLM Verification (if LLM available)
        if hasattr(self, 'llm_service') and self.llm_service:
            findings_map = await self._batch_verify_security_findings(
                findings_map,
                code_files
            )

        # PHASE 3: Build Results
        results = []
        for code_file in code_files:
            findings = findings_map.get(code_file.path, [])
            check_results = check_results_map.get(code_file.path, [])

            status = self._determine_status(findings)

            metadata: Dict[str, Any] = {
                "checks_executed": len(check_results),
                "checks_passed": sum(1 for r in check_results if r.passed),
                "checks_failed": sum(1 for r in check_results if not r.passed),
            }

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
        logger.info("security_batch_completed",
                   file_count=len(code_files),
                   total_findings=sum(len(f) for f in findings_map.values()),
                   duration=f"{batch_duration:.2f}s")

        return results

    async def _batch_verify_security_findings(
        self,
        findings_map: Dict[str, List[Finding]],
        code_files: List[CodeFile]
    ) -> Dict[str, List[Finding]]:
        """
        Batch LLM verification of security findings.

        Reduces LLM calls from N findings to N/batch_size calls.

        Args:
            findings_map: Dict of file_path -> findings
            code_files: List of code files for context

        Returns:
            Updated findings_map with LLM-verified findings
        """
        # Flatten findings
        all_findings_with_context = []
        for file_path, findings in findings_map.items():
            code_file = next((f for f in code_files if f.path == file_path), None)
            for finding in findings:
                all_findings_with_context.append({
                    "finding": finding,
                    "file_path": file_path,
                    "code_file": code_file
                })

        if not all_findings_with_context:
            return findings_map

        # Smart Batching (token-aware)
        MAX_SAFE_TOKENS = 6000
        BATCH_SIZE = 10
        batches = self._smart_batch_findings(all_findings_with_context, BATCH_SIZE, MAX_SAFE_TOKENS)

        logger.info("security_batch_llm_verification",
                   total_findings=len(all_findings_with_context),
                   batches=len(batches))

        # Process each batch
        verified_findings_map: Dict[str, List[Finding]] = {path: [] for path in findings_map.keys()}

        for i, batch in enumerate(batches):
            try:
                logger.debug(f"Processing security batch {i+1}/{len(batches)}")
                verified_batch = await self._verify_security_batch(batch, code_files)

                # Map back to files
                for item in verified_batch:
                    file_path = item["file_path"]
                    verified_findings_map[file_path].append(item["finding"])

            except Exception as e:
                logger.error("security_batch_verification_failed", batch=i, error=str(e))
                # Fallback: keep original findings
                for item in batch:
                    file_path = item["file_path"]
                    verified_findings_map[file_path].append(item["finding"])

        return verified_findings_map

    def _smart_batch_findings(
        self,
        findings_with_context: List[Dict[str, Any]],
        max_batch_size: int,
        max_tokens: int
    ) -> List[List[Dict[str, Any]]]:
        """Token-aware batching for findings."""
        batches = []
        current_batch = []
        current_tokens = 0

        for item in findings_with_context:
            finding = item["finding"]
            # Estimate tokens: message + code snippet
            estimated_tokens = len(finding.message.split()) * 1.5
            if finding.code:
                estimated_tokens += len(finding.code.split()) * 1.5

            if (current_tokens + estimated_tokens > max_tokens or
                len(current_batch) >= max_batch_size):
                if current_batch:
                    batches.append(current_batch)
                current_batch = [item]
                current_tokens = estimated_tokens
            else:
                current_batch.append(item)
                current_tokens += estimated_tokens

        if current_batch:
            batches.append(current_batch)

        return batches

    async def _verify_security_batch(
        self,
        batch: List[Dict[str, Any]],
        code_files: List[CodeFile]
    ) -> List[Dict[str, Any]]:
        """
        Single LLM call for multiple security findings.

        Args:
            batch: List of {finding, file_path, code_file}

        Returns:
            List of verified findings with same structure
        """
        # Build batch prompt
        prompt_parts = ["Review these security findings and verify if they are true vulnerabilities:\n\n"]

        for i, item in enumerate(batch):
            finding = item["finding"]
            code_file = item["code_file"]

            prompt_parts.append(f"Finding #{i+1}:")
            prompt_parts.append(f"File: {item['file_path']}")
            prompt_parts.append(f"Severity: {finding.severity}")
            prompt_parts.append(f"Message: {finding.message}")
            if finding.code:
                prompt_parts.append(f"Code:\n```\n{finding.code[:200]}\n```")
            if code_file:
                # Add limited context
                prompt_parts.append(f"File Context (first 500 chars):\n```\n{code_file.content[:500]}\n```")
            prompt_parts.append("\n---\n")

        prompt_parts.append("""
Return JSON array with verification results:
[
  {"finding_id": 1, "is_valid": true/false, "confidence": "high/medium/low", "reason": "..."},
  ...
]
""")

        full_prompt = "\n".join(prompt_parts)

        # Single LLM call
        try:
            response = await self.llm_service.send_async(
                prompt=full_prompt,
                system="You are a senior security engineer. Verify if these security findings are true vulnerabilities or false positives."
            )

            # Parse LLM response and filter false positives
            import json
            try:
                content = response.get("content", "")
                parsed = json.loads(content)

                if isinstance(parsed, list):
                    # Build set of invalid finding IDs (1-based indexing from prompt)
                    invalid_ids = {
                        item.get("finding_id")
                        for item in parsed
                        if isinstance(item, dict) and not item.get("is_valid", True)
                    }

                    if invalid_ids:
                        # Filter out invalid findings (0-based indexing in batch)
                        verified = [
                            batch[i] for i in range(len(batch))
                            if (i + 1) not in invalid_ids
                        ]
                        logger.info(
                            "security_llm_filtered",
                            total=len(batch),
                            filtered=len(batch) - len(verified),
                            remaining=len(verified)
                        )
                        return verified

            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                logger.warning(
                    "security_llm_parse_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    fallback="keeping_all_findings"
                )

            # Fallback: keep all findings if parsing fails or no invalid findings found
            return batch

        except Exception as e:
            logger.error("security_batch_llm_failed", error=str(e))
            return batch  # Fallback: keep all findings

    def _aggregate_findings(self, check_results: List[CheckResult]) -> List[Finding]:
        """
        Aggregate findings from all check results.

        Args:
            check_results: Results from all executed checks

        Returns:
            List of Finding objects
        """
        findings: List[Finding] = []

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
                findings.append(finding)

        return findings

    def _determine_status(self, findings: List[Finding]) -> str:
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

    def register_check(self, check: "ValidationCheck") -> None:  # type: ignore[name-defined]
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
