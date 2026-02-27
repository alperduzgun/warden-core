"""
AST Pre-Parser Service.

Centralized AST pre-parsing that populates PipelineContext.ast_cache
before frame execution, eliminating redundant per-frame parsing.

The ast_cache on PipelineContext is an LRU-bounded cache (see
``warden.pipeline.domain.lru_cache.LRUCache``).  Eviction is handled
automatically by the cache when entries exceed its maxsize, so this
module only needs to insert -- no manual eviction logic is required.

Process Isolation (#100):
    Tree-sitter parsing is wrapped in a ``ProcessPoolExecutor`` so that
    a crash (segfault, OOM) inside a single file's native parser does
    not bring down the entire scan.  Each file is parsed in a separate
    worker process; if the worker dies the future raises
    ``BrokenProcessPool`` which is caught and recorded as a ``failed``
    parse without aborting the scan.
"""

import asyncio
import os
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any

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

# Maximum number of worker processes for parse isolation.
# Defaults to half the available CPUs (minimum 1) to avoid starving the
# event loop.  Override via WARDEN_AST_WORKERS environment variable.
_DEFAULT_MAX_WORKERS = max(1, (os.cpu_count() or 2) // 2)


def _parse_file_in_worker(
    content: str,
    language_value: str,
    file_path: str,
) -> Any:
    """Top-level function executed in a worker process.

    Must be a module-level function (not a method or lambda) so that it
    is picklable for ``ProcessPoolExecutor``.

    Returns the ``ParseResult`` on success or raises on failure.
    """
    import asyncio as _asyncio

    from warden.ast.application.provider_registry import ASTProviderRegistry
    from warden.ast.domain.enums import CodeLanguage

    lang = CodeLanguage(language_value)

    registry = ASTProviderRegistry()
    _asyncio.run(registry.discover_providers())

    provider = registry.get_provider(lang)
    if provider is None:
        raise RuntimeError(f"No AST provider for {language_value}")

    if hasattr(provider, "ensure_grammar"):
        _asyncio.run(provider.ensure_grammar(lang))

    result = _asyncio.run(provider.parse(content, lang, file_path))
    return result


class ASTPreParser:
    """Pre-parses all code files and populates context.ast_cache.

    When ``use_process_isolation`` is *True* (the default), each file is
    parsed in a child process via ``ProcessPoolExecutor``.  A worker
    crash is recorded as a ``failed`` parse but the scan continues.
    """

    def __init__(
        self,
        timeout: float = _DEFAULT_TIMEOUT,
        *,
        use_process_isolation: bool = True,
        max_workers: int | None = None,
    ) -> None:
        self._timeout = timeout
        self._registry = None
        self._use_process_isolation = use_process_isolation
        self._max_workers = max_workers or _DEFAULT_MAX_WORKERS

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

        When process isolation is enabled, parsing is dispatched to a
        ``ProcessPoolExecutor`` so that native crashes (tree-sitter
        segfaults) in one file cannot kill the scan.  A worker crash is
        recorded as a ``failed`` entry in the stats and the scan
        continues with the remaining files.
        """
        if not code_files:
            return

        start = time.perf_counter()
        parsed = 0
        skipped_cached = 0
        skipped_unsupported = 0
        errors = 0
        failed = 0

        registry = await self._get_registry()

        from warden.ast.domain.enums import CodeLanguage

        if self._use_process_isolation:
            parsed, skipped_cached, skipped_unsupported, errors, failed = (
                await self._parse_with_process_isolation(
                    context, code_files, registry, CodeLanguage,
                )
            )
        else:
            parsed, skipped_cached, skipped_unsupported, errors, failed = (
                await self._parse_in_process(
                    context, code_files, registry, CodeLanguage,
                )
            )

        duration = time.perf_counter() - start

        if parsed > 0 or errors > 0 or failed > 0:
            logger.info(
                "ast_pre_parse_completed",
                parsed=parsed,
                skipped_cached=skipped_cached,
                skipped_unsupported=skipped_unsupported,
                errors=errors,
                failed=failed,
                duration_ms=round(duration * 1000, 1),
            )

    async def _parse_in_process(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
        registry: Any,
        CodeLanguage: Any,
    ) -> tuple[int, int, int, int, int]:
        """Original in-process parsing (no isolation)."""
        parsed = 0
        skipped_cached = 0
        skipped_unsupported = 0
        errors = 0
        failed = 0

        for code_file in code_files:
            if code_file.path in context.ast_cache:
                skipped_cached += 1
                continue

            try:
                lang = CodeLanguage(code_file.language.lower())
            except (ValueError, AttributeError):
                skipped_unsupported += 1
                continue

            provider = registry.get_provider(lang)
            if not provider:
                skipped_unsupported += 1
                continue

            if hasattr(provider, "ensure_grammar"):
                try:
                    await provider.ensure_grammar(lang)
                except Exception:
                    pass

            try:
                result = await asyncio.wait_for(
                    provider.parse(code_file.content, lang, code_file.path),
                    timeout=self._timeout,
                )
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

        return parsed, skipped_cached, skipped_unsupported, errors, failed

    async def _parse_with_process_isolation(
        self,
        context: PipelineContext,
        code_files: list[CodeFile],
        registry: Any,
        CodeLanguage: Any,
    ) -> tuple[int, int, int, int, int]:
        """Parse files using ProcessPoolExecutor for crash isolation.

        Each file's tree-sitter parse runs in a child process.  If the
        worker segfaults or raises, the exception is caught and the file
        is marked as ``failed``; the remaining files are still processed.
        """
        parsed = 0
        skipped_cached = 0
        skipped_unsupported = 0
        errors = 0
        failed = 0

        # Build the list of files eligible for parsing
        files_to_parse: list[CodeFile] = []
        for code_file in code_files:
            if code_file.path in context.ast_cache:
                skipped_cached += 1
                continue

            try:
                CodeLanguage(code_file.language.lower())
            except (ValueError, AttributeError):
                skipped_unsupported += 1
                continue

            provider = registry.get_provider(CodeLanguage(code_file.language.lower()))
            if not provider:
                skipped_unsupported += 1
                continue

            files_to_parse.append(code_file)

        if not files_to_parse:
            return parsed, skipped_cached, skipped_unsupported, errors, failed

        loop = asyncio.get_running_loop()

        # Use ProcessPoolExecutor for isolation.  The pool is created
        # per-call so that a broken pool from a previous crash does not
        # contaminate subsequent batches.
        executor = ProcessPoolExecutor(max_workers=self._max_workers)
        try:
            for code_file in files_to_parse:
                lang_value = code_file.language.lower()
                try:
                    future = loop.run_in_executor(
                        executor,
                        _parse_file_in_worker,
                        code_file.content,
                        lang_value,
                        code_file.path,
                    )
                    result = await asyncio.wait_for(future, timeout=self._timeout)
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
                    # BrokenProcessPool, RuntimeError from worker crash,
                    # or any other exception from the child process.
                    error_type = type(e).__name__
                    is_worker_crash = "BrokenProcessPool" in error_type or "broken" in str(e).lower()
                    if is_worker_crash:
                        logger.warning(
                            "ast_pre_parse_worker_crash",
                            file=code_file.path,
                            error=str(e),
                        )
                        failed += 1
                        # Re-create the executor after a broken pool
                        try:
                            executor.shutdown(wait=False)
                        except Exception:
                            pass
                        executor = ProcessPoolExecutor(max_workers=self._max_workers)
                    else:
                        logger.debug(
                            "ast_pre_parse_error",
                            file=code_file.path,
                            error=str(e),
                        )
                        errors += 1
        finally:
            executor.shutdown(wait=False)

        return parsed, skipped_cached, skipped_unsupported, errors, failed
