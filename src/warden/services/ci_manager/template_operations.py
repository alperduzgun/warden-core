"""
Template Operations Module

Template loading, processing, and version management.
"""

from __future__ import annotations

import importlib.resources
import re
from datetime import datetime, timezone
from typing import Any, Final

from .exceptions import TemplateError

try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


CURRENT_TEMPLATE_VERSION: Final[str] = "1.0.0"
CUSTOM_SECTION_START: Final[str] = "# WARDEN-CUSTOM-START"
CUSTOM_SECTION_END: Final[str] = "# WARDEN-CUSTOM-END"
VERSION_HEADER_PATTERN: Final[str] = r"^# Warden CI v(\d+\.\d+\.\d+)"

# Allowed template names (whitelist)
ALLOWED_TEMPLATES: Final[frozenset[str]] = frozenset(
    {"github.yml", "gitlab.yml", "warden-pr.yml", "warden-nightly.yml", "warden-release.yml"}
)


def load_template(template_name: str) -> str:
    """
    Load template content with validation.

    Raises:
        TemplateError: If template cannot be loaded
    """
    # Whitelist check (fail fast)
    if template_name not in ALLOWED_TEMPLATES:
        raise TemplateError(f"Template not allowed: {template_name}")

    try:
        content = importlib.resources.read_text("warden.templates.workflows", template_name)

        if not content or not content.strip():
            raise TemplateError(f"Template is empty: {template_name}")

        logger.debug("ci_template_loaded", template=template_name, size=len(content))
        return content

    except FileNotFoundError:
        raise TemplateError(f"Template not found: {template_name}")
    except Exception as e:
        raise TemplateError(f"Failed to load template '{template_name}': {e}")


def add_version_header(content: str) -> str:
    """Add version header to workflow content."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    header = (
        f"# Warden CI v{CURRENT_TEMPLATE_VERSION}\n"
        f"# Generated: {timestamp}\n"
        f"# Do not edit sections marked WARDEN-MANAGED\n\n"
    )
    return header + content


def extract_version(content: str) -> str | None:
    """Extract version from workflow file content."""
    if not content:
        return None
    match = re.search(VERSION_HEADER_PATTERN, content, re.MULTILINE)
    return match.group(1) if match else None


def extract_custom_sections(content: str) -> list[tuple[str, str]]:
    """Extract custom sections from workflow file."""
    if not content:
        return []

    custom_sections: list[tuple[str, str]] = []
    pattern = rf"{re.escape(CUSTOM_SECTION_START)}\s*(\w+)?\n(.*?){re.escape(CUSTOM_SECTION_END)}"

    for match in re.finditer(pattern, content, re.DOTALL):
        section_name = match.group(1) or "unnamed"
        section_content = match.group(2)
        custom_sections.append((section_name, section_content))

    return custom_sections


def merge_custom_sections(
    new_content: str,
    custom_sections: list[tuple[str, str]],
) -> str:
    """Merge custom sections into new content."""
    if not custom_sections:
        return new_content

    # Find insertion point (before jobs section or at end)
    insertion_point = new_content.find("\njobs:")
    if insertion_point == -1:
        insertion_point = len(new_content)

    custom_block = "\n"
    for name, content in custom_sections:
        custom_block += f"{CUSTOM_SECTION_START} {name}\n"
        custom_block += content
        if not content.endswith("\n"):
            custom_block += "\n"
        custom_block += f"{CUSTOM_SECTION_END}\n"

    return new_content[:insertion_point] + custom_block + new_content[insertion_point:]


def prepare_template_variables(branch: str, llm_config: dict[str, Any]) -> dict[str, str]:
    """Prepare template variables for substitution."""
    from .validation import validate_branch

    branch = validate_branch(branch)
    provider_id = str(llm_config.get("provider", "ollama"))

    # Build environment variables section
    ci_env_vars = ""
    ollama_setup = ""

    if provider_id == "ollama":
        ci_env_vars = "      OLLAMA_HOST: http://localhost:11434"
        ollama_setup = """      - name: Setup Ollama
        run: |
          curl -fsSL https://ollama.com/install.sh | sh
          ollama serve &
          echo "Waiting for Ollama to be ready..."
          for i in {1..30}; do
            if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
              echo "Ollama is ready!"
              break
            fi
            echo "Attempt $i/30: Ollama not ready yet..."
            sleep 1
          done
          ollama pull qwen2.5-coder:0.5b

"""
    else:
        key_var_map: dict[str, str] = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "groq": "GROQ_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "azure": "AZURE_OPENAI_API_KEY",
            "azure_openai": "AZURE_OPENAI_API_KEY",
        }
        key_var = key_var_map.get(provider_id)
        if key_var:
            ci_env_vars = f"      {key_var}: ${{{{ secrets.{key_var} }}}}"

    return {
        "branch": branch,
        "ci_llm_provider": provider_id,
        "ci_env_vars": ci_env_vars,
        "ollama_setup": ollama_setup,
    }
