"""
Fortification Prompt Builder.

Handles creation and parsing of LLM prompts for the fortification phase.
"""

import json
import re
from typing import Any, Dict, List, Optional
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

class FortificationPromptBuilder:
    """Builder for fortification LLM prompts and response parser."""

    # Search query mapping for semantic context retrieval
    ISSUE_SEARCH_QUERIES = {
        "sql_injection": ["parameterized query", "prepared statement", "ORM query filter"],
        "xss": ["escape HTML", "sanitize output", "template autoescape"],
        "hardcoded_secret": ["environment variable", "config secret", "vault integration"],
        "path_traversal": ["safe path join", "basename validation", "secure file path"],
        "command_injection": ["subprocess safe", "shlex quote", "shell escape"],
        "ssrf": ["URL validation", "allowlist domain", "request validation"],
        "weak_crypto": ["strong encryption AES", "cryptography library", "secure hash"],
        "insecure_deserialization": ["safe deserialization", "JSON loads validation"],
        "xxe": ["XML parser secure", "defuse XML", "disable external entities"],
        "secrets": ["environment variable", "dotenv", "secrets manager"],
    }

    @staticmethod
    def create_llm_prompt(
        issue_type: str,
        issues: List[Dict[str, Any]],
        context: Dict[str, Any],
        semantic_context: Optional[List[Any]] = None,
    ) -> str:
        """Create LLM prompt for fix generation."""
        # Get context information
        project_type = context.get("project_type", "unknown")
        framework = context.get("framework", "unknown")
        language = context.get("language", "python")

        # Format issues for prompt
        issue_details = []
        for issue in issues[:5]:  # Limit to 5 examples
            issue_details.append(
                f"- File: {issue.get('file_path', 'unknown')}\n"
                f"  Line: {issue.get('line_number', 'unknown')}\n"
                f"  Code: {(issue.get('code_snippet') or 'N/A')[:100]}"
            )

        # Format semantic context if available
        semantic_section = ""
        if semantic_context:
            examples = []
            total_chars = 0
            max_chars = 2000  # Max context characters
            
            for i, result in enumerate(semantic_context[:3]):  # Max 3 examples
                file_path = "unknown"
                content = ""
                line = "N/A"
                
                if hasattr(result, 'chunk'):  # SearchResult object with chunk
                     chunk = result.chunk
                     file_path = getattr(chunk, 'file_path', 'unknown')
                     content = getattr(chunk, 'content', str(chunk))
                     line = getattr(chunk, 'start_line', 'N/A')
                elif hasattr(result, 'file_path'): # Direct object
                    file_path = result.file_path
                    content = getattr(result, 'content', str(result))
                    line = getattr(result, 'line_number', 'N/A')
                elif isinstance(result, dict):
                    file_path = result.get('file_path', 'unknown')
                    content = result.get('content', str(result))
                    line = result.get('line_number', 'N/A')
                
                content = (content or "")[:500]
                
                example = f"### Example {i+1}: {file_path}:{line}\n```{language}\n{content}\n```\n"
                
                if total_chars + len(example) > max_chars:
                    break
                    
                examples.append(example)
                total_chars += len(example)
            
            if examples:
                semantic_section = f"""
## SIMILAR SECURE PATTERNS FROM THIS PROJECT

The following code snippets show how similar security issues 
have been handled elsewhere in this codebase. 
Use these as reference for style and approach:

{"".join(examples)}

IMPORTANT: Generate fixes that follow the patterns shown above.
Match the coding style, library usage, and conventions of this project.
"""

        prompt = f"""
You are a security expert fixing {issue_type} vulnerabilities.

PROJECT CONTEXT:
- Type: {project_type}
- Framework: {framework}
- Language: {language}
{semantic_section}
ISSUES FOUND ({len(issues)} total):
{"".join(issue_details)}

Generate secure fixes for these {issue_type} vulnerabilities.
For each fix, provide:
1. Title: Clear description of the fix
2. Detail: Explanation of what the fix does
3. Code: The actual fix code
4. Auto-fixable: Whether this can be automatically applied (true/false)

Format your response as JSON array of fixes.
Focus on framework-specific best practices for {framework}.
"""
        return prompt

    @staticmethod
    def parse_llm_response(
        response: str,
        issues: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Parse LLM response into fortification objects."""
        fortifications = []

        try:
            # Try to extract JSON from response
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                fixes_data = json.loads(json_match.group())

                for fix_data in fixes_data:
                    fortification = {
                        "title": fix_data.get("title", "Security Fix"),
                        "detail": fix_data.get("detail", ""),
                        "code": fix_data.get("code", ""),
                        "auto_fixable": fix_data.get("auto_fixable", False),
                        "severity": issues[0].get("severity", "high") if issues else "medium",
                        "issue_type": issues[0].get("type", "security") if issues else "unknown",
                        "confidence": 0.85,
                    }
                    fortifications.append(fortification)

        except (json.JSONDecodeError, AttributeError) as e:
            logger.error("llm_response_parsing_failed", error=str(e))

            # Create basic fortification from response
            fortification = {
                "title": f"Fix for {issues[0].get('type', 'issue')}" if issues else "Security Fix",
                "detail": (response or "")[:500],  # First 500 chars as detail
                "code": "",
                "auto_fixable": False,
                "severity": issues[0].get("severity", "medium") if issues else "medium",
                "confidence": 0.5,
            }
            fortifications.append(fortification)

        return fortifications
