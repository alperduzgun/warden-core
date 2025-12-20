"""
LLM Prompt Builder - Enriched prompts with AST metrics.

Follows C# pattern: Build rich prompts with AST metrics for better analysis.
"""
from typing import Dict, Any


def build_enriched_prompt(
    file_path: str,
    file_content: str,
    language: str,
    ast_metrics: Dict[str, Any] = None,
) -> str:
    """
    Build enriched prompt with AST metrics (C# pattern).

    Prompt structure:
    1. File header (path, language)
    2. AST Metrics (if available)
    3. Source code
    4. Analysis instructions

    Args:
        file_path: File path
        file_content: Source code
        language: Programming language
        ast_metrics: Optional AST metrics

    Returns:
        Enriched prompt string
    """
    prompt_parts = []

    # 1. File Header
    prompt_parts.append(f"File: {file_path}")
    prompt_parts.append(f"Language: {language}")
    prompt_parts.append("")

    # 2. AST Metrics (enrichment - C# pattern)
    if ast_metrics:
        prompt_parts.append("## AST Metrics (Exact Analysis):")
        prompt_parts.append(f"- Lines of Code: {ast_metrics.get('lines', 0)}")
        prompt_parts.append(f"- Non-Blank Lines: {ast_metrics.get('nonBlankLines', 0)}")
        prompt_parts.append(f"- Comment Lines: {ast_metrics.get('commentLines', 0)}")

        if "functions" in ast_metrics:
            prompt_parts.append(f"- Functions: {ast_metrics.get('functions', 0)}")
        if "classes" in ast_metrics:
            prompt_parts.append(f"- Classes: {ast_metrics.get('classes', 0)}")
        if "imports" in ast_metrics:
            prompt_parts.append(f"- Imports: {ast_metrics.get('imports', 0)}")
        if "asyncFunctions" in ast_metrics:
            prompt_parts.append(f"- Async Functions: {ast_metrics.get('asyncFunctions', 0)}")
        if "conditionals" in ast_metrics:
            prompt_parts.append(f"- Conditionals: {ast_metrics.get('conditionals', 0)}")
        if "loops" in ast_metrics:
            prompt_parts.append(f"- Loops: {ast_metrics.get('loops', 0)}")
        if "errorHandling" in ast_metrics:
            prompt_parts.append(f"- Error Handling (try/except): {ast_metrics.get('errorHandling', 0)}")

        prompt_parts.append("")

    # 3. Source Code
    prompt_parts.append("## Source Code:")
    prompt_parts.append(f"```{language}")
    prompt_parts.append(file_content)
    prompt_parts.append("```")
    prompt_parts.append("")

    # 4. Analysis Instructions
    prompt_parts.append("Please analyze the code considering the AST metrics above.")
    prompt_parts.append("Focus on semantic patterns, architectural issues, and best practices.")
    prompt_parts.append("If AST metrics are provided, use them to validate your analysis.")

    return "\n".join(prompt_parts)
