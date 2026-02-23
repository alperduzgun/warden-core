"""Centralized context slicing & token budget for all LLM consumers.

Single entry point for:
- Resolving triage-aware token budgets (fast vs deep tier)
- Preparing code content for LLM prompts (slicer → AST hints → truncation cascade)

Usage (2-3 lines in any frame/fortifier/phase):
    budget = resolve_token_budget(BUDGET_SECURITY, context=ctx, code_file_metadata=meta)
    code = prepare_code_for_llm(content, token_budget=budget, target_lines=lines,
                                file_path=path, context=ctx)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from warden.shared.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from warden.analysis.domain.code_graph import CodeGraph
    from warden.ast.domain.models import ASTNode

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Budget category constants
# ---------------------------------------------------------------------------
BUDGET_SECURITY = "security"
BUDGET_RESILIENCE = "resilience"
BUDGET_PROPERTY = "property"
BUDGET_FUZZ = "fuzz"
BUDGET_ORPHAN = "orphan"
BUDGET_FORTIFICATION = "fortification"
BUDGET_TRIAGE = "triage"
BUDGET_CLASSIFICATION = "classification"
BUDGET_ANALYSIS = "analysis"
BUDGET_DEFAULT = "default"

# ---------------------------------------------------------------------------
# Default budget table  {category: {"deep": tokens, "fast": tokens}}
# Overridable via LlmConfiguration.token_budgets or config.yaml llm.token_budgets
# ---------------------------------------------------------------------------
DEFAULT_TOKEN_BUDGETS: dict[str, dict[str, int]] = {
    BUDGET_SECURITY: {"deep": 2400, "fast": 400},
    BUDGET_RESILIENCE: {"deep": 3000, "fast": 500},
    BUDGET_PROPERTY: {"deep": 2000, "fast": 400},
    BUDGET_FUZZ: {"deep": 2000, "fast": 400},
    BUDGET_ORPHAN: {"deep": 3000, "fast": 1000},
    BUDGET_FORTIFICATION: {"deep": 3000, "fast": 800},
    BUDGET_TRIAGE: {"deep": 1000, "fast": 1000},
    BUDGET_CLASSIFICATION: {"deep": 2000, "fast": 1000},
    BUDGET_ANALYSIS: {"deep": 400, "fast": 250},
    BUDGET_DEFAULT: {"deep": 2400, "fast": 400},
}


@dataclass(frozen=True)
class TokenBudget:
    """Resolved token budget for a specific LLM call."""

    tokens: int
    category: str
    is_fast_tier: bool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_token_budget(
    category: str,
    *,
    llm_config: Any | None = None,
    context: Any | None = None,
    code_file_metadata: dict[str, Any] | None = None,
    is_fast_tier: bool | None = None,
) -> TokenBudget:
    """Resolve the token budget for a given category.

    Tier detection (in priority order):
    1. Explicit ``is_fast_tier`` parameter
    2. ``code_file_metadata["triage_lane"] == "middle_lane"``

    Budget source (in priority order):
    1. ``llm_config.token_budgets[category]`` (from config.yaml override)
    2. ``DEFAULT_TOKEN_BUDGETS[category]``
    3. ``DEFAULT_TOKEN_BUDGETS["default"]``
    """
    # Determine tier
    fast = False
    if is_fast_tier is not None:
        fast = is_fast_tier
    elif code_file_metadata and code_file_metadata.get("triage_lane") == "middle_lane":
        fast = True

    tier_key = "fast" if fast else "deep"

    # Resolve budget value — config override first
    budget_value: int | None = None

    # Try LlmConfiguration.token_budgets (populated from config.yaml)
    if llm_config is None and context is not None:
        llm_config = getattr(context, "llm_config", None)

    if llm_config is not None:
        config_budgets = getattr(llm_config, "token_budgets", None)
        if config_budgets and isinstance(config_budgets, dict):
            cat_entry = config_budgets.get(category)
            if cat_entry and isinstance(cat_entry, dict):
                budget_value = cat_entry.get(tier_key)

    # Fallback to built-in defaults
    if budget_value is None:
        defaults = DEFAULT_TOKEN_BUDGETS.get(category, DEFAULT_TOKEN_BUDGETS[BUDGET_DEFAULT])
        budget_value = defaults[tier_key]

    return TokenBudget(tokens=budget_value, category=category, is_fast_tier=fast)


def prepare_code_for_llm(
    content: str,
    *,
    token_budget: TokenBudget | int | None = None,
    target_lines: list[int] | None = None,
    ast_root: ASTNode | None = None,
    code_graph: CodeGraph | None = None,
    file_path: str = "",
    context: Any | None = None,
) -> str:
    """Prepare code content for an LLM prompt with cascading truncation.

    Cascade:
    1. Content fits in budget → return as-is
    2. ``ContextSlicerService.build_focused_context()`` (needs target_lines, tries AST)
    3. ``truncate_with_ast_hints()`` (needs target_lines)
    4. ``truncate_content_for_llm()`` (always works)

    Args:
        content: Full source code.
        token_budget: Token budget (TokenBudget or raw int). None → default budget.
        target_lines: 1-based line numbers of interest (dangerous calls, sinks).
        ast_root: Pre-parsed AST root. Auto-resolved from ``context`` if None.
        code_graph: Project code graph. Auto-resolved from ``context`` if None.
        file_path: File path for CodeGraph lookup and AST cache.
        context: PipelineContext — used to auto-resolve ast_root / code_graph.

    Returns:
        Truncated/focused code string ready for LLM.
    """
    from warden.shared.utils.token_utils import (
        estimate_tokens,
        truncate_content_for_llm,
        truncate_with_ast_hints,
    )

    from warden.shared.utils.prompt_sanitizer import PromptSanitizer

    def _sanitize(code: str) -> str:
        """Wrap code in XML boundary tags for prompt injection defense."""
        filename = file_path.rsplit("/", 1)[-1] if file_path else "source"
        return PromptSanitizer.sanitize_code_content(code, filename=filename)

    if not content:
        return content

    # Resolve budget
    max_tokens: int
    if token_budget is None:
        max_tokens = DEFAULT_TOKEN_BUDGETS[BUDGET_DEFAULT]["deep"]
    elif isinstance(token_budget, int):
        max_tokens = token_budget
    else:
        max_tokens = token_budget.tokens

    # 1. Fits in budget → return as-is (still sanitize — content is untrusted)
    if estimate_tokens(content) <= max_tokens:
        return _sanitize(content)

    # Auto-resolve AST root and CodeGraph from pipeline context
    if context is not None and (ast_root is None or code_graph is None):
        try:
            from warden.analysis.services.context_slicer import get_ast_and_graph_from_context

            resolved_ast, resolved_graph = get_ast_and_graph_from_context(context, file_path)
            if ast_root is None:
                ast_root = resolved_ast
            if code_graph is None:
                code_graph = resolved_graph
        except Exception:
            pass

    # 2. Context slicer (function-level extraction)
    if target_lines:
        try:
            from warden.analysis.services.context_slicer import ContextSlicerService

            result = ContextSlicerService().build_focused_context(
                file_content=content,
                file_path=file_path,
                target_lines=target_lines,
                ast_root=ast_root,
                code_graph=code_graph,
                token_budget=max_tokens,
            )
            if result and estimate_tokens(result) <= max_tokens:
                return _sanitize(result)
        except Exception as e:
            logger.debug("prepare_code_slicer_failed", error=str(e))

    # 3. AST-hints truncation (preserves dangerous-line windows)
    if target_lines:
        try:
            result = truncate_with_ast_hints(
                content,
                max_tokens=max_tokens,
                dangerous_lines=target_lines,
                preserve_start_lines=50,
                preserve_end_lines=20,
            )
            if result:
                return _sanitize(result)
        except Exception as e:
            logger.debug("prepare_code_ast_hints_failed", error=str(e))

    # 4. Plain truncation (always works)
    return _sanitize(
        truncate_content_for_llm(
            content,
            max_tokens=max_tokens,
            preserve_start_lines=30,
            preserve_end_lines=15,
        )
    )
