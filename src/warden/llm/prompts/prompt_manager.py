"""
Prompt Template Manager.

Loads, caches, and renders prompt templates with @include() and {{VAR}} support.
Security: Path traversal blocked, circular include detection, size limits.
"""

from __future__ import annotations

import re
from pathlib import Path

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Template directory
TEMPLATES_DIR = Path(__file__).parent / "templates"


class PromptTemplateError(Exception):
    """Raised when template loading or rendering fails."""

    pass


class PromptManager:
    """
    Manages prompt templates with include resolution and variable interpolation.

    Features:
    - @include(shared/_confidence_rules.txt) directive
    - {{VAR}} variable interpolation
    - Circular include detection (visited set + depth limit)
    - Path traversal protection
    - Template size limit (100KB)
    - LRU caching for performance
    """

    _MAX_INCLUDE_DEPTH = 10
    _MAX_TEMPLATE_SIZE = 100_000  # 100KB
    _INCLUDE_PATTERN = re.compile(r"@include\(([^)]+)\)")
    _VARIABLE_PATTERN = re.compile(r"\{\{(\w+)\}\}")

    def __init__(self, templates_dir: Path | None = None):
        self._templates_dir = (templates_dir or TEMPLATES_DIR).resolve()
        self._global_variables: dict[str, str] = {}
        self._cache: dict[str, str] = {}

    def load(self, template_name: str, variables: dict[str, str] | None = None) -> str:
        """
        Load and render a template by name.

        Args:
            template_name: Template filename (e.g., "analysis.txt")
            variables: Optional variables to interpolate

        Returns:
            Rendered template string

        Raises:
            PromptTemplateError: On missing template, circular include, path traversal
        """
        merged_vars = {**self._global_variables, **(variables or {})}

        # Check cache (without variables — raw template)
        cache_key = template_name
        if cache_key not in self._cache:
            raw = self._load_raw(template_name, visited=set(), depth=0)
            self._cache[cache_key] = raw

        raw = self._cache[cache_key]

        # Interpolate variables
        return self._interpolate(raw, merged_vars)

    def register_variables(self, **kwargs: str) -> None:
        """Register global variables available to all templates."""
        self._global_variables.update(kwargs)

    def invalidate_cache(self) -> None:
        """Clear the template cache."""
        self._cache.clear()

    def _load_raw(self, template_name: str, visited: set[str], depth: int) -> str:
        """Load raw template with include resolution."""
        if depth > self._MAX_INCLUDE_DEPTH:
            raise PromptTemplateError(
                f"Maximum include depth ({self._MAX_INCLUDE_DEPTH}) exceeded. "
                f"Possible circular include at '{template_name}'."
            )

        # Resolve and validate path
        template_path = self._resolve_safe_path(template_name)

        # Circular include detection
        canonical = str(template_path)
        if canonical in visited:
            raise PromptTemplateError(f"Circular include detected: '{template_name}' already included in chain.")
        visited.add(canonical)

        # Read template
        try:
            content = template_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise PromptTemplateError(f"Template not found: '{template_name}'")
        except Exception as e:
            raise PromptTemplateError(f"Failed to read template '{template_name}': {e}")

        # Size check
        if len(content) > self._MAX_TEMPLATE_SIZE:
            raise PromptTemplateError(
                f"Template '{template_name}' exceeds size limit ({len(content)} > {self._MAX_TEMPLATE_SIZE} bytes)."
            )

        # Resolve includes
        def replace_include(match: re.Match) -> str:
            include_name = match.group(1).strip()
            return self._load_raw(include_name, visited.copy(), depth + 1)

        content = self._INCLUDE_PATTERN.sub(replace_include, content)

        return content

    def _resolve_safe_path(self, template_name: str) -> Path:
        """Resolve template path with path traversal protection."""
        # Normalize and resolve
        candidate = (self._templates_dir / template_name).resolve()

        # Security: Ensure resolved path is within templates directory
        try:
            candidate.relative_to(self._templates_dir)
        except ValueError:
            raise PromptTemplateError(
                f"Path traversal blocked: '{template_name}' resolves outside templates directory."
            )

        return candidate

    def _interpolate(self, content: str, variables: dict[str, str]) -> str:
        """Interpolate {{VAR}} placeholders. Unknown variables left as-is."""

        def replace_var(match: re.Match) -> str:
            var_name = match.group(1)
            return variables.get(var_name, match.group(0))

        return self._VARIABLE_PATTERN.sub(replace_var, content)


# Module-level singleton
_prompt_manager: PromptManager | None = None


def get_prompt_manager() -> PromptManager:
    """Get the global PromptManager singleton."""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager
