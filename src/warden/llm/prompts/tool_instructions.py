"""
Tool Instructions for LLM Agentic Loop.

Single source of truth (DRY) for tool definitions and instruction snippets
appended to system prompts across all frames and phases.

The LLM uses text-based tool calling (not native function calling APIs)
to ensure compatibility across all providers (Ollama, OpenAI, Groq).
"""

# Circuit breaker: maximum tool call iterations before forcing final response
MAX_TOOL_ITERATIONS = 3

# LLM-facing tool definitions (used for validation and documentation)
AVAILABLE_TOOLS: list[dict] = [
    {
        "name": "warden_query_symbol",
        "description": ("Query a symbol's callers, callees, or definition in the code graph."),
        "parameters": {
            "name": {
                "type": "string",
                "description": "Symbol name (e.g. 'SecurityFrame')",
            },
            "query_type": {
                "type": "string",
                "enum": ["callers", "callees", "who_uses", "search"],
            },
        },
        "required": ["name"],
    },
    {
        "name": "warden_graph_search",
        "description": "Search the code graph for symbols by partial name.",
        "parameters": {
            "query": {
                "type": "string",
                "description": "Partial symbol name",
            },
            "kind": {
                "type": "string",
                "enum": ["class", "function", "method"],
            },
        },
        "required": ["query"],
    },
]

# Set of known tool names for fast validation
KNOWN_TOOL_NAMES: frozenset[str] = frozenset(t["name"] for t in AVAILABLE_TOOLS)

# Snippet appended to system prompts
TOOL_INSTRUCTION_SNIPPET = """

## Available Tools

You have access to code analysis tools. If you need additional context about a symbol, its callers, or its callees, return a TOOL CALL instead of guessing.

Tools:
- warden_query_symbol(name, query_type): Query symbol callers/callees/definition
- warden_graph_search(query, kind): Search code graph by partial name

### How to Use Tools
If you need more context, return ONLY this JSON (nothing else):
```json
{"tool_use": {"name": "TOOL_NAME", "arguments": {"arg1": "value"}}}
```

### Rules
- Do NOT hallucinate symbol definitions. Use tools to verify.
- You have a maximum of 3 tool calls. After that you MUST return your final analysis.
- If you have enough context, return your normal analysis JSON directly.
"""


def get_tool_enhanced_prompt(base_prompt: str) -> str:
    """Append tool instructions to a base system prompt.

    Args:
        base_prompt: The original system prompt text.

    Returns:
        System prompt with tool instruction snippet appended.
    """
    return base_prompt + TOOL_INSTRUCTION_SNIPPET
