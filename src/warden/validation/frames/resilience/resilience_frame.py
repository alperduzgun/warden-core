"""
Chaos Engineering Analysis Frame.

Philosophy: "Everything will fail. The question is HOW and WHEN."

Architecture (Universal, Language-Agnostic):
1. Tree-sitter → Extract structure (imports, function calls)
2. LSP → Enrich with cross-file context (callers, callees)
3. VectorDB → Search related resilience patterns in codebase
4. LLM → Decide what's external, simulate failures, find missing patterns

Pipeline: Tree-sitter → LSP → VectorDB → LLM

Principles: KISS, DRY, SOLID, YAGNI, Fail-Fast, Idempotency
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from warden.llm.prompts.tool_instructions import get_tool_enhanced_prompt
from warden.pipeline.application.orchestrator.result_aggregator import normalize_finding_to_dict
from warden.shared.infrastructure.logging import get_logger
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
    ValidationFrame,
)
from warden.validation.domain.mixins import TaintAware

if TYPE_CHECKING:
    from warden.pipeline.domain.pipeline_context import PipelineContext

logger = get_logger(__name__)


# =============================================================================
# PRE-COMPILED PATTERNS (Performance: compile once, use many times)
# =============================================================================

# Universal import patterns (work across languages)
_IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+(.+)", re.IGNORECASE),
    re.compile(r"^\s*from\s+(\S+)\s+import", re.IGNORECASE),
    re.compile(r'^\s*require\s*\(\s*[\'"]([^\'"]+)', re.IGNORECASE),
    re.compile(r"^\s*use\s+(\S+)", re.IGNORECASE),
    re.compile(r"^\s*using\s+(\S+)", re.IGNORECASE),
    re.compile(r'^\s*#include\s*[<"]([^>"]+)', re.IGNORECASE),
]

# Function call pattern
_CALL_PATTERN = re.compile(r"\b(\w+(?:\.\w+)*)\s*\(", re.MULTILINE)

# Async function pattern
_ASYNC_PATTERN = re.compile(r"\basync\s+(?:def|function|fn)\s+(\w+)", re.MULTILINE)

# Error handler pattern
_ERROR_HANDLER_PATTERN = re.compile(r"\b(try|catch|except|rescue|recover)\b", re.IGNORECASE)

# Keywords to filter from function calls
_CALL_KEYWORDS = frozenset({"if", "for", "while", "switch", "catch", "function", "def", "class"})


# =============================================================================
# DOMAIN MODELS (Strict Types, Immutable)
# =============================================================================


class DependencyType(Enum):
    """Types of external dependencies that can fail."""

    NETWORK = "network"
    DATABASE = "database"
    FILE_SYSTEM = "file_system"
    MESSAGE_QUEUE = "message_queue"
    CLOUD_SERVICE = "cloud_service"
    EXTERNAL_PROCESS = "external_process"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExtractedCall:
    """A function/method call extracted from code."""

    name: str
    line: int
    module: str | None = None

    def __hash__(self) -> int:
        return hash((self.name, self.line, self.module))


@dataclass(frozen=True)
class ExtractedImport:
    """An import statement extracted from code."""

    module: str
    line: int
    alias: str | None = None


@dataclass
class ChaosContext:
    """
    Context for chaos engineering analysis.

    Collected incrementally through analysis pipeline.
    Passed to LLM for intelligent decision making.
    """

    # From Tree-sitter (structural)
    imports: list[ExtractedImport] = field(default_factory=list)
    function_calls: list[ExtractedCall] = field(default_factory=list)
    async_functions: list[str] = field(default_factory=list)
    error_handlers: int = 0

    # From LSP (semantic)
    callers: list[dict[str, str]] = field(default_factory=list)
    callees: list[dict[str, str]] = field(default_factory=list)

    # From LLM (intelligent)
    external_deps: list[str] = field(default_factory=list)
    dep_types: dict[str, DependencyType] = field(default_factory=dict)

    # Limits for LLM context (prevent token explosion)
    MAX_IMPORTS_IN_CONTEXT: int = 10
    MAX_CALLS_IN_CONTEXT: int = 10
    MAX_ASYNC_IN_CONTEXT: int = 5
    MAX_CALLERS_IN_CONTEXT: int = 3
    MAX_CALLEES_IN_CONTEXT: int = 3

    @property
    def has_potential_externals(self) -> bool:
        """Quick check if analysis is worth doing."""
        # If we have imports or function calls, worth analyzing
        return bool(self.imports) or bool(self.function_calls)

    def to_llm_context(self) -> str:
        """Format context for LLM prompt."""
        lines = []

        if self.imports:
            import_list = [f"{i.module}" for i in self.imports[: self.MAX_IMPORTS_IN_CONTEXT]]
            lines.append(f"Imports: {', '.join(import_list)}")

        if self.function_calls:
            call_list = list({c.name for c in self.function_calls})[: self.MAX_CALLS_IN_CONTEXT]
            lines.append(f"Function calls: {', '.join(call_list)}")

        if self.async_functions:
            lines.append(f"Async functions: {', '.join(self.async_functions[: self.MAX_ASYNC_IN_CONTEXT])}")

        if self.callers:
            caller_list = [f"{c['name']} ({c.get('file', '?')})" for c in self.callers[: self.MAX_CALLERS_IN_CONTEXT]]
            lines.append(f"Called by (blast radius): {', '.join(caller_list)}")

        if self.callees:
            callee_list = [f"{c['name']} ({c.get('file', '?')})" for c in self.callees[: self.MAX_CALLEES_IN_CONTEXT]]
            lines.append(f"Calls to (failure sources): {', '.join(callee_list)}")

        return "\n".join(lines) if lines else "No structural context available"


# =============================================================================
# CHAOS SYSTEM PROMPT (Single Source of Truth)
# =============================================================================

_CHAOS_SYSTEM_PROMPT_BASE = """You are a Chaos Engineer. Your mindset: "Everything will fail. The question is HOW and WHEN."

