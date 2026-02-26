"""
AST Pre-Parser Service.

Centralized AST pre-parsing that populates PipelineContext.ast_cache
before frame execution, eliminating redundant per-frame parsing.

The ast_cache on PipelineContext is an LRU-bounded cache (see
``warden.pipeline.domain.lru_cache.LRUCache``).  Eviction is handled
automatically by the cache when entries exceed its maxsize, so this
module only needs to insert -- no manual eviction logic is required.
"""

import asyncio
import time

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)

# Default per-file parse timeout
_DEFAULT_TIMEOUT = 10.0

# Maximum AST cache entries to prevent OOM on large repos.
# Kept for backward-compat (tests import this constant).
# The authoritative limit lives in PipelineContext.max_ast_cache_entries.
_MAX_AST_CACHE_ENTRIES = 500


class ASTPreParser:
    """Pre-parses all code files and populates context.ast_cache."""

    def __init__(self, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._registry = None

    async def _get_registry(self):
        """Lazy-init the AST provider registry."""
        if self._registry is None:
            from warden.ast.application.provider_registry import ASTProviderRegistry

            self._registry = ASTProviderRegistry()
            await self._registry.discover_providers()
        return self._registry

    async def pre_parse_all_async(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
    ) -> None:
        """
        Pre-parse all code files and store results in context.ast_cache.

        Skips files already in cache, unsupported languages, and handles
        timeouts/errors gracefully (log + continue).

        The ast_cache is an LRU cache with automatic eviction; when the
        cache is full the least-recently-used entry is silently dropped
        on the next insertion.
        """
        if not code_files:
            return

        start = time.perf_counter()
        parsed = 0
        skipped_cached = 0
        skipped_unsupported = 0
        errors = 0

        registry = await self._get_registry()

        from warden.ast.domain.enums import CodeLanguage

        for code_file in code_files:
            # Skip if already cached
            if code_file.path in context.ast_cache:
                skipped_cached += 1
                continue

            # Resolve language enum
            try:
                lang = CodeLanguage(code_file.language.lower())
            except (ValueError, AttributeError):
                skipped_unsupported += 1
                continue

            # Get best provider for language
            provider = registry.get_provider(lang)
            if not provider:
                skipped_unsupported += 1
                continue

            # Ensure grammar is loaded (tree-sitter auto-install)
            if hasattr(provider, "ensure_grammar"):
                try:
                    await provider.ensure_grammar(lang)
                except Exception:
                    pass  # best-effort

            # Parse with per-file timeout
            try:
                result = await asyncio.wait_for(
                    provider.parse(code_file.content, lang, code_file.path),
                    timeout=self._timeout,
                )
                # LRUCache.__setitem__ handles eviction automatically
                context.ast_cache[code_file.path] = result
                parsed += 1
            except asyncio.TimeoutError:
                logger.debug(
                    "ast_pre_parse_timeout",
                    file=code_file.path,
                    timeout=self._timeout,
                )
                errors += 1
            except Exception as e:
                logger.debug(
                    "ast_pre_parse_error",
                    file=code_file.path,
                    error=str(e),
                )
                errors += 1

        duration = time.perf_counter() - start

        if parsed > 0 or errors > 0:
            logger.info(
                "ast_pre_parse_completed",
                parsed=parsed,
                skipped_cached=skipped_cached,
                skipped_unsupported=skipped_unsupported,
                errors=errors,
                duration_ms=round(duration * 1000, 1),
            )
