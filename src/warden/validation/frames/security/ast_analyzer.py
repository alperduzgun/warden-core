"""
AST Analyzer Module

Tree-sitter AST analysis for structural vulnerability detection.
"""

import asyncio
from typing import Any

try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


async def extract_ast_context(code_file: Any) -> dict[str, Any]:
    """
    Extract AST context using Tree-sitter for structural analysis.

    Detects:
    - Function calls with string concatenation (potential injection)
    - Dangerous function usage (eval, exec, subprocess)
    - Unvalidated input flows

    Returns:
        Dict with AST-extracted security context
    """
    ast_context: dict[str, Any] = {
        "dangerous_calls": [],
        "string_concatenations": [],
        "input_sources": [],
        "sql_queries": [],
    }

    try:
        from warden.ast.application.provider_registry import ASTProviderRegistry
        from warden.ast.domain.enums import CodeLanguage

        # Get language enum
        try:
            lang = CodeLanguage(code_file.language.lower())
        except ValueError:
            logger.debug("ast_unsupported_language", language=code_file.language)
            return ast_context

        # Cache-first: use pre-parsed result if available
        cached = code_file.metadata.get("_cached_parse_result") if code_file.metadata else None
        if cached and cached.ast_root:
            result = cached
        else:
            # Fallback: on-demand parse
            registry = ASTProviderRegistry()
            provider = registry.get_provider(lang)

            if not provider:
                logger.debug("ast_no_provider", language=lang)
                return ast_context

            if hasattr(provider, "ensure_grammar"):
                await provider.ensure_grammar(lang)

            result = await asyncio.wait_for(provider.parse(code_file.content, lang), timeout=5.0)

        if not result.ast_root:
            return ast_context

        # Walk AST and extract security-relevant nodes
        _walk_ast_for_security(result.ast_root, ast_context, code_file.content)

        logger.debug(
            "ast_security_context_extracted",
            dangerous_calls=len(ast_context["dangerous_calls"]),
            sql_queries=len(ast_context["sql_queries"]),
            input_sources=len(ast_context["input_sources"]),
        )

    except asyncio.TimeoutError:
        logger.debug("ast_extraction_timeout", file=code_file.path)
    except Exception as e:
        logger.debug("ast_extraction_failed", error=str(e))

    return ast_context


def _walk_ast_for_security(node: Any, context: dict[str, Any], source: str) -> None:
    """Walk AST and extract security-relevant patterns."""
    if node is None:
        return

    node_type = getattr(node, "type", "") or ""

    # Detect dangerous function calls
    # call_expression: JS/Go, call: Python, method_invocation: Java
    if node_type in ("call_expression", "call", "method_invocation", "selector_expression"):
        call_name = _get_call_name(node)
        if call_name:
            # Check for dangerous functions (multi-language)
            dangerous_funcs = {
                "eval", "exec", "compile", "subprocess", "shell", "system", "popen",
                "spawn", "execfile",
                # Go
                "Command", "CommandContext", "StartProcess",
                # Java
                "Runtime.exec", "ProcessBuilder",
            }
            if any(d in call_name for d in dangerous_funcs) or any(d in call_name.lower() for d in {"eval", "exec", "system", "popen", "spawn"}):
                line = getattr(node, "start_point", (0,))[0] if hasattr(node, "start_point") else 0
                context["dangerous_calls"].append({"function": call_name, "line": line, "risk": "high"})

            # Check for SQL-related calls (multi-language)
            sql_funcs = {
                "execute", "executemany", "raw", "query", "cursor",
                # Go
                "Exec", "Query", "QueryRow",
                # Java
                "executeQuery", "executeUpdate", "createNativeQuery",
            }
            if any(s in call_name for s in sql_funcs) or any(s in call_name.lower() for s in {"execute", "query", "raw"}):
                line = getattr(node, "start_point", (0,))[0] if hasattr(node, "start_point") else 0
                context["sql_queries"].append({"function": call_name, "line": line})

    # Detect string concatenation in potentially dangerous contexts
    if node_type in ("binary_expression", "binary_operator") and hasattr(node, "text"):
        text = node.text.decode() if isinstance(node.text, bytes) else str(node.text)
        if "+" in text and ('"' in text or "'" in text):
            line = getattr(node, "start_point", (0,))[0] if hasattr(node, "start_point") else 0
            context["string_concatenations"].append({"line": line, "snippet": text[:100]})

    # Detect input sources (multi-language)
    if node_type in ("call_expression", "call", "attribute", "method_invocation", "selector_expression"):
        call_name = _get_call_name(node) or ""
        input_patterns = {
            "request", "input", "argv", "stdin", "getenv", "form", "params",
            # Go
            "FormValue", "PostFormValue", "URL.Query", "r.Body", "r.Header",
            # Java
            "getParameter", "getHeader", "getCookies", "getInputStream", "getReader",
            "getQueryString",
        }
        if any(p in call_name for p in input_patterns) or any(p in call_name.lower() for p in {"request", "input", "argv", "stdin", "getenv", "form", "params"}):
            line = getattr(node, "start_point", (0,))[0] if hasattr(node, "start_point") else 0
            context["input_sources"].append({"source": call_name, "line": line})

    # Recurse into children
    children = getattr(node, "children", []) or []
    for child in children:
        _walk_ast_for_security(child, context, source)


def _get_call_name(node: Any) -> str | None:
    """Extract function/method name from call node."""
    for attr in ("function", "callee", "name", "method"):
        child = getattr(node, attr, None)
        if child:
            if hasattr(child, "text"):
                return child.text.decode() if isinstance(child.text, bytes) else str(child.text)
            if hasattr(child, "name"):
                return str(child.name)
    return None


def format_ast_context(ast_context: dict[str, Any]) -> str:
    """Format AST context for LLM prompt."""
    lines = []

    if ast_context.get("dangerous_calls"):
        lines.append("[Dangerous Function Calls (AST)]:")
        for call in ast_context["dangerous_calls"][:5]:
            lines.append(f"  - {call['function']} at line {call['line']} (risk: {call['risk']})")

    if ast_context.get("sql_queries"):
        lines.append("\n[SQL Query Locations (AST)]:")
        for q in ast_context["sql_queries"][:5]:
            lines.append(f"  - {q['function']} at line {q['line']}")

    if ast_context.get("input_sources"):
        lines.append("\n[Input Sources (AST)]:")
        for src in ast_context["input_sources"][:5]:
            lines.append(f"  - {src['source']} at line {src['line']}")

    return "\n".join(lines) if lines else ""
