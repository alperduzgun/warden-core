"""
Gap Analyzer for Contract Comparison.

Compares consumer and provider contracts to identify:
1. Missing operations (consumer expects, provider missing)
2. Unused operations (provider has, consumer doesn't use)
3. Type mismatches between models
4. Field-level differences (optional vs required)
5. Enum value mismatches

Author: Warden Team
Version: 1.0.0
"""

import asyncio
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple

from warden.validation.frames.spec.models import (
    Contract,
    ContractGap,
    EnumDefinition,
    GapSeverity,
    ModelDefinition,
    OperationDefinition,
    SpecAnalysisResult,
)
from warden.validation.frames.spec.decision_cache import SpecDecisionCache
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MatchResult:
    """Result of matching an operation."""

    matched: bool
    provider_operation: Optional[OperationDefinition] = None
    similarity_score: float = 0.0
    match_type: str = "none"  # "exact", "normalized", "fuzzy", "none"


@dataclass
class GapAnalyzerConfig:
    """Configuration for gap analysis."""

    # Matching thresholds
    fuzzy_match_threshold: float = 0.8  # Minimum similarity for fuzzy match
    enable_fuzzy_matching: bool = True

    # What to check
    check_input_types: bool = True
    check_output_types: bool = True
    check_field_optionality: bool = True
    check_field_types: bool = True
    check_enum_values: bool = True

    # Severity mapping
    missing_operation_severity: GapSeverity = GapSeverity.CRITICAL
    unused_operation_severity: GapSeverity = GapSeverity.LOW
    type_mismatch_severity: GapSeverity = GapSeverity.HIGH
    nullable_mismatch_severity: GapSeverity = GapSeverity.MEDIUM
    missing_field_severity: GapSeverity = GapSeverity.HIGH
    enum_mismatch_severity: GapSeverity = GapSeverity.MEDIUM


