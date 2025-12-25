"""Template resolver for config.yaml ${VAR} syntax."""

import copy
import re
from typing import Any, cast

import structlog

from .secret_manager import SecretManager

logger = structlog.get_logger(__name__)


class TemplateResolver:
    """Resolves ${VAR} template variables in configuration.

    Used to process .warden/config.yaml after loading.

    Example:
        # config.yaml content:
        # llm:
        #   azure:
        #     api_key: "${AZURE_OPENAI_API_KEY}"
        #     endpoint: "${AZURE_OPENAI_ENDPOINT}"

        resolver = TemplateResolver()
        config = yaml.safe_load(open("config.yaml"))
        resolved = await resolver.resolve(config)
        # Now config["llm"]["azure"]["api_key"] has the actual value
    """

    TEMPLATE_PATTERN = re.compile(r"\$\{([^}]+)\}")

    def __init__(self, secret_manager: SecretManager | None = None):
        """Initialize the resolver.

        Args:
            secret_manager: SecretManager to use. If None, creates one.
        """
        self._secret_manager = secret_manager or SecretManager()

    async def resolve(self, config: dict[str, Any]) -> dict[str, Any]:
        """Resolve all ${VAR} templates in a config dictionary.

        Args:
            config: Configuration dictionary with ${VAR} templates.

        Returns:
            Configuration with templates resolved.
        """
        # Deep copy to avoid modifying original
        result = copy.deepcopy(config)
        resolved = await self._resolve_value(result)
        return cast(dict[str, Any], resolved)

    async def _resolve_value(self, value: Any) -> Any:
        """Recursively resolve templates in a value.

        Args:
            value: Any value (str, dict, list, or primitive).

        Returns:
            Value with templates resolved.
        """
        if isinstance(value, str):
            return await self._resolve_string(value)
        elif isinstance(value, dict):
            return {k: await self._resolve_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [await self._resolve_value(item) for item in value]
        else:
            return value

    async def _resolve_string(self, value: str) -> str:
        """Resolve ${VAR} patterns in a string.

        Supports multiple variables in one string:
        "https://${HOST}:${PORT}/api" -> "https://example.com:8080/api"

        Args:
            value: String possibly containing ${VAR} patterns.

        Returns:
            String with templates resolved (unresolved left as-is).
        """
        matches = self.TEMPLATE_PATTERN.findall(value)

        if not matches:
            return value

        result = value
        for var_name in matches:
            secret = await self._secret_manager.get_secret(var_name)
            if secret.found and secret.value is not None:
                result = result.replace(f"${{{var_name}}}", secret.value)
                logger.debug(
                    "template_resolved",
                    var=var_name,
                    source=secret.source.value,
                )
            else:
                logger.warning(
                    "template_unresolved",
                    var=var_name,
                    message=f"Secret '{var_name}' not found in any source",
                )

        return result

    async def resolve_keys(
        self, config: dict[str, Any], keys: list[str]
    ) -> dict[str, Any]:
        """Resolve only specific keys in config (for security).

        Use this when you only want to resolve certain known keys,
        leaving others as templates.

        Args:
            config: Configuration dictionary.
            keys: List of dot-notation keys to resolve (e.g., ["llm.azure.api_key"]).

        Returns:
            Config with specified keys resolved.
        """
        result = copy.deepcopy(config)

        for key_path in keys:
            parts = key_path.split(".")
            target = result

            # Navigate to parent
            for part in parts[:-1]:
                if isinstance(target, dict) and part in target:
                    target = target[part]
                else:
                    break
            else:
                # Resolve final key
                final_key = parts[-1]
                if isinstance(target, dict) and final_key in target:
                    target[final_key] = await self._resolve_value(target[final_key])

        return result

    def find_templates(self, config: dict[str, Any]) -> list[str]:
        """Find all template variables in a config.

        Useful for debugging or validation.

        Args:
            config: Configuration dictionary.

        Returns:
            List of unique variable names found.
        """
        templates: set[str] = set()
        self._find_templates_recursive(config, templates)
        return sorted(templates)

    def _find_templates_recursive(self, value: Any, templates: set[str]) -> None:
        """Recursively find template variables.

        Args:
            value: Any value to search.
            templates: Set to add found variables to.
        """
        if isinstance(value, str):
            matches = self.TEMPLATE_PATTERN.findall(value)
            templates.update(matches)
        elif isinstance(value, dict):
            for v in value.values():
                self._find_templates_recursive(v, templates)
        elif isinstance(value, list):
            for item in value:
                self._find_templates_recursive(item, templates)
