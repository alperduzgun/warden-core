"""
Configuration Adapter

MCP adapter for configuration management tools.
Maps to gRPC ConfigurationMixin functionality.
"""

from __future__ import annotations

import contextlib
from typing import Any

import yaml

from warden.llm.config import DEFAULT_MODELS
from warden.llm.types import LlmProvider
from warden.mcp.domain.enums import ToolCategory
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter


def _default_model_for(provider_id: str) -> str:
    """Look up the default smart model for a provider from the shared DEFAULT_MODELS dict."""
    with contextlib.suppress(ValueError):
        return DEFAULT_MODELS.get(LlmProvider(provider_id), "") or ""
    return ""


class ConfigAdapter(BaseWardenAdapter):
    """
    Adapter for configuration tools.

    Tools:
        - warden_get_available_frames: List validation frames
        - warden_get_available_providers: List LLM providers
        - warden_get_configuration: Get full configuration
        - warden_update_configuration: Update settings
        - warden_update_frame_status: Enable/disable frame
        - warden_configure: Configure Warden settings
        - warden_configure_ci: Configure CI/CD workflow
    """

    SUPPORTED_TOOLS = frozenset(
        {
            "warden_get_available_frames",
            "warden_get_available_providers",
            "warden_get_configuration",
            "warden_update_configuration",
            "warden_update_frame_status",
            "warden_configure",
            "warden_configure_ci",
        }
    )
    TOOL_CATEGORY = ToolCategory.CONFIG

    def get_tool_definitions(self) -> list[MCPToolDefinition]:
        """Get configuration tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_get_available_frames",
                description="List all available validation frames with their status",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_get_available_providers",
                description="List all available LLM providers and their status",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_get_configuration",
                description="Get full Warden configuration including frames, providers, and settings",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_update_configuration",
                description="Update Warden configuration settings",
                properties={
                    "settings": {
                        "type": "object",
                        "description": "Configuration settings to update",
                        "additionalProperties": True,
                    },
                },
                required=["settings"],
            ),
            self._create_tool_definition(
                name="warden_update_frame_status",
                description="Enable or disable a validation frame",
                properties={
                    "frame_id": {
                        "type": "string",
                        "description": "Frame identifier (e.g., 'security', 'chaos')",
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "Whether to enable (true) or disable (false) the frame",
                    },
                },
                required=["frame_id", "enabled"],
            ),
            self._create_tool_definition(
                name="warden_configure",
                description="Configure Warden settings (Provider, API Key, Model) idempotently. Safe for Agents.",
                properties={
                    "provider": {
                        "type": "string",
                        "description": "LLM Provider (ollama, openai, anthropic, gemini, azure_openai, deepseek, groq, openrouter)",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API Key for the provider (required for cloud providers)",
                    },
                    "model": {
                        "type": "string",
                        "description": "Smart model name (e.g., claude-3-5-sonnet-latest, gemini-1.5-pro)",
                    },
                    "vector_db": {
                        "type": "string",
                        "description": "Vector Database provider (local, qdrant, pinecone)",
                        "default": "local",
                    },
                },
                required=["provider"],
            ),
            self._create_tool_definition(
                name="warden_configure_ci",
                description=(
                    "Configure CI/CD workflow for Warden. "
                    "Generates or updates GitHub Actions / GitLab CI files. "
                    "Call this when the user wants to set up CI for their project via AI."
                ),
                properties={
                    "ci_provider": {
                        "type": "string",
                        "description": "CI platform: 'github' (GitHub Actions) or 'gitlab' (GitLab CI).",
                        "enum": ["github", "gitlab"],
                    },
                    "llm_provider": {
                        "type": "string",
                        "description": (
                            "Smart tier LLM provider for CI scans. "
                            "Options: groq, openai, anthropic, azure_openai, deepseek, gemini, ollama. "
                            "Note: claude_code is NOT supported in CI."
                        ),
                        "enum": ["groq", "openai", "anthropic", "azure_openai", "deepseek", "gemini", "ollama"],
                    },
                    "fast_model": {
                        "type": "string",
                        "description": "Fast tier model (default: qwen2.5-coder:3b via Ollama).",
                    },
                    "branch": {
                        "type": "string",
                        "description": "Default branch name (default: main).",
                        "default": "main",
                    },
                },
                required=["ci_provider", "llm_provider"],
            ),
        ]

    async def _execute_tool_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        """Execute configuration tool."""
        if tool_name == "warden_get_available_frames":
            return await self._get_available_frames_async()
        elif tool_name == "warden_get_available_providers":
            return await self._get_available_providers_async()
        elif tool_name == "warden_get_configuration":
            return await self._get_configuration_async()
        elif tool_name == "warden_update_configuration":
            return await self._update_configuration_async(arguments)
        elif tool_name == "warden_update_frame_status":
            return await self._update_frame_status_async(arguments)
        elif tool_name == "warden_configure":
            return await self._configure_warden_async(arguments)
        elif tool_name == "warden_configure_ci":
            return await self._configure_ci_async(arguments)
        else:
            return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _get_available_frames_async(self) -> MCPToolResult:
        """Get available validation frames."""
        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            frames = await self.bridge.get_available_frames_async()
            return MCPToolResult.json_result(
                {
                    "frames": frames,
                    "total_count": len(frames),
                }
            )
        except Exception as e:
            return MCPToolResult.error(f"Failed to get frames: {e}")

    async def _get_available_providers_async(self) -> MCPToolResult:
        """Get available LLM providers."""
        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            providers = await self.bridge.get_available_providers_async()
            return MCPToolResult.json_result(
                {
                    "providers": providers,
                    "total_count": len(providers),
                }
            )
        except Exception as e:
            return MCPToolResult.error(f"Failed to get providers: {e}")

    async def _get_configuration_async(self) -> MCPToolResult:
        """Get full Warden configuration."""
        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            config = await self.bridge.get_config_async()
            return MCPToolResult.json_result(config)
        except Exception as e:
            return MCPToolResult.error(f"Failed to get configuration: {e}")

    async def _update_configuration_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """Update configuration settings."""
        settings = arguments.get("settings", {})

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            # Check if bridge has update method
            if hasattr(self.bridge, "update_config"):
                result = await self.bridge.update_config(settings)
                return MCPToolResult.json_result(result)
            else:
                return MCPToolResult.error("Configuration update not supported")
        except Exception as e:
            return MCPToolResult.error(f"Failed to update configuration: {e}")

    async def _update_frame_status_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """Update frame enabled status."""
        frame_id = arguments.get("frame_id")
        enabled = arguments.get("enabled")

        if not frame_id:
            return MCPToolResult.error("Missing required parameter: frame_id")
        if enabled is None:
            return MCPToolResult.error("Missing required parameter: enabled")

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            result = await self.bridge.update_frame_status_async(frame_id, enabled)
            return MCPToolResult.json_result(result)
        except Exception as e:
            return MCPToolResult.error(f"Failed to update frame status: {e}")

    async def _configure_warden_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """
        Configure Warden settings safely (Atomic & Idempotent).

        Args:
            arguments: Tool arguments

        Returns:
            MCPToolResult: Success or failure
        """
        provider = arguments.get("provider", "").lower()
        api_key = arguments.get("api_key")
        model = arguments.get("model")
        vector_db = arguments.get("vector_db", "local")

        valid_providers = {"ollama", "openai", "anthropic", "gemini", "azure_openai", "deepseek", "groq", "openrouter"}

        if provider not in valid_providers:
            return MCPToolResult.error(f"Invalid provider: {provider}. Must be one of: {', '.join(valid_providers)}")

        # 1. Update .env (Atomic-ish)
        # We read lines, update/append, and write back.
        # Ideally this should use a proper parser but for minimal deps this is standard.
        env_updates = {}
        if api_key:
            key_map = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "azure_openai": "AZURE_OPENAI_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
                "groq": "GROQ_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
            }
            if provider in key_map:
                env_updates[key_map[provider]] = api_key

        if env_updates:
            try:
                env_path = self.project_root / ".env"
                current_lines = []
                if env_path.exists():
                    with open(env_path) as f:
                        current_lines = f.readlines()

                new_lines = []
                processed_keys = set()

                for line in current_lines:
                    # simplistic parsing
                    parts = line.split("=")
                    if len(parts) > 0:
                        key = parts[0].strip()
                        if key in env_updates:
                            new_lines.append(f"{key}={env_updates[key]}\n")
                            processed_keys.add(key)
                            continue
                    new_lines.append(line)

                for key, val in env_updates.items():
                    if key not in processed_keys:
                        if new_lines and not new_lines[-1].endswith("\n"):
                            new_lines.append("\n")
                        new_lines.append(f"{key}={val}\n")

                with open(env_path, "w") as f:
                    f.writelines(new_lines)

            except Exception as e:
                return MCPToolResult.error(f"Failed to update .env: {e}")

        # 2. Update config.yaml (Atomic-ish)
        # We use the bridge to reload/update if possible, but also ensure file on disk is correct.
        warden_dir = self.project_root / ".warden"
        if not warden_dir.exists():
            try:
                warden_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return MCPToolResult.error(f"Failed to create .warden directory: {e}")

        config_path = warden_dir / "config.yaml"

        config_data = {}
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config_data = yaml.safe_load(f) or {}
            except Exception:
                config_data = {}  # Fail safe, overwrite if corrupt

        # Ensure section exists
        if "llm" not in config_data:
            config_data["llm"] = {}

        config_data["llm"]["provider"] = provider
        if model:
            config_data["llm"]["smart_model"] = model
            # For simplicity, set fast model to same if not defined, or smart defaults
            if "fast_model" not in config_data["llm"]:
                config_data["llm"]["fast_model"] = model  # simplified

        config_data["vector_db"] = {"provider": vector_db}

        try:
            with open(config_path, "w") as f:
                yaml.safe_dump(config_data, f)
        except Exception as e:
            return MCPToolResult.error(f"Failed to write config.yaml: {e}")

        # 3. Update Artifacts (CLAUDE.md, etc.) to Usage Mode
        try:
            from warden.cli.commands.init_helpers import generate_ai_tool_files

            # Simplified mock config for generation
            gen_config = {"provider": provider, "model": model, "vector_db": vector_db}
            generate_ai_tool_files(self.project_root, gen_config)
        except Exception as e:
            # Non-critical failure, but log it for observability
            # Assuming logger is available via self.logger or get_logger
            from warden.shared.infrastructure.logging import get_logger

            logger = get_logger(__name__)
            logger.warning("artifact_generation_failed_in_adapter", error=str(e))

        return MCPToolResult.json_result(
            {
                "status": "configured",
                "provider": provider,
                "config_path": str(config_path),
                "updated_env": list(env_updates.keys()),
            }
        )

    async def _configure_ci_async(self, arguments: dict[str, Any]) -> MCPToolResult:
        """
        Configure CI/CD workflow files (GitHub Actions / GitLab CI).

        Uses shared DEFAULT_MODELS to resolve smart model defaults — no duplicate dict.
        """
        ci_provider_id = arguments.get("ci_provider", "")
        llm_provider_id = arguments.get("llm_provider", "")
        fast_model = arguments.get("fast_model", "qwen2.5-coder:3b")
        branch = arguments.get("branch", "main")

        if not ci_provider_id or not llm_provider_id:
            return MCPToolResult.error("Missing required parameters: ci_provider and llm_provider")

        # Build llm_config using shared DEFAULT_MODELS — no duplicate dict needed
        llm_config = {
            "provider": llm_provider_id,
            "model": _default_model_for(llm_provider_id),
            "fast_model": fast_model,
        }

        try:
            from warden.cli.commands.init_helpers import CI_PROVIDERS, configure_ci_workflow

            ci_provider = next(
                (v for v in CI_PROVIDERS.values() if v["id"] == ci_provider_id),
                None,
            )
            if not ci_provider:
                return MCPToolResult.error(f"Unknown CI provider: {ci_provider_id}")

            project_root = self.project_root
            success = configure_ci_workflow(ci_provider, llm_config, project_root, branch)

            if success:
                return MCPToolResult.json_result(
                    {
                        "status": "configured",
                        "ci_provider": ci_provider_id,
                        "llm_provider": llm_provider_id,
                        "fast_model": fast_model,
                        "branch": branch,
                        "message": (
                            f"CI workflow configured for {ci_provider_id}. Commit the generated workflow files."
                        ),
                    }
                )
            return MCPToolResult.error("Failed to write CI workflow files.")
        except Exception as e:
            return MCPToolResult.error(f"CI configuration failed: {e}")