## YOUR TASK

Given code and its structural context (imports, function calls, cross-file dependencies):

1. **IDENTIFY** external dependencies from the imports and calls
   - Network: HTTP clients, gRPC, WebSocket
   - Database: SQL, NoSQL, ORM
   - File System: read/write operations
   - Message Queues: Kafka, RabbitMQ, Redis
   - Cloud: AWS, Azure, GCP services
   - External Process: subprocess, exec

2. **SIMULATE** failure scenarios for each external dependency:
   - Network: timeout, connection refused, 5xx errors, rate limiting
   - Database: connection lost, deadlock, slow query, constraint violation
   - File: permission denied, disk full, file locked
   - Queue: broker down, message lost, duplicate delivery
   - Cloud: service unavailable, throttling, eventual consistency

3. **EVALUATE** existing resilience patterns:
   - Timeout: Does code give up or wait forever?
   - Retry: Exponential backoff? Jitter? Max attempts?
   - Circuit Breaker: Fail-fast when dependency is down?
   - Fallback: Graceful degradation or crash?
   - Cleanup: Resources released on failure?

4. **REPORT** only MISSING resilience patterns (not existing ones)

## OUTPUT FORMAT (JSON)

{
    "external_dependencies": [
        {"name": "httpx.AsyncClient", "type": "network", "line": 15},
        {"name": "sqlalchemy.Session", "type": "database", "line": 42}
    ],
    "issues": [
        {
            "severity": "high",
            "title": "HTTP call without timeout",
            "description": "client.get() at line 20 has no timeout. If server is slow, this will hang forever.",
            "line": 20,
            "suggestion": "Add timeout=10.0 or use asyncio.wait_for()"
        }
    ],
    "score": 4,
    "confidence": 0.85
}

