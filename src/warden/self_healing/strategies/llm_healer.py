"""LLM-powered healer — fallback diagnosis for unknown errors."""

from __future__ import annotations

import re
import traceback

from warden.self_healing.models import DiagnosticResult, ErrorCategory
from warden.self_healing.registry import HealerRegistry
from warden.self_healing.strategies.base import IHealerStrategy
from warden.self_healing.strategies.import_healer import _try_pip_install
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

_DIAGNOSIS_PROMPT = """You are a Python runtime error diagnostic assistant for the Warden security scanner.
Analyze this error and suggest a fix. If a pip package is missing, respond with:
INSTALL: package-name

Error: {error_type}: {error_message}
Traceback:
{traceback_str}
Context: {context}

Respond concisely. If a package install would fix this, ONLY output the INSTALL line.
If multiple packages are needed, put each on its own INSTALL: line.
If the issue is not a missing package, briefly explain the problem and suggest a fix."""


class LLMHealer(IHealerStrategy):
    """Fallback healer that asks the LLM fast tier for error diagnosis."""

    @property
    def name(self) -> str:
        return "llm_healer"

    @property
    def handles(self) -> list[ErrorCategory]:
        return [ErrorCategory.UNKNOWN]

    @property
    def priority(self) -> int:
        return 50

    async def can_heal(self, error: Exception, category: ErrorCategory) -> bool:
        return True

    async def heal(self, error: Exception, context: str = "") -> DiagnosticResult:
        tb_str = traceback.format_exception(type(error), error, error.__traceback__)
        tb_text = "".join(tb_str)[-2000:]

        llm_diagnosis = await _ask_llm_diagnosis(error, tb_text, context)

        if llm_diagnosis:
            packages = _parse_llm_fix(llm_diagnosis)
            if packages:
                installed = []
                for pkg in packages:
                    if _try_pip_install(pkg):
                        installed.append(pkg)

                if installed:
                    return DiagnosticResult(
                        fixed=True,
                        diagnosis=f"LLM diagnosed missing packages. Installed: {', '.join(installed)}",
                        packages_installed=installed,
                        should_retry=True,
                        error_category=ErrorCategory.UNKNOWN,
                        strategy_used=self.name,
                    )

            return DiagnosticResult(
                diagnosis=llm_diagnosis,
                suggested_action="Review the diagnosis above and apply the suggested fix manually.",
                error_category=ErrorCategory.UNKNOWN,
                strategy_used=self.name,
            )

        return DiagnosticResult(
            diagnosis=f"Unhandled {type(error).__name__}: {error}",
            suggested_action="Run 'warden doctor' to check your setup, or report this issue.",
            error_category=ErrorCategory.UNKNOWN,
            strategy_used=self.name,
        )


async def _ask_llm_diagnosis(
    error: Exception,
    traceback_str: str,
    context: str,
) -> str | None:
    """Send error to LLM fast tier for diagnosis."""
    try:
        import asyncio

        from warden.llm.factory import create_client

        client = create_client()

        if not await client.is_available_async():
            logger.debug("llm_unavailable_for_diagnosis")
            return None

        prompt = _DIAGNOSIS_PROMPT.format(
            error_type=type(error).__name__,
            error_message=str(error)[:500],
            traceback_str=traceback_str[:1500],
            context=context[:500] if context else "Warden security scan",
        )

        response = await asyncio.wait_for(
            client.complete_async(
                prompt,
                system_prompt="You are a concise Python error diagnostic assistant.",
                use_fast_tier=True,
            ),
            timeout=10.0,
        )

        if response and response.content:
            logger.info("llm_diagnosis_received", length=len(response.content))
            return response.content.strip()

    except Exception as e:
        logger.debug("llm_diagnosis_failed", error=str(e))

    return None


def _parse_llm_fix(diagnosis: str) -> list[str]:
    """Extract pip package names from LLM response."""
    packages: list[str] = []
    install_pattern = re.compile(r"INSTALL:\s*([a-zA-Z0-9_\-\[\]]+(?:\s+[a-zA-Z0-9_\-\[\]]+){0,2})")
    pip_pattern = re.compile(r"pip\s+install\s+([a-zA-Z0-9_\-\[\]]+)")

    for line in diagnosis.splitlines():
        line = line.strip()

        match = install_pattern.match(line)
        if match:
            pkg = match.group(1).strip()
            if pkg and pkg not in packages:
                packages.append(pkg)
            continue

        for pip_match in pip_pattern.finditer(line):
            pkg = pip_match.group(1).strip()
            if pkg and pkg not in packages:
                packages.append(pkg)

    return packages


HealerRegistry.register(LLMHealer())
