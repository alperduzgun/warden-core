"""
Setup Resource Adapter.

Provides the 'warden://setup/guide' resource to teach Agents
how to conduct an interactive setup interview.
"""

from typing import List, Optional
from pathlib import Path

from warden.mcp.domain.models import MCPResourceDefinition, MCPToolDefinition, MCPToolResult
from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.enums import ToolCategory, ResourceType


class SetupResourceAdapter(BaseWardenAdapter):
    """
    Adapter that serves static guidance resources for Agents.
    """

    SUPPORTED_TOOLS = frozenset()
    TOOL_CATEGORY = ToolCategory.CONFIG 

    SETUP_PROTOCOL = """
# Warden Setup Protocol for Agents

## Objective
Your goal is to help a potentially non-technical user configure Warden. 
You must act as a **Setup Expert**. Do not just execute commands; **guide** the user.

## The Interview Process

### Phase 1: Assess Needs
1. Ask: "Do you prefer a **Cloud-based** (easier, more powerful) or **Local** (private, free) setup?"
2. Ask: "Which AI model do you usually use? (Claude, GPT-4, Gemini)"

### Phase 2: Gather Secrets (If Cloud)
If they chose Cloud:
- Ask for the API Key for their chosen provider.
- Remind them: "Your key is stored locally in `.env` and never shared."

### Phase 3: Verify Environment (If Local)
If they chose Local:
- specific tool checking is not needed, just assume they might need Ollama.
- Ask: "Do you have **Ollama** installed and running?"

### Phase 4: Execution
Once you have the info (Provider, Key, Model), call the `warden_configure` tool.
DO NOT ask the user to run terminal commands. YOU run the tool.

## Example Configuration Call
```json
{
  "provider": "gemini",
  "api_key": "AIza...",
  "model": "gemini-1.5-pro"
}
```

## After Setup
Once `warden_configure` returns success:
1. Tell the user: "Warden is now configured with [Provider]!"
2. Suggest they run their first scan.
"""

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        # This adapter only provides Resources, no tools.
        return []

    async def _execute_tool_async(self, tool_name: str, arguments: dict) -> MCPToolResult:
        # Should not be called
        return MCPToolResult.error("No tools protected by this adapter")

    # --- Resource Provider Implementation ---
    
    def list_resources(self) -> List[MCPResourceDefinition]:
        """List available setup resources."""
        return [
            MCPResourceDefinition(
                uri="warden://setup/guide",
                name="Warden Setup Protocol",
                description="Instructions for Agents on how to guide users through setup.",
                resource_type=ResourceType.CONFIG,
                mime_type="text/markdown",
                file_path="(internal memory)"
            )
        ]

    def read_resource(self, uri: str) -> Optional[str]:
        """Read the setup protocol."""
        if uri == "warden://setup/guide":
            return self.SETUP_PROTOCOL
        return None
