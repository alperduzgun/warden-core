"""
Universal Contract Extractor - Language & SDK Agnostic.

Reconstructed with fixes for precise extraction and custom output format.
"""

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.enums import ASTNodeType, ParseStatus
from warden.ast.domain.enums import CodeLanguage as ASTCodeLanguage
from warden.ast.domain.models import ASTNode
from warden.llm.prompts.tool_instructions import get_tool_enhanced_prompt
from warden.llm.types import LlmRequest
from warden.shared.infrastructure.exceptions import ExternalServiceError
from warden.shared.infrastructure.logging import get_logger
from warden.shared.infrastructure.resilience import CircuitBreakerOpen, RetryExhausted
from warden.validation.frames.spec.models import (
    Contract,
    EnumDefinition,
    ModelDefinition,
    OperationDefinition,
    OperationType,
    PlatformRole,
)

# =============================================================================
# PURPOSE: Why SpecFrame? (The Problem it Solves)
# =============================================================================
# In modern distributed systems (e.g., Flutter mobile app + Node.js backend),
# API contracts often drift. Backend changes an endpoint, and the mobile app
# crashes. Traditional solutions (Swagger, OpenAPI) require manual maintenance
# which is often skipped or forgotten.
#
# SpecFrame Difference:
# If you only wrote unit tests, the Backend and Frontend could both pass
# individually. However, SpecFrame is the ONLY mechanism that puts BOTH
# codebases on the table simultaneously to say: "You are speaking different
# languages."
#
# Even if the engine is "ready", "invisible" endpoint drifts can cause silent
# failures. SpecFrame automatically answers: "What is missing or wrong in
# the web panel/consumer?"
# =============================================================================

logger = get_logger(__name__)

# =============================================================================
# CONTRACT_EXTRACTION_PROMPT Methodology (Zero-Hallucination Strategy)
# =============================================================================
# This prompt uses an abstract methodology instead of concrete 'invoice' examples.
# Small models (like Qwen 3b) tend to over-fit and hallucinate when provided with
# specific examples. By explaining the 'how-to' (look for HTTP verbs, string literals,
# and req.body pattern matching), we force the model to perform actual code analysis
# rather than template matching.
#
# Key Requirements for the Output:
# 1. Output must be PURE JSON without markdown or explanations.
# 2. Endpoints must be inferred from string literals in client/server calls.
# 3. Request/Response fields must be extracted from property access or arguments.
# =============================================================================
CONTRACT_EXTRACTION_PROMPT = """Analyze the code to extract API metadata.
Return ONLY valid JSON. No explanations. No markdown.

Methodology:
1. THE ENDPOINT: Find a string literal representing a URL or route (e.g., inside `http.get()` or `router.post()`). Use the exact path found.
2. THE METHOD: Determine the HTTP verb used (GET, POST, etc).
3. THE FIELDS: Extract property names from req.body, req.query, or call arguments.
4. THE RESPONSE: Identify fields returned in the response object.

Rule: Do NOT use placeholder strings like "ACTION" or "/PATH". Use only names found in the code.

Expected Format:
{
  "operation_name": "...",
  "http_method": "...",
  "endpoint": "...",
  "request_fields": ["field_name: type"],
  "response_fields": ["field_name: type"]
}

Code:
{code}
"""


@dataclass
class APICallCandidate:
    function_name: str
    code_snippet: str
    file_path: str
    line: int
    column: int
    context: str
    ast_node: ASTNode


def parse_list_field(field_data: Any) -> list[dict[str, str]]:
    """Helper to ensure fields are list of dicts or strings for YAML."""
    if isinstance(field_data, list):
        parsed = []
        for item in field_data:
            if isinstance(item, str) and ":" in item:
                parsed.append(item)
            else:
                parsed.append(str(item))
        return parsed
    return []


