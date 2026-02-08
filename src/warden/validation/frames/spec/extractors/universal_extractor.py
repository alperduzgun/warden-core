"""
Universal Contract Extractor - Language & SDK Agnostic.

Reconstructed with fixes for precise extraction and custom output format.
"""

import asyncio
import time
import logging
import traceback
from pathlib import Path
from typing import List, Optional, Dict, Any, Set
from dataclasses import dataclass

from warden.validation.frames.spec.models import (
    Contract,
    OperationDefinition,
    OperationType,
    ModelDefinition,
    EnumDefinition,
    PlatformRole,
    PlatformType,
)
from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.models import ASTNode, ParseResult
from warden.ast.domain.enums import CodeLanguage as ASTCodeLanguage, ASTNodeType, ParseStatus
from warden.llm.types import LlmRequest
from warden.shared.infrastructure.logging import get_logger
from warden.shared.infrastructure.resilience import CircuitBreakerOpen, RetryExhausted
from warden.shared.infrastructure.exceptions import ExternalServiceError
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
# Small models (like Qwen 0.5b) tend to over-fit and hallucinate when provided with 
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

def parse_list_field(field_data: Any) -> List[Dict[str, str]]:
    """Helper to ensure fields are list of dicts or strings for YAML."""
    if isinstance(field_data, list):
        parsed = []
        for item in field_data:
            if isinstance(item, str) and ':' in item:
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
        }

    async def extract(self) -> Contract:
        logger.info("universal_extraction_started", project=str(self.project_root), role=self.role.value)
        
        # Initialize providers (Fixed Step 2592)
        await self.ast_registry.discover_providers()
        
        start_time = time.time()
        
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
        
        duration = int((time.time() - start_time) * 1000)
        logger.info("universal_extraction_completed", duration_ms=duration, operations=len(operations), stats=self.stats)
        
        return Contract(
            name="ohmylove",
            operations=operations,
            # Models/Enums extracted later if possible
        )

    def _discover_code_files(self) -> List[Path]:
        code_files = []
        extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.dart', '.java', '.kt', '.swift', '.go', '.rs'}
        exclude_dirs = {'node_modules', 'venv', '.venv', 'build', 'dist', '.git', '__pycache__', '.warden'}
        
        if not self.project_root.exists():
            return []
            
        for ext in extensions:
            # Recursive glob
            for p in self.project_root.rglob(f"*{ext}"):
                if not any(ex in p.parts for ex in exclude_dirs):
                    code_files.append(p)
                    
        return code_files # No limit

    async def _extract_api_candidates(self, code_files: List[Path]) -> List[APICallCandidate]:
        candidates = []
        # print(f"DEBUG: Starting scan of {len(code_files)} files")
        
        for file_path in code_files:
            try:
                language = self._detect_language(file_path)
                if not language: continue
                
                provider = self.ast_registry.get_provider(language)
                if not provider: continue
                
                try:
                    source = file_path.read_text(encoding='utf-8', errors='replace')
                except Exception:
                    continue
                    
                result = await provider.parse(source, language, str(file_path))
                
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
                # Print exception for visibility
                # print(f"CRITICAL ERROR scanning {file_path}: {e}")
                # traceback.print_exc()
                continue
                
        return candidates

    def _detect_language(self, file_path: Path) -> Optional[ASTCodeLanguage]:
        ext = file_path.suffix.lower()
        mapping = {
            '.py': ASTCodeLanguage.PYTHON,
            '.js': ASTCodeLanguage.JAVASCRIPT,
            '.ts': ASTCodeLanguage.TYPESCRIPT,
            '.tsx': ASTCodeLanguage.TYPESCRIPT,
            '.dart': ASTCodeLanguage.DART,
            '.java': ASTCodeLanguage.JAVA,
            '.kt': ASTCodeLanguage.KOTLIN,
            '.swift': ASTCodeLanguage.SWIFT,
            '.go': ASTCodeLanguage.GO,
            '.rs': ASTCodeLanguage.RUST,
        }
        return mapping.get(ext)

    def _find_call_expressions(self, node: ASTNode, debug_file: str = "") -> List[ASTNode]:
        """Recursive find call expressions."""
        calls = []
        
        raw_type = node.attributes.get('original_type', '')
        
        is_call = node.node_type == ASTNodeType.CALL_EXPRESSION
        
        # Fallback for Dart/unmapped nodes
        # TreeSitterProvider puts raw type in attributes['original_type']
        raw_type = node.attributes.get('original_type', '')
        if raw_type in ['method_invocation', 'function_expression_invocation', 'call_expression', 'constructor_invocation']:
             is_call = True
             
        # Dart selector check (expression_statement wrapping identifier + selector)
        if raw_type == 'expression_statement':
            has_selector = False
            has_identifier = False
            for child in node.children:
                ct = child.attributes.get('original_type', '')
                if ct == 'selector':
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

    def _create_candidate(self, node: ASTNode, source: str, file_path: Path) -> Optional[APICallCandidate]:
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
            ast_node=node
        )

    def _extract_function_name(self, node: ASTNode) -> Optional[str]:
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
        if not name: return False
        
        # Blocklist (Noise)
        blocklist = {
            "print", "println", "printf", "console.log", "console.error", "length", "toString",
            "add", "addAll", "remove", "clear", "contains", "map", "forEach", "filter", "reduce",
            "require", "import", "export", "json.decode", "json.encode",
            "setState", "initState", "dispose", "build", "super.initState",
            "Text", "Column", "Row", "Container", "SizedBox", "Padding", "Center", "Align"
        }
        if name in blocklist: return False
        
        lower = name.lower()
        if "test" in lower and "http" not in lower: return False
        
        # Allowlist
        api_keywords = {
            "http", "dio", "fetch", "axios", "api", "service", "client", "request",
            "query", "mutation", "subscription", "router", "app.get", "app.post",
            "db.", "firestore", "collection", "doc", "firebase"
        }
        
        is_api = any(k in lower for k in api_keywords)
        if is_api: return True
        
        return False

    def _heuristic_filter(self, candidates: List[APICallCandidate]) -> List[APICallCandidate]:
        return candidates # Identity (Trust creation filter)

    async def _extract_operations(self, calls: List[APICallCandidate]) -> List[OperationDefinition]:
        """Extract definitions for multiple candidates in parallel."""
        from asyncio import Semaphore, gather
        
        # Limit concurrency to 4 to avoid overwhelming local LLM/CPU
        semaphore = Semaphore(4)
        
        async def sem_extract(call):
            async with semaphore:
                try:
                    return await self._extract_single_operation(call)
                except CircuitBreakerOpen:
                    # If circuit breaker trips, we should ideally stop all
                    # but for now we just re-raise and let gather handle it
                    raise
                except Exception as e:
                    logger.debug("operation_extraction_failed", error=str(e))
                    return None

        # Run all extractions
        tasks = [sem_extract(call) for call in calls]
        results = await gather(*tasks, return_exceptions=False)
        
        # Filter out None results (failures)
        return [op for op in results if op is not None]

    async def _extract_single_operation(self, call: APICallCandidate) -> Optional[OperationDefinition]:
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
            system_prompt="You are a contract extraction specialist.",
            user_message=prompt,
            temperature=0.0
        )
        
        try:
            response = await asyncio.wait_for(
                self.llm_service.send_async(request),
                timeout=60.0 
            )
            
            # OrchestratedClient now raises ExternalServiceError on failure
            # So response.success is True here

            from warden.shared.utils.json_parser import parse_json_from_llm
            data = parse_json_from_llm(response.content)
            
            if not data:
                raise Exception("Invalid JSON")
                
            # Mapping
            op_type = OperationType.QUERY
            method = data.get('http_method', '').upper()
            if method in ['POST', 'PUT', 'DELETE', 'PATCH']:
                op_type = OperationType.COMMAND
                
            metadata = {}
            if 'http_method' in data: metadata['http_method'] = data['http_method']
            if 'endpoint' in data: metadata['endpoint'] = data['endpoint']
            if 'request_fields' in data: metadata['request_fields'] = parse_list_field(data['request_fields'])
            if 'response_fields' in data: metadata['response_fields'] = parse_list_field(data['response_fields'])
            
            return OperationDefinition(
                name=data.get('operation_name', call.function_name),
                operation_type=op_type,
                description=data.get('description'),
                metadata=metadata,
                source_file=call.file_path,
                source_line=call.line
            )
            
        except CircuitBreakerOpen:
            raise # Re-raise to stop extraction loop on upper level
            
        except (ExternalServiceError, RetryExhausted) as e:
            # Single operation failure (e.g. timeout, rate limit before breaker trips)
            # Log and fallback
            logger.warning("ai_extraction_failed_external", error=str(e))
            return self._create_fallback_operation(call)
            
        except Exception as e:
            # Other errors (JSON parse, etc)
            logger.debug("ai_extraction_failed", error=str(e))
            return self._create_fallback_operation(call)

    def _create_fallback_operation(self, call: APICallCandidate) -> OperationDefinition:
        return OperationDefinition(
            name=call.function_name,
            operation_type=OperationType.QUERY,
            source_file=call.file_path,
            source_line=call.line
        )

    async def _get_similar_patterns(self, call: APICallCandidate) -> str:
        return "" # Stub

    def _get_node_text(self, node: ASTNode, source: str) -> str:
        """Get source text for node using location (Fixed)."""
        if not node.location:
            return ""
            
        try:
            lines = source.splitlines()
            if not lines: return ""
            
            sl = node.location.start_line
            sc = node.location.start_column
            el = node.location.end_line
            ec = node.location.end_column
            
            if sl < 0 or sl >= len(lines): return ""
            if el > len(lines): el = len(lines)
            
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
        except Exception:
            return ""

    def _get_context(self, node: ASTNode, source: str) -> str:
        lines = source.splitlines()
        if not node.location: return ""
        sl = max(0, node.location.start_line - 10)
        el = min(len(lines), node.location.end_line + 10)
        return "\n".join(lines[sl:el])
