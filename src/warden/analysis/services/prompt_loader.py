"""
PromptLoader — Loads LLM prompt templates with project-level override support.

Resolution order:
  1. .warden/prompts/{name}.md  — project-local override (in cwd or nearest ancestor)
  2. src/warden/analysis/prompts/{name}.md  — package default

Variable substitution replaces ``{{VARIABLE}}`` placeholders directly,
matching the existing PromptManager convention (``{{VAR}}`` placeholders).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# Safe prompt name: letters, digits, underscores, hyphens only (no path separators)
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Package-default prompts directory (sibling to this file's parent)
_DEFAULT_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Placeholder pattern: {{VAR_NAME}}
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


class PromptLoader:
    """Loads named prompt files with project-override support.

    Usage::

        loader = PromptLoader(project_root=Path("/path/to/project"))
        system_prompt = loader.load("verifier_system")
        batch_prompt = loader.load(
            "verifier_batch",
            batch_size=str(len(batch)),
            context_prompt=ctx,
            findings_summary=summary,
        )

    Override a prompt at the project level by placing a file at::

        .warden/prompts/verifier_system.md

    Any ``{{VARIABLE}}`` placeholders in the template are substituted with
    the keyword arguments passed to :meth:`load`.  Unknown placeholders are
    left as-is (no error).
    """

    def __init__(
        self,
        project_root: Optional[Path] = None,
        default_prompts_dir: Optional[Path] = None,
    ) -> None:
        self._project_root: Optional[Path] = (
            project_root.resolve() if project_root else self._find_project_root()
        )
        self._default_dir: Path = (default_prompts_dir or _DEFAULT_PROMPTS_DIR).resolve()
        # Simple dict cache — keyed by resolved file path, value is raw content.
        self._cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, prompt_name: str, **variables: str) -> str:
        """Return the rendered prompt for *prompt_name*, with variable substitution.

        Args:
            prompt_name: Prompt name without extension (e.g. ``"verifier_system"``).
            **variables: Values to substitute for ``{{VARIABLE}}`` placeholders.

        Returns:
            Rendered prompt string.

        Raises:
            FileNotFoundError: If neither project override nor package default exists.
        """
        path = self._resolve(prompt_name)
        raw = self._read_cached(path)
        return self._interpolate(raw, variables)

    def has_override(self, prompt_name: str) -> bool:
        """Return True if a project-level override exists for *prompt_name*."""
        if not _SAFE_NAME_RE.match(prompt_name):
            return False  # Fail safe — invalid names never have overrides
        override = self._override_path(prompt_name)
        return override is not None and override.exists()

    def invalidate_cache(self) -> None:
        """Clear in-memory cache (useful in tests or after file edits)."""
        self._cache.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve(self, prompt_name: str) -> Path:
        """Return the path to use, preferring project override over default."""
        if not _SAFE_NAME_RE.match(prompt_name):
            raise ValueError(
                f"Invalid prompt name {prompt_name!r}. "
                "Only letters, digits, underscores and hyphens are allowed."
            )
        override = self._override_path(prompt_name)
        if override and override.exists():
            logger.debug(
                "prompt_loader_override_found",
                prompt_name=prompt_name,
                path=str(override),
            )
            return override

        default = self._default_dir / f"{prompt_name}.md"
        if default.exists():
            return default

        raise FileNotFoundError(
            f"Prompt '{prompt_name}' not found.\n"
            f"  Checked override: {override}\n"
            f"  Checked default:  {default}"
        )

    def _override_path(self, prompt_name: str) -> Optional[Path]:
        """Return the expected project-override path, or None if no project root."""
        if self._project_root is None:
            return None
        expected_dir = (self._project_root / ".warden" / "prompts").resolve()
        candidate = (expected_dir / f"{prompt_name}.md").resolve()
        # is_relative_to() is exact — avoids the startswith prefix-collision bug
        # where /tmp/foo would be considered a parent of /tmp/foobar.
        try:
            candidate.relative_to(expected_dir)
        except ValueError:
            raise ValueError(
                f"Prompt path escapes the allowed directory: {candidate}"
            )
        return candidate

    def _read_cached(self, path: Path) -> str:
        key = str(path)
        if key not in self._cache:
            self._cache[key] = path.read_text(encoding="utf-8")
        return self._cache[key]

    @staticmethod
    def _interpolate(template: str, variables: dict[str, str]) -> str:
        """Replace ``{{KEY}}`` placeholders with values from *variables*.

        Unknown placeholders are left intact so that downstream code can
        detect them or pass them through to the LLM unchanged.
        """

        def replace(match: re.Match) -> str:
            key = match.group(1)
            return variables.get(key, match.group(0))

        return _PLACEHOLDER_RE.sub(replace, template)

    @staticmethod
    def _find_project_root() -> Optional[Path]:
        """Walk up from cwd to find the nearest directory containing `.warden/`.

        Returns None if no `.warden/` directory is found (prevents accidental
        reads from unrelated directories).
        """
        current = Path.cwd().resolve()
        for candidate in [current, *current.parents]:
            if (candidate / ".warden").is_dir():
                return candidate
        return None