class UniversalContractExtractor:
    def __init__(
        self,
        project_root: Path,
        role: PlatformRole = PlatformRole.CONSUMER,
        llm_service: Any = None,
        semantic_search_service: Any = None,
    ):
        self.project_root = project_root
        self.role = role
        self.llm_service = llm_service
        self.semantic_search = semantic_search_service
        self.ast_registry = ASTProviderRegistry()

        self.stats = {
            "files_scanned": 0,
            "api_candidates_found": 0,
            "api_calls_confirmed": 0,
            "operations_extracted": 0,
            "models_extracted": 0,
            "enums_extracted": 0,
            "ai_enabled": False,  # Added ai_enabled to stats
        }
        self.ai_enabled = False  # Default to False, will be set by health check
        # Internal cache: avoids re-parsing the same file across detect/models/enums
        self._parse_cache: dict[str, Any] = {}
        # External cache reference (set by pipeline if available)
        self.ast_cache: dict[str, Any] | None = None

    async def extract(self) -> Contract:
        """
        Extract API contract using Universal Discovery logic (Gen 3.1).
        """
        start_time = time.time()
        logger.info("universal_extraction_started", project=self.project_root.name, role=self.role.value)

        # 0. Pre-flight AI Health Check
        ai_available = False
        if self.llm_service:
            try:
                ai_available = await self.llm_service.is_available_async()
                if not ai_available:
                    logger.warning(
                        "ai_extraction_degraded",
                        reason="LLM service or configured model not available. Entering heuristic-only mode.",
                        provider=self.llm_service.provider.value
                        if hasattr(self.llm_service, "provider")
                        else "unknown",
                    )
            except Exception as e:
                logger.warning("ai_health_check_failed", error=str(e))

        self.ai_enabled = ai_available
        self.stats["ai_enabled"] = ai_available  # Update stats

        # Initialize providers (Fixed Step 2592)
        await self.ast_registry.discover_providers()

        # 1. Discover files
        code_files = self._discover_code_files()
        logger.info("code_files_discovered", count=len(code_files))

        # 2. Extract Candidates
        candidates = await self._extract_api_candidates(code_files)
        logger.info("api_candidates_found", count=len(candidates))
        self.stats["api_candidates_found"] = len(candidates)

        # 3. Filter/Refine (Heuristics only for now)
        confirmed_candidates = self._heuristic_filter(candidates)
        logger.info("api_calls_confirmed", count=len(confirmed_candidates))
        self.stats["api_calls_confirmed"] = len(confirmed_candidates)

        # 4. Extract Operations (using LLM with fallback)
        operations = await self._extract_operations(confirmed_candidates)
        self.stats["operations_extracted"] = len(operations)

        # 5. Extract Models & Enums (New in Gen 3.1)
        models = await self._extract_models(code_files)
        enums = await self._extract_enums(code_files)
        self.stats["models_extracted"] = len(models)
        self.stats["enums_extracted"] = len(enums)

        duration = int((time.time() - start_time) * 1000)
        logger.info(
            "universal_extraction_completed", duration_ms=duration, operations=len(operations), stats=self.stats
        )

        return Contract(
            name=self.project_root.name,
            operations=operations,
            models=models,
            enums=enums,
        )

    async def _cached_parse(self, provider: Any, source: str, language: Any, file_path: str) -> Any:
        """Parse with local + external cache to avoid redundant parsing."""
        # Check local instance cache first
        if file_path in self._parse_cache:
            return self._parse_cache[file_path]
        # Check external pipeline ast_cache
        if self.ast_cache and file_path in self.ast_cache:
            result = self.ast_cache[file_path]
            self._parse_cache[file_path] = result
            return result
        # On-demand parse
        result = await provider.parse(source, language, file_path)
        self._parse_cache[file_path] = result
        return result

    def _discover_code_files(self) -> list[Path]:
        """Discover code files using global SafeFileScanner."""
        from warden.shared.utils.path_utils import SafeFileScanner

        scanner = SafeFileScanner(self.project_root, max_depth=15)
        extensions = {".py", ".js", ".ts", ".jsx", ".tsx", ".dart", ".java", ".kt", ".swift", ".go", ".rs"}

        files = scanner.scan(extensions)
        print(f"DEBUG [{self.role.name}]: Found {len(files)} files in {self.project_root}")
        return files

    async def _extract_api_candidates(self, code_files: list[Path]) -> list[APICallCandidate]:
        candidates = []

        for file_path in code_files:
            try:
                language = self._detect_language(file_path)
                if not language:
                    continue

                provider = self.ast_registry.get_provider(language)
                if not provider:
                    continue

                try:
                    source = file_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                result = await self._cached_parse(provider, source, language, str(file_path))

                if result.status != ParseStatus.SUCCESS or not result.ast_root:
                    continue

                # Check call expressions
                call_nodes = self._find_call_expressions(result.ast_root, str(file_path))

                for node in call_nodes:
                    cand = self._create_candidate(node, source, file_path)
                    if cand:
                        candidates.append(cand)

                self.stats["files_scanned"] += 1

            except Exception as e:
                logger.debug("file_scan_error", file=str(file_path), error=str(e))
                continue

        return candidates

    def _detect_language(self, file_path: Path) -> ASTCodeLanguage | None:
        ext = file_path.suffix.lower()
        mapping = {
            ".py": ASTCodeLanguage.PYTHON,
            ".js": ASTCodeLanguage.JAVASCRIPT,
            ".ts": ASTCodeLanguage.TYPESCRIPT,
            ".tsx": ASTCodeLanguage.TYPESCRIPT,
            ".dart": ASTCodeLanguage.DART,
            ".java": ASTCodeLanguage.JAVA,
            ".kt": ASTCodeLanguage.KOTLIN,
            ".swift": ASTCodeLanguage.SWIFT,
            ".go": ASTCodeLanguage.GO,
            ".rs": ASTCodeLanguage.RUST,
        }
        return mapping.get(ext)

    def _find_call_expressions(self, node: ASTNode, debug_file: str = "") -> list[ASTNode]:
        """Recursive find call expressions."""
        calls = []

        raw_type = node.attributes.get("original_type", "")

        is_call = node.node_type == ASTNodeType.CALL_EXPRESSION

        # Fallback for Dart/unmapped nodes
        # TreeSitterProvider puts raw type in attributes['original_type']
        raw_type = node.attributes.get("original_type", "")
        if raw_type in [
            "method_invocation",
            "function_expression_invocation",
            "call_expression",
            "constructor_invocation",
        ]:
            is_call = True

        # Dart await_expression: `await http.get(...)` parses as await_expression
        # with a selector child containing the actual call
        if raw_type == "await_expression":
            for child in node.children:
                ct = child.attributes.get("original_type", "")
                if ct in ("selector", "method_invocation", "call_expression"):
                    is_call = True
                    break

        # Dart selector check (expression_statement wrapping identifier + selector)
        if raw_type == "expression_statement":
            has_selector = False
            has_identifier = False
            for child in node.children:
                ct = child.attributes.get("original_type", "")
                if ct == "selector":
                    has_selector = True
                if child.node_type == ASTNodeType.IDENTIFIER:
                    has_identifier = True

            if has_selector and has_identifier:
                is_call = True

        if is_call:
            calls.append(node)

        for child in node.children:
            calls.extend(self._find_call_expressions(child, debug_file))
        return calls

    def _create_candidate(self, node: ASTNode, source: str, file_path: Path) -> APICallCandidate | None:
        name = self._extract_function_name(node)
        if not name or not self._is_relevant_candidate(name):
            return None

        code_snippet = self._get_node_text(node, source)
        context = self._get_context(node, source)

        return APICallCandidate(
            function_name=name,
            code_snippet=code_snippet,
            file_path=str(file_path),
            line=node.location.start_line if node.location else 0,
            column=node.location.start_column if node.location else 0,
            context=context,
            ast_node=node,
        )

    def _extract_function_name(self, node: ASTNode) -> str | None:
        # Robust accumulation of parts
        parts = []
        for child in node.children:
            if child.node_type == ASTNodeType.IDENTIFIER and child.name:
                parts.append(child.name)
            elif child.node_type == ASTNodeType.MEMBER_ACCESS:
                sub_parts = [c.name for c in child.children if c.name]
                if sub_parts:
                    parts.extend(sub_parts)

        if parts:
            return ".".join(parts)
        return node.name

    def _is_relevant_candidate(self, name: str) -> bool:
        if not name:
            return False

        # Blocklist (Noise)
        """Heuristic to filter out non-API calls."""
        name_lower = name.lower()

        # Denylist (Common noise)
        denylist = {
            "log",
            "print",
            "debug",
            "assert",
            "expect",
            "push",
            "pop",
            "clear",
            "add",
            "remove",
            "testwidgets",
            "pump",
            "pumpwidget",
            "tap",
            "entertext",
            "drag",
            "longpress",
            "setstate",
            "initstate",
            "dispose",
            "build",
            "render",
        }
        if name_lower in denylist or any(d == name_lower.split(".")[-1] for d in denylist):
            return False

        # Allowlist (HTTP/API keywords) - Use exact/word boundary matching where possible
        api_keywords = {
            "http",
            "dio",
            "fetch",
            "axios",
            "api",
            "service",
            "client",
            "request",
            "query",
            "mutation",
            "subscription",
            "router",
            "app.get",
            "app.post",
            "db.",
            "firestore",
            "collection",
            "doc",
            "firebase",
            "send",
            "call",
            "remote",
            "endpoint",
            "auth",
            "token",
        }

        # HTTP Methods (Whole word only to avoid testWidgets matching 'get')
        http_methods = {"get", "post", "put", "delete", "patch"}

        # Score-based relevance
        score = 0
        if any(k in name_lower for k in api_keywords):
            score += 2

        # Match HTTP methods as separate components (e.g. .get() or getSomething)
        name_parts = name_lower.replace("_", ".").split(".")
        if any(m in name_parts for m in http_methods):
            score += 2

        if any(name_lower.startswith(k) for k in ["api", "service", "http"]):
            score += 1

        return score >= 2

    def _heuristic_filter(self, candidates: list[APICallCandidate]) -> list[APICallCandidate]:
        """Filter candidates using lightweight heuristics beyond _is_relevant_candidate.

        Removes duplicates (same function+file+line) and candidates with
        empty code snippets that provide no value for extraction.
        """
        seen = set()
        filtered = []
        for c in candidates:
            key = (c.function_name, c.file_path, c.line)
            if key in seen:
                continue
            seen.add(key)
            if not c.code_snippet.strip():
                continue
            filtered.append(c)
        return filtered

    async def _extract_operations(self, candidates: list[APICallCandidate]) -> list[OperationDefinition]:
        """Extract high-level operation definitions using AI/Heuristics."""
        if not candidates:
            return []

        # If AI is disabled or unavailable, use heuristics only
        if not self.ai_enabled:
            logger.info("using_pure_heuristics_for_operations", count=len(candidates))
            return [self._create_fallback_operation(c) for c in candidates]

        # Batch processing with AI
        from warden.shared.infrastructure.resilience.parallel import ParallelBatchExecutor

        executor = ParallelBatchExecutor(concurrency_limit=4, item_timeout=30.0)

        results = await executor.execute_batch(
            items=candidates,  # Changed from 'calls' to 'candidates'
            task_fn=self._extract_single_operation,
            batch_name="spec_operation_extraction",
        )

        # Filter out None and return
        return [op for op in results if op is not None]

    async def _extract_single_operation(self, call: APICallCandidate) -> OperationDefinition | None:
        # Fallback if no LLM
        if not self.llm_service:
            return self._create_fallback_operation(call)

        snippets = await self._get_similar_patterns(call)

        prompt = f"""{CONTRACT_EXTRACTION_PROMPT}

API Call:
Function: {call.function_name}
Code: {call.code_snippet}

Context:
{call.context}

Similar Patterns:
{snippets}

Extract details.
"""
        request = LlmRequest(
            system_prompt=get_tool_enhanced_prompt("You are a contract extraction specialist."),
            user_message=prompt,
            temperature=0.0,
        )

        try:
            response = await asyncio.wait_for(self.llm_service.send_with_tools_async(request), timeout=60.0)

            # OrchestratedClient now raises ExternalServiceError on failure
            # So response.success is True here

            from warden.shared.utils.json_parser import parse_json_from_llm

            data = parse_json_from_llm(response.content)

            if not data:
                raise Exception("Invalid JSON")

            # Mapping
            op_type = OperationType.QUERY
            method = data.get("http_method", "").upper()
            if method in ["POST", "PUT", "DELETE", "PATCH"]:
                op_type = OperationType.COMMAND

            metadata = {}
            if "http_method" in data:
                metadata["http_method"] = data["http_method"]
            if "endpoint" in data:
                metadata["endpoint"] = data["endpoint"]
            if "request_fields" in data:
                metadata["request_fields"] = parse_list_field(data["request_fields"])
            if "response_fields" in data:
                metadata["response_fields"] = parse_list_field(data["response_fields"])

            return OperationDefinition(
                name=data.get("operation_name", call.function_name),
                operation_type=op_type,
                description=data.get("description"),
                metadata=metadata,
                source_file=call.file_path,
                source_line=call.line,
            )

        except CircuitBreakerOpen:
            raise  # Re-raise to stop extraction loop on upper level

        except (ExternalServiceError, RetryExhausted) as e:
            # Single operation failure (e.g. timeout, rate limit before breaker trips)
            # Log and fallback
            logger.warning("ai_extraction_failed_external", error=str(e))
            return self._create_fallback_operation(call)

        except Exception as e:
            # Other errors (JSON parse, etc)
            logger.debug("ai_extraction_failed", error=str(e))
            return self._create_fallback_operation(call)

    async def _extract_models(self, code_files: list[Path]) -> list[ModelDefinition]:
        """Extract data models (Classes/Interfaces) from code files."""
        models = []
        for file_path in code_files:
            try:
                language = self._detect_language(file_path)
                if not language:
                    continue
                provider = self.ast_registry.get_provider(language)
                if not provider:
                    continue

                source = file_path.read_text(encoding="utf-8", errors="replace")
                result = await self._cached_parse(provider, source, language, str(file_path))
                if result.status != ParseStatus.SUCCESS or not result.ast_root:
                    continue

                # Find all classes/interfaces
                model_nodes = self._find_model_nodes(result.ast_root)
                for node in model_nodes:
                    model = self._create_model_definition(node, source, file_path)
                    if model:
                        models.append(model)
            except Exception as e:
                logger.debug("model_extraction_error", file=str(file_path), error=str(e))
        return models

    async def _extract_enums(self, code_files: list[Path]) -> list[EnumDefinition]:
        """Extract Enums from code files."""
        enums = []
        for file_path in code_files:
            try:
                language = self._detect_language(file_path)
                if not language:
                    continue
                provider = self.ast_registry.get_provider(language)
                if not provider:
                    continue

                source = file_path.read_text(encoding="utf-8", errors="replace")
                result = await self._cached_parse(provider, source, language, str(file_path))
                if result.status != ParseStatus.SUCCESS or not result.ast_root:
                    continue

                # Find all enums
                enum_nodes = self._find_enum_nodes(result.ast_root)
                for node in enum_nodes:
                    enum = self._create_enum_definition(node, source, file_path)
                    if enum:
                        enums.append(enum)
            except Exception as e:
                logger.debug("enum_extraction_error", file=str(file_path), error=str(e))
        return enums

    def _find_model_nodes(self, node: ASTNode) -> list[ASTNode]:
        """Find nodes that represent data models."""
        models = []
        if node.node_type in [ASTNodeType.CLASS, ASTNodeType.INTERFACE]:
            # Filter out known non-model classes (UI, etc)
            name = node.name or ""
            exclude_keywords = {"Widget", "State", "Page", "Screen", "View", "Controller", "Bloc"}

            # Ensure it's not actually an enum (double check heuristic)
            raw_type = node.attributes.get("original_type", "").lower()

            if not any(k in name for k in exclude_keywords) and "enum" not in raw_type:
                models.append(node)

        for child in node.children:
            models.extend(self._find_model_nodes(child))
        return models

    def _find_enum_nodes(self, node: ASTNode) -> list[ASTNode]:
        """Find enum nodes based on universal type or original type heuristic."""
        enums = []
        if node.node_type == ASTNodeType.ENUM:
            enums.append(node)
        else:
            # Fallback for unmapped enums
            raw_type = node.attributes.get("original_type", "").lower()
            if "enum" in raw_type:
                enums.append(node)

        for child in node.children:
            enums.extend(self._find_enum_nodes(child))
        return enums

    def _create_model_definition(self, node: ASTNode, source: str, file_path: Path) -> ModelDefinition | None:
        from warden.validation.frames.spec.models import FieldDefinition

        fields = []

        def find_fields_recursive(curr: ASTNode):
            for child in curr.children:
                # Check for FIELD, PROPERTY, or ASSIGNMENT (Python fields are mapped as FIELD now, but ASSIGNMENT as safety)
                if child.node_type in [ASTNodeType.FIELD, ASTNodeType.PROPERTY, ASTNodeType.ASSIGNMENT]:
                    field_name = child.name or ""
                    # Attempt to extract type (heuristic)
                    field_type = "any"

                    # First check for type_annotation attribute (Python fields)
                    if "type_annotation" in child.attributes:
                        field_type = child.attributes["type_annotation"]
                    else:
                        # Fallback: search children for type identifier
                        for grandchild in child.children:
                            if grandchild.node_type == ASTNodeType.IDENTIFIER and grandchild.name != field_name:
                                field_type = grandchild.name
                                break

                    if field_name:
                        fields.append(
                            FieldDefinition(
                                name=field_name,
                                type_name=field_type,
                                source_file=str(file_path),
                                source_line=child.location.start_line if child.location else 0,
                            )
                        )
                # Don't recurse into other classes/functions
                elif child.node_type not in [
                    ASTNodeType.CLASS,
                    ASTNodeType.INTERFACE,
                    ASTNodeType.FUNCTION,
                    ASTNodeType.METHOD,
                ]:
                    find_fields_recursive(child)

        find_fields_recursive(node)

        if not fields:
            return None

        return ModelDefinition(
            name=node.name or "UnknownModel",
            fields=fields,
            source_file=str(file_path),
            source_line=node.location.start_line if node.location else 0,
        )

    def _create_enum_definition(self, node: ASTNode, source: str, file_path: Path) -> EnumDefinition | None:
        values = []
        # In many grammars, enum values are children with specific types
        for child in node.children:
            # Direct identifier (some languages)
            if child.node_type == ASTNodeType.IDENTIFIER and child.name:
                name = child.name.strip()
                if len(name) > 1 and name[0].isalpha():
                    values.append(name)
            # Python/Java/etc: enum values are assignments (e.g., PENDING = "pending")
            elif child.node_type == ASTNodeType.ASSIGNMENT and child.name:
                # The assignment itself has the enum value name
                name = child.name.strip()
                if len(name) > 1 and name[0].isalpha():
                    values.append(name)

        # Even if no values extracted, return the enum (it might be empty or abstract)
        # But at least one value is expected for a valid enum
        if not values:
            return None

        return EnumDefinition(
            name=node.name or "UnknownEnum",
            values=list(set(values)),  # Deduplicate
            source_file=str(file_path),
            source_line=node.location.start_line if node.location else 0,
        )

    def _find_annotated_nodes(self, node: ASTNode) -> list[tuple[ASTNode, str]]:
        """Find methods or classes with API annotations."""
        found = []

        # Check children for annotations
        for child in node.children:
            original_type = child.attributes.get("original_type", "")
            if "annotation" in original_type or "decorator" in original_type:
                # If this node has an API keyword in its name (e.g. @GET)
                ann_text = child.name or ""
                if any(k in ann_text.upper() for k in ["GET", "POST", "PUT", "DELETE", "PATCH", "INTERNAL"]):
                    found.append((node, ann_text))

            # Recurse
            found.extend(self._find_annotated_nodes(child))

        return found

    def _create_fallback_operation(self, call: APICallCandidate) -> OperationDefinition:
        """
        DEGRADED MODE: Creates a heuristic-based operation definition when AI fails.
        """
        logger.info("creating_fallback_operation", function=call.function_name, reason="ai_unavailable")
        return OperationDefinition(
            name=call.function_name,
            operation_type=OperationType.QUERY,  # Default to Query for safety
            description="Auto-extracted (AI extraction skipped/failed)",
            source_file=call.file_path,
            source_line=call.line,
        )

    async def _get_similar_patterns(self, call: APICallCandidate) -> str:
        """Retrieve similar API patterns via semantic search if available."""
        if not self.semantic_search:
            return ""
        try:
            results = await self.semantic_search.search(call.function_name, limit=3)
            if results:
                return "\n".join(str(r) for r in results)
        except Exception as e:
            logger.debug("semantic_search_failed", function=call.function_name, error=str(e))
        return ""

    def _get_node_text(self, node: ASTNode, source: str) -> str:
        """Get source text for node using location (Fixed)."""
        if not node.location:
            return ""

        try:
            lines = source.splitlines()
            if not lines:
                return ""

            sl = node.location.start_line
            sc = node.location.start_column
            el = node.location.end_line
            ec = node.location.end_column

            if sl < 0 or sl >= len(lines):
                return ""
            if el > len(lines):
                el = len(lines)

            if sl == el:
                if sl < len(lines):
                    return lines[sl][sc:ec]
                return ""

            result = []
            if sl < len(lines):
                result.append(lines[sl][sc:])
            for i in range(sl + 1, el):
                if i < len(lines):
                    result.append(lines[i])
            if el < len(lines):
                result.append(lines[el][:ec])

            return "\\n".join(result)
        except (IndexError, UnicodeDecodeError, AttributeError):
            return ""

    def _get_context(self, node: ASTNode, source: str) -> str:
        lines = source.splitlines()
        if not node.location:
            return ""
        sl = max(0, node.location.start_line - 10)
        el = min(len(lines), node.location.end_line + 10)
        return "\n".join(lines[sl:el])