class GapAnalyzer:
    """
    Analyzes gaps between consumer and provider contracts.

    Usage:
        analyzer = GapAnalyzer()
        result = analyzer.analyze(consumer_contract, provider_contract)

        for gap in result.gaps:
            print(f"{gap.severity}: {gap.message}")
    """

    def __init__(self, config: Optional[GapAnalyzerConfig] = None, llm_service: Optional[Any] = None, semantic_search_service: Optional[Any] = None):
        """Initialize analyzer with optional config."""
        self.config = config or GapAnalyzerConfig()
        self.llm_service = llm_service
        self.semantic_search_service = semantic_search_service
        self.decision_cache = SpecDecisionCache()

        # Common operation name patterns for normalization
        self._prefixes = ["get", "fetch", "load", "find", "retrieve", "query"]
        self._command_prefixes = ["create", "add", "insert", "post", "save", "submit", "process"]
        self._update_prefixes = ["update", "edit", "modify", "patch", "put"]
        self._delete_prefixes = ["delete", "remove", "destroy", "drop"]

    async def analyze(
        self,
        consumer: Contract,
        provider: Contract,
        consumer_platform: Optional[str] = None,
        provider_platform: Optional[str] = None,
    ) -> SpecAnalysisResult:
        """
        Analyze gaps between consumer and provider contracts.

        Note: Now async to support async semantic matching.

        Args:
            consumer: Contract representing what the consumer expects
            provider: Contract representing what the provider offers
            consumer_platform: Name of consumer platform (for reporting)
            provider_platform: Name of provider platform (for reporting)

        Returns:
            SpecAnalysisResult with all identified gaps
        """
        logger.info(
            "gap_analysis_started",
            consumer=consumer.name,
            provider=provider.name,
            consumer_ops=len(consumer.operations),
            provider_ops=len(provider.operations),
            llm_enabled=self.llm_service is not None,
        )

        result = SpecAnalysisResult(
            consumer_contract=consumer,
            provider_contract=provider,
            total_consumer_operations=len(consumer.operations),
            total_provider_operations=len(provider.operations),
        )

        # Build provider lookup maps
        provider_ops_map = self._build_operation_map(provider.operations)
        provider_models_map = {m.name: m for m in provider.models}
        provider_enums_map = {e.name: e for e in provider.enums}

        # Track matched provider operations
        matched_provider_ops: Set[str] = set()

        # 1. Check consumer operations against provider
        for consumer_op in consumer.operations:
            match = await self._match_operation(consumer_op, provider_ops_map)

            if match.matched and match.provider_operation:
                result.matched_operations += 1
                matched_provider_ops.add(match.provider_operation.name)

                # Check type compatibility
                type_gaps = self._check_operation_types(
                    consumer_op,
                    match.provider_operation,
                    provider_models_map,
                    consumer_platform,
                    provider_platform,
                )
                result.gaps.extend(type_gaps)
                result.type_mismatches += len(type_gaps)

            else:
                # Missing operation
                result.missing_operations += 1
                result.gaps.append(ContractGap(
                    gap_type="missing_operation",
                    severity=self.config.missing_operation_severity,
                    message=f"Operation '{consumer_op.name}' expected by consumer but not found in provider",
                    detail=self._get_missing_op_detail(consumer_op, provider_ops_map),
                    consumer_platform=consumer_platform,
                    provider_platform=provider_platform,
                    operation_name=consumer_op.name,
                    consumer_file=consumer_op.source_file,
                    consumer_line=consumer_op.source_line,
                ))

        # 2. Find unused provider operations
        for provider_op in provider.operations:
            if provider_op.name not in matched_provider_ops:
                result.unused_operations += 1
                result.gaps.append(ContractGap(
                    gap_type="unused_operation",
                    severity=self.config.unused_operation_severity,
                    message=f"Operation '{provider_op.name}' provided but not used by consumer",
                    consumer_platform=consumer_platform,
                    provider_platform=provider_platform,
                    operation_name=provider_op.name,
                    provider_file=provider_op.source_file,
                    provider_line=provider_op.source_line,
                ))

        # 3. Check model compatibility
        model_gaps = self._check_models(
            consumer.models,
            provider_models_map,
            consumer_platform,
            provider_platform,
        )
        result.gaps.extend(model_gaps)

        # 4. Check enum compatibility
        enum_gaps = self._check_enums(
            consumer.enums,
            provider_enums_map,
            consumer_platform,
            provider_platform,
        )
        result.gaps.extend(enum_gaps)

        logger.info(
            "gap_analysis_completed",
            total_gaps=len(result.gaps),
            critical=sum(1 for g in result.gaps if g.severity == GapSeverity.CRITICAL),
            high=sum(1 for g in result.gaps if g.severity == GapSeverity.HIGH),
            medium=sum(1 for g in result.gaps if g.severity == GapSeverity.MEDIUM),
            low=sum(1 for g in result.gaps if g.severity == GapSeverity.LOW),
        )

        return result

    def _build_operation_map(
        self,
        operations: List[OperationDefinition],
    ) -> Dict[str, OperationDefinition]:
        """Build a map of operations with normalized names."""
        op_map: Dict[str, OperationDefinition] = {}
        for op in operations:
            # Store with original name
            op_map[op.name] = op
            # Also store with normalized name
            normalized = self._normalize_operation_name(op.name)
            if normalized != op.name:
                op_map[normalized] = op
        return op_map

    async def _match_operation(
        self,
        consumer_op: OperationDefinition,
        provider_ops: Dict[str, OperationDefinition],
    ) -> MatchResult:
        """
        Try to match a consumer operation to a provider operation.

        Note: This method is async to support async semantic matching.
        """
        # 1. Exact match
        if consumer_op.name in provider_ops:
            return MatchResult(
                matched=True,
                provider_operation=provider_ops[consumer_op.name],
                similarity_score=1.0,
                match_type="exact",
            )

        # 2. Normalized match
        normalized_name = self._normalize_operation_name(consumer_op.name)
        if normalized_name in provider_ops:
            return MatchResult(
                matched=True,
                provider_operation=provider_ops[normalized_name],
                similarity_score=0.95,
                match_type="normalized",
            )

        # 3. Fuzzy match (if enabled)
        if self.config.enable_fuzzy_matching:
            best_match = self._fuzzy_match(consumer_op.name, provider_ops)
            if best_match:
                return best_match

        # 4. Semantic match (using LLM if available)
        if self.llm_service:
            semantic_match = await self._semantic_match_operation(consumer_op, provider_ops)
            if semantic_match:
                return semantic_match

        return MatchResult(matched=False)

    def _normalize_operation_name(self, name: str) -> str:
        """
        Normalize operation name for matching.

        Examples:
            getUsers -> users
            fetchUserList -> userList
            createUser -> user (command)
        """
        lower_name = name.lower()

        # Remove common prefixes
        for prefix in self._prefixes + self._command_prefixes + self._update_prefixes + self._delete_prefixes:
            if lower_name.startswith(prefix):
                # Keep the rest, preserve case from original
                suffix = name[len(prefix):]
                if suffix:
                    return suffix[0].lower() + suffix[1:]

        return name

    def _sanitize_operation_name(self, operation_name: str) -> Optional[str]:
        """
        Sanitize operation name to prevent prompt injection attacks.

        Security checks:
        1. Length validation (3-100 chars)
        2. Whitelist pattern (alphanumeric, underscore, dash, dot only)
        3. Check for prompt injection patterns

        Args:
            operation_name: Raw operation name from user code

        Returns:
            Sanitized operation name, or None if invalid
        """
        # Check length bounds (SECURITY: Prevent DOS via extremely long names)
        if len(operation_name) < 3 or len(operation_name) > 100:
            logger.warning(
                "operation_name_invalid_length",
                name=operation_name[:50],  # Truncate for logging
                length=len(operation_name),
            )
            return None

        # Whitelist pattern: only alphanumeric, underscore, dash, dot
        # SECURITY: Strict validation prevents injection via special chars
        sanitized = re.sub(r"[^a-zA-Z0-9_\-\.]", "", operation_name)
        if sanitized != operation_name:
            logger.warning(
                "operation_name_contains_invalid_chars",
                original=operation_name[:50],
                sanitized=sanitized[:50],
            )
            return None

        # SECURITY: Check for prompt injection patterns
        # These patterns indicate attempts to manipulate LLM behavior
        injection_patterns = [
            r"(?i)ignore\s+previous",
            r"(?i)ignore\s+all",
            r"(?i)system\s*:",
            r"(?i)assistant\s*:",
            r"(?i)user\s*:",
            r"(?i)forget\s+",
            r"(?i)disregard\s+",
            r"(?i)<\s*system",
            r"(?i)<\s*prompt",
        ]

        for pattern in injection_patterns:
            if re.search(pattern, sanitized):
                logger.error(
                    "prompt_injection_detected_in_operation_name",
                    name=sanitized[:50],
                    pattern=pattern,
                    security_event=True,  # Flag for security monitoring
                )
                return None

        return sanitized

    def _sanitize_rag_context(self, raw_context: str) -> str:
        """
        Sanitize RAG context to prevent prompt injection via retrieved code snippets.

        Security measures:
        1. Truncate to max 500 chars
        2. Remove non-ASCII characters (keep printable ASCII + newlines)
        3. Escape System: and User: prefixes that could confuse LLM

        Args:
            raw_context: Raw context from RAG system

        Returns:
            Sanitized context safe for LLM prompt
        """
        if not raw_context:
            return ""

        # SECURITY: Truncate to prevent context overflow attacks
        truncated = raw_context[:500]

        # SECURITY: Remove non-ASCII to prevent unicode injection tricks
        # Keep only printable ASCII (32-126) plus newline (10) and tab (9)
        sanitized_chars = []
        for char in truncated:
            code = ord(char)
            if (32 <= code <= 126) or code in (9, 10):
                sanitized_chars.append(char)

        sanitized = "".join(sanitized_chars)

        # SECURITY: Escape role prefixes that could manipulate conversation flow
        # Replace "System:" and "User:" with safe equivalents
        sanitized = re.sub(r"(?i)System\s*:", "[CONTEXT_SYSTEM]:", sanitized)
        sanitized = re.sub(r"(?i)User\s*:", "[CONTEXT_USER]:", sanitized)
        sanitized = re.sub(r"(?i)Assistant\s*:", "[CONTEXT_ASSISTANT]:", sanitized)

        return sanitized

    async def _semantic_match_operation(
        self,
        consumer_op: OperationDefinition,
        provider_ops: Dict[str, OperationDefinition],
    ) -> Optional[MatchResult]:
        """
        Use LLM to find semantic match with caching and RAG context.

        Note: Now properly async - no ThreadPoolExecutor wrapper needed.
        """
        # Only try if we have candidates (skip if empty)
        if not provider_ops:
            return None

        # SECURITY: Sanitize operation name to prevent prompt injection
        safe_query = self._sanitize_operation_name(consumer_op.name)
        if safe_query is None:
            logger.warning(
                "skipping_unsafe_semantic_query",
                query=consumer_op.name[:50],  # Truncate for safe logging
                reason="sanitization_failed",
            )
            return None

        # Filter candidates (Basic Bulkhead)
        candidates = []
        consumer_norm = self._normalize_operation_name(consumer_op.name).lower()

        for name, op in provider_ops.items():
            provider_norm = self._normalize_operation_name(name).lower()
            score = SequenceMatcher(None, consumer_norm, provider_norm).ratio()
            if score > 0.3:
                candidates.append(op)

        # 0. Check Cache (Persistence Layer)
        # Check against ALL candidates in filtered list to see if we have a definitive match or rejection
        # For simplicity in V1, we just check if this specific consumer_op has a KNOWN match in the provider set
        for candidate in candidates:
            decision = self.decision_cache.get_decision(safe_query, candidate.name)
            if decision and decision.get("matched"):
                # Cache HIT - Return immediately without LLM
                logger.debug("semantic_cache_hit", consumer=safe_query, provider=candidate.name)
                return MatchResult(
                    matched=True,
                    provider_operation=provider_ops[candidate.name],
                    similarity_score=decision.get("confidence", 0.9),
                    match_type="semantic_cached",
                )

        # If no cache hit, proceed to LLM
        if not candidates:
            candidates = list(provider_ops.values())[:20]

        start_time = time.perf_counter()

        # 1. RAG Context Retrieval (The Eyes)
        rag_context = ""
        if self.semantic_search_service:
            try:
                # Search for usages/definitions
                rag_query = f"usage of {safe_query} OR {safe_query} definition"
                # Run sync semantic search in thread pool to avoid blocking event loop
                result = await asyncio.to_thread(
                    self.semantic_search_service.search, rag_query
                )
                if result:
                    rag_context = str(result)
            except Exception as e:
                logger.warning("rag_context_failed", error=str(e))

        try:
            # LLM call - now properly async
            if hasattr(self.llm_service, 'find_best_match'):
                prompt_context = f"API Operation Matching. Consumer: {safe_query} ({consumer_op.operation_type.value})"
                if rag_context:
                    # SECURITY: Sanitize RAG context before embedding in prompt
                    safe_rag_context = self._sanitize_rag_context(rag_context)
                    prompt_context += f"\nCONTEXT:\n{safe_rag_context}"

                # Call LLM service (assuming it has async support or we use sync call)
                # Note: Most LLM services are sync, so we call directly
                # If timeout is needed, use asyncio.wait_for at call site
                match_name = self.llm_service.find_best_match(
                    query=safe_query,
                    options=[op.name for op in candidates],
                    context=prompt_context
                )

                duration = time.perf_counter() - start_time

                if match_name and match_name in provider_ops:
                    # Cache Success
                    self.decision_cache.cache_decision(
                        safe_query,
                        match_name,
                        matched=True,
                        confidence=0.9,
                        reasoning="LLM Match"
                    )

                    logger.info(
                        "semantic_match_success",
                        consumer=safe_query,
                        matched=match_name,
                        duration=f"{duration:.4f}s",
                        cached=True
                    )
                    return MatchResult(
                        matched=True,
                        provider_operation=provider_ops[match_name],
                        similarity_score=0.9,
                        match_type="semantic_llm",
                    )

        except Exception as e:
            logger.debug("llm_semantic_match_failed", error=str(e))

        return None

    def _get_verb_category(self, name: str) -> Optional[str]:
        """Get the CRUD verb category of an operation name."""
        lower = name.lower()
        for prefix in self._prefixes:
            if lower.startswith(prefix):
                return "query"
        for prefix in self._command_prefixes:
            if lower.startswith(prefix):
                return "create"
        for prefix in self._update_prefixes:
            if lower.startswith(prefix):
                return "update"
        for prefix in self._delete_prefixes:
            if lower.startswith(prefix):
                return "delete"
        return None

    def _fuzzy_match(
        self,
        consumer_name: str,
        provider_ops: Dict[str, OperationDefinition],
    ) -> Optional[MatchResult]:
        """Find best fuzzy match for operation name."""
        best_score = 0.0
        best_op: Optional[OperationDefinition] = None

        consumer_normalized = self._normalize_operation_name(consumer_name).lower()
        consumer_category = self._get_verb_category(consumer_name)

        for name, op in provider_ops.items():
            provider_normalized = self._normalize_operation_name(name).lower()

            # Skip if verb categories conflict (e.g. delete vs get)
            # Use the operation's original name (op.name) for category detection
            # since map keys may be normalized (no prefix)
            if consumer_category:
                provider_category = self._get_verb_category(op.name)
                if provider_category and consumer_category != provider_category:
                    continue

            # Calculate similarity
            score = SequenceMatcher(None, consumer_normalized, provider_normalized).ratio()

            if score > best_score:
                best_score = score
                best_op = op

        if best_score >= self.config.fuzzy_match_threshold and best_op:
            return MatchResult(
                matched=True,
                provider_operation=best_op,
                similarity_score=best_score,
                match_type="fuzzy",
            )

        return None

    def _get_missing_op_detail(
        self,
        consumer_op: OperationDefinition,
        provider_ops: Dict[str, OperationDefinition],
    ) -> str:
        """Get detail message for missing operation, suggesting similar ones."""
        suggestions: List[Tuple[str, float]] = []
        consumer_normalized = self._normalize_operation_name(consumer_op.name).lower()

        for name in provider_ops:
            provider_normalized = self._normalize_operation_name(name).lower()
            score = SequenceMatcher(None, consumer_normalized, provider_normalized).ratio()
            if score > 0.5:
                suggestions.append((name, score))

        suggestions.sort(key=lambda x: x[1], reverse=True)

        if suggestions:
            top_suggestions = [s[0] for s in suggestions[:3]]
            return f"Similar operations in provider: {', '.join(top_suggestions)}"

        return "No similar operations found in provider"

    def _check_operation_types(
        self,
        consumer_op: OperationDefinition,
        provider_op: OperationDefinition,
        provider_models: Dict[str, ModelDefinition],
        consumer_platform: Optional[str],
        provider_platform: Optional[str],
    ) -> List[ContractGap]:
        """Check type compatibility between matched operations."""
        gaps: List[ContractGap] = []

        # Check input type
        if self.config.check_input_types:
            if consumer_op.input_type and provider_op.input_type:
                if not self._types_compatible(consumer_op.input_type, provider_op.input_type):
                    gaps.append(ContractGap(
                        gap_type="input_type_mismatch",
                        severity=self.config.type_mismatch_severity,
                        message=f"Input type mismatch for '{consumer_op.name}'",
                        detail=f"Consumer expects '{consumer_op.input_type}', provider accepts '{provider_op.input_type}'",
                        consumer_platform=consumer_platform,
                        provider_platform=provider_platform,
                        operation_name=consumer_op.name,
                        consumer_file=consumer_op.source_file,
                        consumer_line=consumer_op.source_line,
                        provider_file=provider_op.source_file,
                        provider_line=provider_op.source_line,
                    ))
            elif consumer_op.input_type and not provider_op.input_type:
                gaps.append(ContractGap(
                    gap_type="input_type_missing",
                    severity=self.config.type_mismatch_severity,
                    message=f"Consumer sends input to '{consumer_op.name}' but provider doesn't expect it",
                    detail=f"Consumer sends '{consumer_op.input_type}'",
                    consumer_platform=consumer_platform,
                    provider_platform=provider_platform,
                    operation_name=consumer_op.name,
                    consumer_file=consumer_op.source_file,
                    consumer_line=consumer_op.source_line,
                ))

        # Check output type
        if self.config.check_output_types:
            if consumer_op.output_type and provider_op.output_type:
                if not self._types_compatible(consumer_op.output_type, provider_op.output_type):
                    gaps.append(ContractGap(
                        gap_type="output_type_mismatch",
                        severity=self.config.type_mismatch_severity,
                        message=f"Output type mismatch for '{consumer_op.name}'",
                        detail=f"Consumer expects '{consumer_op.output_type}', provider returns '{provider_op.output_type}'",
                        consumer_platform=consumer_platform,
                        provider_platform=provider_platform,
                        operation_name=consumer_op.name,
                        consumer_file=consumer_op.source_file,
                        consumer_line=consumer_op.source_line,
                        provider_file=provider_op.source_file,
                        provider_line=provider_op.source_line,
                    ))

        return gaps

    def _types_compatible(self, consumer_type: str, provider_type: str) -> bool:
        """Check if two types are compatible."""
        # Normalize types
        consumer_normalized = self._normalize_type(consumer_type)
        provider_normalized = self._normalize_type(provider_type)

        # Exact match
        if consumer_normalized == provider_normalized:
            return True

        # Check type aliases
        type_aliases = {
            "int": {"integer", "int32", "int64", "number"},
            "float": {"double", "decimal", "number", "real"},
            "string": {"str", "text"},
            "bool": {"boolean"},
            "datetime": {"date", "timestamp", "time"},
            "any": {"object", "dynamic", "unknown"},
            "list": {"array", "[]"},
        }

        for base_type, aliases in type_aliases.items():
            all_variants = {base_type} | aliases
            if consumer_normalized in all_variants and provider_normalized in all_variants:
                return True

        return False

    def _normalize_type(self, type_name: str) -> str:
        """Normalize type name for comparison."""
        if not type_name:
            return "any"

        # Remove common wrappers
        type_name = type_name.strip()

        # Remove array markers
        type_name = re.sub(r"\[\]$", "", type_name)
        type_name = re.sub(r"^List<(.+)>$", r"\1", type_name)
        type_name = re.sub(r"^Array<(.+)>$", r"\1", type_name)

        # Remove optional markers
        type_name = re.sub(r"\?$", "", type_name)
        type_name = re.sub(r"\s*\|\s*null", "", type_name)
        type_name = re.sub(r"\s*\|\s*undefined", "", type_name)

        return type_name.lower()

    def _check_models(
        self,
        consumer_models: List[ModelDefinition],
        provider_models: Dict[str, ModelDefinition],
        consumer_platform: Optional[str],
        provider_platform: Optional[str],
    ) -> List[ContractGap]:
        """Check model compatibility."""
        gaps: List[ContractGap] = []

        for consumer_model in consumer_models:
            provider_model = self._find_model_match(consumer_model.name, provider_models)

            if not provider_model:
                # Model might be platform-specific, just log it
                logger.debug(
                    "model_not_found_in_provider",
                    model=consumer_model.name,
                )
                continue

            # Check fields
            field_gaps = self._check_model_fields(
                consumer_model,
                provider_model,
                consumer_platform,
                provider_platform,
            )
            gaps.extend(field_gaps)

        return gaps

    def _find_model_match(
        self,
        consumer_model_name: str,
        provider_models: Dict[str, ModelDefinition],
    ) -> Optional[ModelDefinition]:
        """Find matching model in provider."""
        # Exact match
        if consumer_model_name in provider_models:
            return provider_models[consumer_model_name]

        # Try common suffixes
        suffixes = ["Dto", "DTO", "Request", "Response", "Model", "Entity", "Input", "Output"]
        base_name = consumer_model_name

        for suffix in suffixes:
            if consumer_model_name.endswith(suffix):
                base_name = consumer_model_name[:-len(suffix)]
                break

        # Try matching with different suffixes
        for suffix in [""] + suffixes:
            candidate = base_name + suffix
            if candidate in provider_models:
                return provider_models[candidate]

        return None

    def _check_model_fields(
        self,
        consumer_model: ModelDefinition,
        provider_model: ModelDefinition,
        consumer_platform: Optional[str],
        provider_platform: Optional[str],
    ) -> List[ContractGap]:
        """Check field compatibility between models."""
        gaps: List[ContractGap] = []

        provider_fields = {f.name: f for f in provider_model.fields}

        for consumer_field in consumer_model.fields:
            provider_field = provider_fields.get(consumer_field.name)

            if not provider_field:
                # Missing field
                if self.config.check_field_types:
                    gaps.append(ContractGap(
                        gap_type="missing_field",
                        severity=self.config.missing_field_severity,
                        message=f"Field '{consumer_field.name}' in '{consumer_model.name}' not found in provider",
                        consumer_platform=consumer_platform,
                        provider_platform=provider_platform,
                        field_name=consumer_field.name,
                        consumer_file=consumer_field.source_file,
                    ))
                continue

            # Check type compatibility
            if self.config.check_field_types:
                if not self._types_compatible(consumer_field.type_name, provider_field.type_name):
                    gaps.append(ContractGap(
                        gap_type="field_type_mismatch",
                        severity=self.config.type_mismatch_severity,
                        message=f"Type mismatch for field '{consumer_field.name}' in '{consumer_model.name}'",
                        detail=f"Consumer: {consumer_field.type_name}, Provider: {provider_field.type_name}",
                        consumer_platform=consumer_platform,
                        provider_platform=provider_platform,
                        field_name=consumer_field.name,
                        consumer_file=consumer_field.source_file,
                        provider_file=provider_field.source_file,
                    ))

            # Check optionality
            if self.config.check_field_optionality:
                if not consumer_field.is_optional and provider_field.is_optional:
                    gaps.append(ContractGap(
                        gap_type="nullable_mismatch",
                        severity=self.config.nullable_mismatch_severity,
                        message=f"Field '{consumer_field.name}' in '{consumer_model.name}' is required by consumer but optional in provider",
                        consumer_platform=consumer_platform,
                        provider_platform=provider_platform,
                        field_name=consumer_field.name,
                        consumer_file=consumer_field.source_file,
                        provider_file=provider_field.source_file,
                    ))

        return gaps

    def _check_enums(
        self,
        consumer_enums: List[EnumDefinition],
        provider_enums: Dict[str, EnumDefinition],
        consumer_platform: Optional[str],
        provider_platform: Optional[str],
    ) -> List[ContractGap]:
        """Check enum compatibility."""
        gaps: List[ContractGap] = []

        if not self.config.check_enum_values:
            return gaps

        for consumer_enum in consumer_enums:
            provider_enum = provider_enums.get(consumer_enum.name)

            if not provider_enum:
                # Enum might be platform-specific
                logger.debug(
                    "enum_not_found_in_provider",
                    enum=consumer_enum.name,
                )
                continue

            # Check for missing values
            consumer_values = set(consumer_enum.values)
            provider_values = set(provider_enum.values)

            missing_in_provider = consumer_values - provider_values
            extra_in_provider = provider_values - consumer_values

            if missing_in_provider:
                gaps.append(ContractGap(
                    gap_type="enum_value_missing",
                    severity=self.config.enum_mismatch_severity,
                    message=f"Enum '{consumer_enum.name}' values missing in provider: {', '.join(missing_in_provider)}",
                    detail=f"Consumer expects: {consumer_values}, Provider has: {provider_values}",
                    consumer_platform=consumer_platform,
                    provider_platform=provider_platform,
                    consumer_file=consumer_enum.source_file,
                    consumer_line=consumer_enum.source_line,
                    provider_file=provider_enum.source_file,
                    provider_line=provider_enum.source_line,
                ))

            if extra_in_provider:
                gaps.append(ContractGap(
                    gap_type="enum_value_extra",
                    severity=GapSeverity.LOW,
                    message=f"Enum '{consumer_enum.name}' has extra values in provider: {', '.join(extra_in_provider)}",
                    consumer_platform=consumer_platform,
                    provider_platform=provider_platform,
                    provider_file=provider_enum.source_file,
                    provider_line=provider_enum.source_line,
                ))

        return gaps


async def analyze_contracts(
    consumer: Contract,
    provider: Contract,
    config: Optional[GapAnalyzerConfig] = None,
) -> SpecAnalysisResult:
    """
    Convenience function to analyze contracts.

    Note: Now async to support async semantic matching.

    Args:
        consumer: Consumer contract
        provider: Provider contract
        config: Optional analyzer configuration

    Returns:
        SpecAnalysisResult with gaps
    """
    analyzer = GapAnalyzer(config)
    return await analyzer.analyze(consumer, provider)