## SEVERITY GUIDE
- critical: Data loss, security breach, cascading failure
- high: Service unavailability, stuck process, resource leak
- medium: Poor UX, slow recovery, partial failure
- low: Suboptimal but functional
"""

CHAOS_SYSTEM_PROMPT = get_tool_enhanced_prompt(_CHAOS_SYSTEM_PROMPT_BASE)


# =============================================================================
# RESILIENCE FRAME (Main Class)
# =============================================================================


class ResilienceFrame(ValidationFrame, TaintAware):
    """
    Chaos Engineering Analysis Frame.

    Universal, language-agnostic approach:
    1. Tree-sitter extracts structure (imports, calls)
    2. LSP adds semantic context (cross-file)
    3. LLM decides what's external and what's missing

    Follows: KISS, DRY, SOLID, YAGNI
    Safety: Fail-fast, timeouts on all external calls, idempotent analysis
    """

    # Metadata
    frame_id = "resilience"  # Class-level access: ResilienceFrame.frame_id == "resilience"
    name = "Chaos Engineering Analysis"
    description = "Simulate failures, find missing resilience patterns (timeout, retry, circuit breaker)."
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = False
    version = "3.1.0"  # v3.1: Added VectorDB semantic search for related patterns
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]
    minimum_triage_lane: str = "middle_lane"  # Skip FAST files; LLM-heavy frame

    # Configuration (fail-fast defaults)
    DEFAULT_TIMEOUT_SECONDS: float = 30.0
    MAX_IMPORTS_TO_ANALYZE: int = 20
    MAX_CALLS_TO_ANALYZE: int = 50
    MAX_LSP_FUNCTIONS_TO_CHECK: int = 3
    LSP_CALL_TIMEOUT: float = 5.0

    # Circuit breaker settings (prevent cascading failures)
    CIRCUIT_BREAKER_THRESHOLD: int = 3  # failures before opening
    CIRCUIT_BREAKER_RESET_SECONDS: float = 60.0

    # Class-level circuit breaker state (shared across instances)
    _llm_failure_count: int = 0
    _llm_circuit_opened_at: float | None = None

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize with optional config. Fail-fast on invalid config."""
        super().__init__(config)
        self._taint_paths: dict[str, list] = {}

        # Validate config early (fail-fast)
        self._timeout = float(self.config.get("timeout", self.DEFAULT_TIMEOUT_SECONDS))
        if self._timeout <= 0:
            raise ValueError(f"timeout must be positive, got {self._timeout}")

        logger.debug("resilience_frame_initialized", timeout=self._timeout, version=self.version)

    def set_taint_paths(self, taint_paths: dict[str, list]) -> None:
        """TaintAware implementation — receive shared taint analysis results."""
        self._taint_paths = taint_paths

    async def execute_async(self, code_file: CodeFile, context: PipelineContext | None = None) -> FrameResult:
        """
        Execute chaos engineering analysis.

        Args:
            code_file: Code file to analyze
            context: Optional pipeline context (Tier 2: Context-Awareness)

        Pipeline:
        1. Extract structure (tree-sitter) - O(n), instant
        2. Enrich context (LSP) - O(1), with timeout
        3. Search related patterns (VectorDB) - O(1), with timeout
        4. Analyze with LLM (if worth it) - expensive, with timeout

        Idempotent: Same input → same output (temperature=0)
        """
        start_time = time.perf_counter()

        logger.info(
            "chaos_analysis_started", file=code_file.path, language=code_file.language, size_bytes=code_file.size_bytes
        )

        findings: list[Finding] = []
        self._pipeline_context = context  # Preserve for LLM prompt enrichment
        context = ChaosContext()

        try:
            # STEP 1: Extract structure (fast, no external deps)
            context = await self._extract_structure(code_file)

            # Early exit if nothing to analyze (YAGNI)
            if not context.has_potential_externals:
                logger.debug("chaos_no_externals_skipping", file=code_file.path)
                return self._create_result(code_file, findings, context, start_time)

            # STEP 2: Enrich with LSP (cheap, with timeout)
            await self._enrich_with_lsp(code_file, context)

            # STEP 3: Search related resilience patterns (VectorDB)
            related_patterns = await self._search_related_patterns(code_file, context)

            # STEP 4: LLM analysis (expensive, only if LLM available)
            if self._has_llm_service():
                llm_findings = await self._analyze_with_llm(code_file, context, related_patterns)
                findings.extend(llm_findings)
            else:
                # Fallback: basic pattern detection without LLM
                basic_findings = self._basic_analysis(code_file, context)
                findings.extend(basic_findings)

        except Exception as e:
            # Fail-fast but graceful: log and return partial result
            logger.error("chaos_analysis_failed", file=code_file.path, error=str(e), error_type=type(e).__name__)
            findings.append(
                Finding(
                    id=f"{self.frame_id}-error",
                    severity="low",
                    message=f"Analysis incomplete: {type(e).__name__}",
                    location=code_file.path,
                    detail=str(e),
                    code=None,
                )
            )

        return self._create_result(code_file, findings, context, start_time)

    # =========================================================================
    # STEP 1: Structure Extraction (Tree-sitter / Regex fallback)
    # =========================================================================

    async def _extract_structure(self, code_file: CodeFile) -> ChaosContext:
        """
        Extract structural information from code.

        Tries tree-sitter first (universal), falls back to basic regex.
        No external dependencies, always succeeds.
        """
        context = ChaosContext()

        try:
            # Try tree-sitter first
            context = await self._extract_with_tree_sitter(code_file)
            logger.debug(
                "structure_extracted_tree_sitter", imports=len(context.imports), calls=len(context.function_calls)
            )
        except Exception as e:
            # Fallback to regex (always works)
            logger.debug("tree_sitter_fallback_to_regex", reason=str(e))
            context = self._extract_with_regex(code_file)

        return context

    async def _extract_with_tree_sitter(self, code_file: CodeFile) -> ChaosContext:
        """Extract using tree-sitter AST with auto-install."""
        from warden.ast.application.provider_registry import ASTProviderRegistry
        from warden.ast.domain.enums import CodeLanguage

        context = ChaosContext()

        # Get language enum
        try:
            lang = CodeLanguage(code_file.language.lower())
        except ValueError:
            raise ValueError(f"Unsupported language: {code_file.language}")

        # Cache-first: use pre-parsed result if available
        cached = code_file.metadata.get("_cached_parse_result") if code_file.metadata else None
        if cached and cached.ast_root:
            result = cached
        else:
            # Fallback: on-demand parse
            registry = ASTProviderRegistry()
            provider = registry.get_provider(lang)

            if not provider:
                raise ValueError(f"No AST provider for {lang}")

            if hasattr(provider, "ensure_grammar"):
                await provider.ensure_grammar(lang)

            result = await provider.parse(code_file.content, lang)

        if not result.ast_root:
            raise ValueError("AST parsing returned no result")

        # Extract imports and calls from AST
        self._walk_ast_node(result.ast_root, context, code_file.content)

        return context

    def _walk_ast_node(self, node: Any, context: ChaosContext, source: str) -> None:
        """
        Walk AST and extract relevant information.

        Universal patterns across languages:
        - Import statements
        - Function/method calls
        - Async function definitions
        - Try/catch blocks
        """
        if node is None:
            return

        node_type = getattr(node, "type", "") or getattr(node, "node_type", "")

        # Import detection (universal patterns)
        if node_type in (
            "import_statement",
            "import_declaration",
            "import_from_statement",
            "use_declaration",
            "using_directive",
        ):
            line = getattr(node, "start_point", (0,))[0] if hasattr(node, "start_point") else 0
            # Get the import text
            if hasattr(node, "text"):
                module = node.text.decode() if isinstance(node.text, bytes) else str(node.text)
            else:
                module = str(node)
            context.imports.append(ExtractedImport(module=module[:100], line=line))

        # Function call detection
        if node_type in ("call_expression", "call", "method_invocation", "invocation_expression"):
            line = getattr(node, "start_point", (0,))[0] if hasattr(node, "start_point") else 0
            # Get function name
            name = self._extract_call_name(node)
            if name and len(context.function_calls) < self.MAX_CALLS_TO_ANALYZE:
                context.function_calls.append(ExtractedCall(name=name[:50], line=line))

        # Async function detection
        if node_type in ("async_function_definition", "async_function_declaration", "async_method_definition"):
            name = self._extract_function_name(node)
            if name:
                context.async_functions.append(name[:50])

        # Error handler detection
        if node_type in ("try_statement", "try_expression", "catch_clause"):
            context.error_handlers += 1

        # Recurse into children
        children = getattr(node, "children", []) or []
        for child in children:
            self._walk_ast_node(child, context, source)

    def _extract_call_name(self, node: Any) -> str | None:
        """Extract function name from call node."""
        # Try common patterns
        for attr in ("function", "callee", "name", "method"):
            child = getattr(node, attr, None)
            if child:
                if hasattr(child, "text"):
                    return child.text.decode() if isinstance(child.text, bytes) else str(child.text)
                if hasattr(child, "name"):
                    return str(child.name)
        return None

    def _extract_function_name(self, node: Any) -> str | None:
        """Extract function name from definition node."""
        name_node = getattr(node, "name", None)
        if name_node:
            if hasattr(name_node, "text"):
                return name_node.text.decode() if isinstance(name_node.text, bytes) else str(name_node.text)
            return str(name_node)
        return None

    def _extract_with_regex(self, code_file: CodeFile) -> ChaosContext:
        """
        Fallback regex extraction (universal patterns).

        Works for any language, less accurate than tree-sitter.
        Uses pre-compiled patterns for performance.
        """
        context = ChaosContext()
        content = code_file.content
        lines = content.split("\n")

        # Extract imports (limit lines scanned for performance)
        for i, line in enumerate(lines[:200]):
            for pattern in _IMPORT_PATTERNS:
                match = pattern.search(line)
                if match and len(context.imports) < self.MAX_IMPORTS_TO_ANALYZE:
                    context.imports.append(ExtractedImport(module=match.group(1)[:100], line=i))
                    break

        # Extract function calls
        for i, line in enumerate(lines):
            for match in _CALL_PATTERN.finditer(line):
                if len(context.function_calls) < self.MAX_CALLS_TO_ANALYZE:
                    name = match.group(1)
                    # Filter out common keywords
                    if name.lower() not in _CALL_KEYWORDS:
                        context.function_calls.append(ExtractedCall(name=name[:50], line=i))

        # Async detection
        for match in _ASYNC_PATTERN.finditer(content):
            context.async_functions.append(match.group(1))

        # Error handler count
        context.error_handlers = len(_ERROR_HANDLER_PATTERN.findall(content))

        return context

    # =========================================================================
    # STEP 2: LSP Enrichment
    # =========================================================================

    async def _enrich_with_lsp(self, code_file: CodeFile, context: ChaosContext) -> None:
        """
        Enrich context with LSP semantic information.

        Adds: callers (blast radius), callees (failure sources)
        Timeout protected, failures are logged and ignored.
        """
        import asyncio

        try:
            from warden.lsp import get_semantic_analyzer

            analyzer = get_semantic_analyzer()

            # Get callers/callees for first few async functions (rate limited)
            for func_name in context.async_functions[: self.MAX_LSP_FUNCTIONS_TO_CHECK]:
                try:
                    # Find function in code
                    match = re.search(rf"\b{re.escape(func_name)}\s*\(", code_file.content)
                    if not match:
                        continue

                    line = code_file.content[: match.start()].count("\n")

                    # Get callers with timeout
                    callers = await asyncio.wait_for(
                        analyzer.get_callers_async(code_file.path, line, 4, content=code_file.content),
                        timeout=self.LSP_CALL_TIMEOUT,
                    )
                    if callers:
                        context.callers.extend(
                            [{"name": c.name, "file": c.location} for c in callers[: context.MAX_CALLERS_IN_CONTEXT]]
                        )

                    # Get callees with timeout
                    callees = await asyncio.wait_for(
                        analyzer.get_callees_async(code_file.path, line, 4, content=code_file.content),
                        timeout=self.LSP_CALL_TIMEOUT,
                    )
                    if callees:
                        context.callees.extend(
                            [{"name": c.name, "file": c.location} for c in callees[: context.MAX_CALLEES_IN_CONTEXT]]
                        )

                except asyncio.TimeoutError:
                    logger.debug("lsp_timeout", func=func_name, timeout=self.LSP_CALL_TIMEOUT)
                    continue

        except ImportError:
            logger.debug("lsp_not_available")
        except Exception as e:
            logger.debug("lsp_enrichment_failed", error=str(e))

    # =========================================================================
    # STEP 3: Semantic Search (VectorDB)
    # =========================================================================

    async def _search_related_patterns(self, code_file: CodeFile, context: ChaosContext) -> list[dict[str, Any]]:
        """
        Search for related resilience patterns using VectorDB.

        Finds:
        - Similar code with resilience patterns (timeout, retry, circuit breaker)
        - Related error handling in the codebase
        - Existing resilience implementations to learn from

        Returns:
            List of related code snippets with resilience patterns
        """
        related_patterns: list[dict[str, Any]] = []

        # Check if semantic search service is available
        if not hasattr(self, "semantic_search_service") or not self.semantic_search_service:
            logger.debug("semantic_search_not_available")
            return related_patterns

        if not self.semantic_search_service.is_available():
            logger.debug("semantic_search_index_not_ready")
            return related_patterns

        try:
            # Build search query from context
            search_terms = []

            # Add external dependency names
            if context.imports:
                import_names = [i.module.split(".")[-1] for i in context.imports[:3]]
                search_terms.extend(import_names)

            # Add async function names (likely need resilience)
            if context.async_functions:
                search_terms.extend(context.async_functions[:2])

            # Always search for resilience patterns
            search_terms.extend(["timeout", "retry", "circuit_breaker", "error_handling"])

            query = f"resilience patterns for {' '.join(search_terms[:5])}"

            # Search with timeout
            import asyncio

            search_results = await asyncio.wait_for(
                self.semantic_search_service.search(query=query, limit=3), timeout=5.0
            )

            if search_results:
                for result in search_results:
                    # Skip if same file
                    if result.chunk.file_path == code_file.path:
                        continue

                    related_patterns.append(
                        {
                            "file": result.chunk.file_path,
                            "content": result.chunk.content[:300],
                            "score": result.score if hasattr(result, "score") else 0.0,
                            "has_timeout": "timeout" in result.chunk.content.lower(),
                            "has_retry": "retry" in result.chunk.content.lower(),
                            "has_circuit_breaker": "circuit" in result.chunk.content.lower(),
                        }
                    )

                logger.debug("semantic_search_complete", query=query[:50], results_found=len(related_patterns))

        except asyncio.TimeoutError:
            logger.debug("semantic_search_timeout")
        except Exception as e:
            logger.debug("semantic_search_failed", error=str(e))

        return related_patterns

    def _format_related_patterns(self, patterns: list[dict[str, Any]]) -> str:
        """Format related patterns for LLM context."""
        if not patterns:
            return ""

        lines = ["[Related Resilience Patterns in Codebase]:"]
        for p in patterns[:3]:
            features = []
            if p.get("has_timeout"):
                features.append("timeout")
            if p.get("has_retry"):
                features.append("retry")
            if p.get("has_circuit_breaker"):
                features.append("circuit_breaker")

            feature_str = f" ({', '.join(features)})" if features else ""
            lines.append(f"  - {p['file']}{feature_str}")
            lines.append(f"    ```\n    {p['content'][:200]}...\n    ```")

        return "\n".join(lines)

    # =========================================================================
    # STEP 4: LLM Analysis
    # =========================================================================

    def _has_llm_service(self) -> bool:
        """
        Check if LLM service is available and circuit breaker allows.

        Circuit breaker pattern: after N failures, stop trying for M seconds.
        Prevents cascading delays when LLM is down.
        """
        try:
            # Check if service exists
            if not hasattr(self, "llm_service") or self.llm_service is None:
                return False

            # Check circuit breaker
            if ResilienceFrame._llm_circuit_opened_at is not None:
                elapsed = time.perf_counter() - ResilienceFrame._llm_circuit_opened_at
                if elapsed < self.CIRCUIT_BREAKER_RESET_SECONDS:
                    logger.debug("llm_circuit_open", seconds_remaining=self.CIRCUIT_BREAKER_RESET_SECONDS - elapsed)
                    return False
                # Reset circuit breaker
                logger.info("llm_circuit_reset")
                ResilienceFrame._llm_circuit_opened_at = None
                ResilienceFrame._llm_failure_count = 0

            return True
        except Exception:
            # Any error checking service = no service
            return False

    async def _analyze_with_llm(
        self, code_file: CodeFile, context: ChaosContext, related_patterns: list[dict[str, Any]] | None = None
    ) -> list[Finding]:
        """
        Analyze with LLM for intelligent chaos engineering.

        The LLM decides:
        - Which imports/calls are external dependencies
        - What failure scenarios are relevant
        - What resilience patterns are missing
        """
        import asyncio

        from warden.llm.types import LlmRequest

        findings: list[Finding] = []

        try:
            # Format related patterns context
            related_context = ""
            if related_patterns:
                related_context = self._format_related_patterns(related_patterns)

            from warden.shared.utils.llm_context import BUDGET_RESILIENCE, prepare_code_for_llm, resolve_token_budget

            pctx = getattr(self, "_pipeline_context", None)
            budget = resolve_token_budget(
                BUDGET_RESILIENCE,
                context=pctx,
                code_file_metadata=code_file.metadata,
            )

            # Build target lines from extracted calls (external dependency calls)
            target_lines: list[int] = sorted({call.line for call in context.function_calls[:20] if call.line > 0})

            truncated_code = prepare_code_for_llm(
                code_file.content,
                token_budget=budget,
                target_lines=target_lines or None,
                file_path=code_file.path,
                context=pctx,
            )

            # Build context-aware prompt (Tier 1: Context-Awareness)
            additional_context = ""

            # Add project intelligence if available
            if hasattr(self, "project_intelligence") and self.project_intelligence:
                pi = self.project_intelligence
                additional_context += "\n[PROJECT CONTEXT]:\n"

                if hasattr(pi, "entry_points") and pi.entry_points:
                    entry_points_str = ", ".join(pi.entry_points[:5])
                    additional_context += f"Entry Points: {entry_points_str}\n"

                if hasattr(pi, "critical_sinks") and pi.critical_sinks:
                    sinks_str = ", ".join(pi.critical_sinks[:5])
                    additional_context += f"Critical Operations: {sinks_str}\n"

                # Framework detection (context for resilience patterns)
                if hasattr(pi, "detected_frameworks") and pi.detected_frameworks:
                    fw_str = ", ".join(pi.detected_frameworks[:3])
                    additional_context += f"Framework: {fw_str}\n"

                # Architecture description (LLM-generated project overview)
                if hasattr(pi, "architecture") and pi.architecture:
                    additional_context += f"\n[ARCHITECTURE]:\n{pi.architecture[:300]}\n"

                logger.debug("project_intelligence_added_to_resilience_prompt", file=code_file.path)

            # Architectural Directives (human-authored rules from .warden/architecture.md)
            if hasattr(self, "architectural_directives") and self.architectural_directives:
                additional_context += f"\n[ARCHITECTURAL DIRECTIVES]:\n{self.architectural_directives[:500]}\n"

            # File dependency context (import graph)
            pctx = getattr(self, "_pipeline_context", None)
            if pctx and hasattr(pctx, "dependency_graph_forward"):
                rel_path = code_file.path
                try:
                    from pathlib import Path as _P

                    if pctx.project_root:
                        rel_path = str(_P(code_file.path).resolve().relative_to(pctx.project_root))
                except (ValueError, TypeError):
                    pass
                deps = pctx.dependency_graph_forward.get(rel_path, [])
                dependents = pctx.dependency_graph_reverse.get(rel_path, [])
                if deps:
                    additional_context += f"Depends on: {', '.join(deps[:5])}\n"
                if dependents:
                    additional_context += f"Depended by: {', '.join(dependents[:5])}\n"

            # Add prior findings if available - BATCH 2: Sanitized
            if hasattr(self, "prior_findings") and self.prior_findings:
                # Normalize and filter findings for this file
                file_findings = []
                for f in self.prior_findings:
                    normalized = normalize_finding_to_dict(f)
                    if normalized.get("location", "").startswith(code_file.path):
                        file_findings.append(normalized)

                if file_findings:
                    additional_context += "\n[PRIOR FINDINGS ON THIS FILE]:\n"
                    for finding in file_findings[:3]:
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
                                "prompt_injection_detected_resilience",
                                file=code_file.path,
                                finding_id=finding.get("id", "unknown"),
                                action="sanitized",
                            )
                            msg = "[SANITIZED: Suspicious content removed]"

                        additional_context += f"- [{severity}] {msg}\n"

                    logger.debug("prior_findings_added_to_resilience_prompt", file=code_file.path)

            # Add taint analysis context for severity-aware resilience
            file_taint_paths = self._taint_paths.get(code_file.path, [])
            if file_taint_paths:
                unsanitized = [p for p in file_taint_paths if not p.is_sanitized]
                if unsanitized:
                    additional_context += "\n[TAINT ANALYSIS — Unsanitized Data Flows]:\n"
                    for tp in unsanitized[:5]:
                        additional_context += (
                            f"  - {tp.source.name} (line {tp.source.line})"
                            f" -> {tp.sink.name} [{tp.sink_type}] (line {tp.sink.line})\n"
                        )
                    additional_context += (
                        "External dependencies on these tainted paths are HIGHER RISK — "
                        "missing resilience patterns here can lead to data corruption or security breaches.\n"
                    )

            # Build prompt with context
            user_prompt = f"""Analyze this code for chaos engineering:

File: {code_file.path}
Language: {code_file.language}

Context:
{context.to_llm_context()}

{related_context}

{additional_context}

Code:
```{code_file.language}
{truncated_code}
```

Identify external dependencies and missing resilience patterns. Return JSON."""

            request = LlmRequest(
                system_prompt=CHAOS_SYSTEM_PROMPT,
                user_message=user_prompt,
                temperature=0.0,  # Idempotent
            )

            # Call LLM with timeout
            response = await asyncio.wait_for(self.llm_service.send_with_tools_async(request), timeout=self._timeout)

            if response.success and response.content:
                findings = self._parse_llm_response(response.content, code_file.path)
                logger.info("chaos_llm_analysis_complete", findings=len(findings))
                # Success - reset failure count
                ResilienceFrame._llm_failure_count = 0
            else:
                logger.warning("chaos_llm_failed", error=response.error_message)
                self._record_llm_failure()

        except asyncio.TimeoutError:
            logger.warning("chaos_llm_timeout", timeout=self._timeout)
            self._record_llm_failure()
        except Exception as e:
            logger.error("chaos_llm_error", error=str(e))
            self._record_llm_failure()

        return findings

    def _record_llm_failure(self) -> None:
        """Record LLM failure and open circuit if threshold reached."""
        ResilienceFrame._llm_failure_count += 1
        if ResilienceFrame._llm_failure_count >= self.CIRCUIT_BREAKER_THRESHOLD:
            ResilienceFrame._llm_circuit_opened_at = time.perf_counter()
            logger.warning(
                "llm_circuit_opened",
                failures=ResilienceFrame._llm_failure_count,
                reset_seconds=self.CIRCUIT_BREAKER_RESET_SECONDS,
            )

    def _parse_llm_response(self, content: str, file_path: str) -> list[Finding]:
        """Parse LLM JSON response into findings."""
        from warden.shared.utils.json_parser import parse_json_from_llm

        findings: list[Finding] = []

        try:
            data = parse_json_from_llm(content)
            if not data:
                return findings

            for issue in data.get("issues", []):
                findings.append(
                    Finding(
                        id=f"{self.frame_id}-{issue.get('line', 0)}",
                        severity=issue.get("severity", "medium"),
                        message=issue.get("title", "Resilience issue"),
                        location=f"{file_path}:{issue.get('line', 1)}",
                        detail=f"{issue.get('description', '')}\n\nSuggestion: {issue.get('suggestion', '')}",
                        code=None,
                    )
                )

        except Exception as e:
            logger.warning("chaos_parse_error", error=str(e))

        return findings

    # =========================================================================
    # Fallback: Basic Analysis (No LLM)
    # =========================================================================

    def _basic_analysis(self, code_file: CodeFile, context: ChaosContext) -> list[Finding]:
        """
        Basic analysis without LLM.

        Simple heuristics for common issues:
        - Async functions without try/catch
        - Many external calls, few error handlers
        """
        findings: list[Finding] = []

        # Heuristic: async functions should have error handling
        if context.async_functions and context.error_handlers == 0:
            findings.append(
                Finding(
                    id=f"{self.frame_id}-no-error-handling",
                    severity="medium",
                    message=f"{len(context.async_functions)} async functions with no error handling",
                    location=f"{code_file.path}:1",
                    detail="Async operations should have try/catch for resilience",
                    code=None,
                )
            )

        # Heuristic: many calls, few handlers = risky
        call_count = len(context.function_calls)
        if call_count > 10 and context.error_handlers < 2:
            findings.append(
                Finding(
                    id=f"{self.frame_id}-insufficient-handlers",
                    severity="low",
                    message=f"{call_count} function calls with only {context.error_handlers} error handlers",
                    location=f"{code_file.path}:1",
                    detail="Consider adding more error handling for external calls",
                    code=None,
                )
            )

        return findings

    # =========================================================================
    # Result Creation
    # =========================================================================

    def _create_result(
        self, code_file: CodeFile, findings: list[Finding], context: ChaosContext, start_time: float
    ) -> FrameResult:
        """Create FrameResult with metadata."""
        duration = time.perf_counter() - start_time

        # Severity boost: if file has unsanitized taint paths, bump medium -> high
        file_taint_paths = self._taint_paths.get(code_file.path, [])
        has_unsanitized_taint = any(not tp.is_sanitized for tp in file_taint_paths) if file_taint_paths else False
        if has_unsanitized_taint:
            boosted = 0
            for f in findings:
                if f.severity == "medium":
                    f.severity = "high"
                    boosted += 1
            if boosted:
                logger.info(
                    "taint_severity_boost",
                    file=code_file.path,
                    boosted_findings=boosted,
                )

        # Determine status
        critical = sum(1 for f in findings if f.severity == "critical")
        high = sum(1 for f in findings if f.severity == "high")

        if critical > 0:
            status = "failed"
        elif high > 0:
            status = "warning"
        else:
            status = "passed"

        logger.info(
            "chaos_analysis_complete",
            file=code_file.path,
            status=status,
            findings=len(findings),
            duration_ms=int(duration * 1000),
        )

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=duration,
            issues_found=len(findings),
            is_blocker=self.is_blocker,
            findings=findings,
            metadata={
                "method": "chaos_engineering_v3",
                "imports_found": len(context.imports),
                "calls_found": len(context.function_calls),
                "async_functions": len(context.async_functions),
                "error_handlers": context.error_handlers,
                "has_lsp_context": bool(context.callers or context.callees),
            },
        )
