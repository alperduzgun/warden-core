"""
LLM Operations Adapter

MCP adapter for LLM-powered analysis tools.
Maps to gRPC LlmOperationsMixin functionality.
"""

from pathlib import Path
from typing import Any, Dict, List

from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory


class LlmAdapter(BaseWardenAdapter):
    """
    Adapter for LLM operation tools.

    Tools:
        - warden_analyze_with_llm: LLM code analysis
        - warden_classify_code: Code classification
        - warden_test_llm_provider: Test provider
        - warden_get_available_models: List models
        - warden_validate_llm_config: Validate config
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_analyze_with_llm",
        "warden_classify_code",
        "warden_test_llm_provider",
        "warden_get_available_models",
        "warden_validate_llm_config",
    })
    TOOL_CATEGORY = ToolCategory.LLM

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """Get LLM tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_analyze_with_llm",
                description="Analyze code using LLM with custom prompt",
                properties={
                    "code": {
                        "type": "string",
                        "description": "Code to analyze",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Analysis prompt/instruction",
                    },
                    "provider": {
                        "type": "string",
                        "description": "LLM provider (anthropic, openai, etc.)",
                    },
                },
                required=["code", "prompt"],
            ),
            self._create_tool_definition(
                name="warden_classify_code",
                description="Classify code to determine recommended validation frames",
                properties={
                    "code": {
                        "type": "string",
                        "description": "Code to classify",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "File path for context",
                    },
                },
                required=["code"],
            ),
            self._create_tool_definition(
                name="warden_test_llm_provider",
                description="Test LLM provider connectivity and response",
                properties={
                    "provider": {
                        "type": "string",
                        "description": "Provider to test (anthropic, openai, etc.)",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Test prompt",
                        "default": "Hello, respond with 'OK' if you can read this.",
                    },
                },
                required=["provider"],
            ),
            self._create_tool_definition(
                name="warden_get_available_models",
                description="Get available models for an LLM provider",
                properties={
                    "provider": {
                        "type": "string",
                        "description": "Provider name",
                    },
                },
                required=["provider"],
            ),
            self._create_tool_definition(
                name="warden_validate_llm_config",
                description="Validate LLM configuration",
                properties={
                    "provider": {
                        "type": "string",
                        "description": "Provider name",
                    },
                    "config": {
                        "type": "object",
                        "description": "Configuration to validate",
                        "additionalProperties": True,
                    },
                },
                required=["provider"],
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """Execute LLM tool."""
        handlers = {
            "warden_analyze_with_llm": self._analyze_with_llm,
            "warden_classify_code": self._classify_code,
            "warden_test_llm_provider": self._test_llm_provider,
            "warden_get_available_models": self._get_available_models,
            "warden_validate_llm_config": self._validate_llm_config,
        }

        handler = handlers.get(tool_name)
        if handler:
            return await handler(arguments)
        return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _analyze_with_llm(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Analyze code with LLM."""
        code = arguments.get("code")
        prompt = arguments.get("prompt")
        provider = arguments.get("provider")

        if not code:
            return MCPToolResult.error("Missing required parameter: code")
        if not prompt:
            return MCPToolResult.error("Missing required parameter: prompt")

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            # Collect streaming response
            response_text = ""
            async for chunk in self.bridge.analyze_with_llm(code, prompt, provider):
                if isinstance(chunk, dict):
                    response_text += chunk.get("content", "")
                else:
                    response_text += str(chunk)

            return MCPToolResult.json_result({
                "success": True,
                "response": response_text,
                "provider": provider or "default",
            })
        except Exception as e:
            return MCPToolResult.error(f"LLM analysis failed: {e}")

    async def _classify_code(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Classify code for frame recommendation."""
        code = arguments.get("code")
        file_path = arguments.get("file_path", "")

        if not code:
            return MCPToolResult.error("Missing required parameter: code")

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            if hasattr(self.bridge, "classify_code"):
                result = await self.bridge.classify_code(code, file_path)
                return MCPToolResult.json_result(result)
            else:
                # Fallback: basic classification based on content
                return MCPToolResult.json_result(self._basic_classify(code))
        except Exception as e:
            return MCPToolResult.error(f"Classification failed: {e}")

    def _basic_classify(self, code: str) -> Dict[str, Any]:
        """Basic code classification without LLM."""
        code_lower = code.lower()

        return {
            "has_async_operations": "async" in code_lower or "await" in code_lower,
            "has_user_input": "input(" in code_lower or "request." in code_lower,
            "has_database_operations": any(x in code_lower for x in ["sql", "query", "cursor", "execute"]),
            "has_network_calls": any(x in code_lower for x in ["http", "requests.", "fetch", "socket"]),
            "has_file_operations": any(x in code_lower for x in ["open(", "read(", "write(", "path"]),
            "has_authentication": any(x in code_lower for x in ["password", "token", "auth", "login"]),
            "has_cryptography": any(x in code_lower for x in ["encrypt", "decrypt", "hash", "crypto"]),
            "detected_frameworks": [],
            "recommended_frames": ["security", "resilience"],
            "confidence": 0.5,
            "method": "basic_heuristic",
        }

    async def _test_llm_provider(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Test LLM provider connectivity."""
        provider = arguments.get("provider")
        prompt = arguments.get("prompt", "Hello, respond with 'OK' if you can read this.")

        if not provider:
            return MCPToolResult.error("Missing required parameter: provider")

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            if hasattr(self.bridge, "test_provider"):
                result = await self.bridge.test_provider(provider, prompt)
                return MCPToolResult.json_result(result)
            else:
                return MCPToolResult.error("Provider testing not available")
        except Exception as e:
            return MCPToolResult.json_result({
                "success": False,
                "provider": provider,
                "error_message": str(e),
            })

    async def _get_available_models(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get available models for provider."""
        provider = arguments.get("provider")

        if not provider:
            return MCPToolResult.error("Missing required parameter: provider")

        if not self.bridge:
            return MCPToolResult.error("Warden bridge not available")

        try:
            if hasattr(self.bridge, "get_available_models"):
                result = await self.bridge.get_available_models(provider)
                return MCPToolResult.json_result(result)
            else:
                # Return hardcoded models based on provider
                models = self._get_default_models(provider)
                return MCPToolResult.json_result({"models": models})
        except Exception as e:
            return MCPToolResult.error(f"Failed to get models: {e}")

    def _get_default_models(self, provider: str) -> List[Dict[str, Any]]:
        """Get default models for provider."""
        provider_models = {
            "anthropic": [
                {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "max_tokens": 200000},
                {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus", "max_tokens": 200000},
            ],
            "openai": [
                {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "max_tokens": 128000},
                {"id": "gpt-4o", "name": "GPT-4o", "max_tokens": 128000},
            ],
        }
        return provider_models.get(provider.lower(), [])

    async def _validate_llm_config(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Validate LLM configuration."""
        provider = arguments.get("provider")
        config = arguments.get("config", {})

        if not provider:
            return MCPToolResult.error("Missing required parameter: provider")

        errors = []
        warnings = []

        # Basic validation
        valid_providers = ["anthropic", "openai", "ollama", "azure"]
        if provider.lower() not in valid_providers:
            warnings.append(f"Unknown provider: {provider}")

        # Check for API key
        if not config.get("api_key") and provider.lower() in ["anthropic", "openai"]:
            errors.append(f"API key required for {provider}")

        return MCPToolResult.json_result({
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        })
