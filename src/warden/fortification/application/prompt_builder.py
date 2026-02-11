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
        issues: list[dict[str, Any]],
        context: dict[str, Any],
        semantic_context: list[Any] | None = None,
    ) -> str:
        """Create optimized LLM prompt for fix generation."""
        # Get context information
        framework = context.get("framework", "unknown")
        language = context.get("language", "python")

        # Format issues (Compact)
        issue_details = []
        for issue in issues[:5]:  # Limit to 5
            snippet = (issue.get('code_snippet') or 'N/A')[:80] # Reduced to 80
            issue_details.append(
                f"- {issue.get('file_path', '?')}:{issue.get('line_number', '?')}\n"
                f"  `{snippet}`"
            )

        # Format semantic context (Strict limit)
        semantic_section = ""
        if semantic_context:
            examples = []
            max_chars = 1500  # Reduced validation context
            total_chars = 0

            for i, result in enumerate(semantic_context[:3]):
                file_path = "unknown"
                content = ""

                # ... extractor logic same as before ...
                if hasattr(result, 'chunk'):
                     chunk = result.chunk
                     file_path = getattr(chunk, 'file_path', 'unknown')
                     content = getattr(chunk, 'content', str(chunk))
                elif hasattr(result, 'file_path'):
                    file_path = result.file_path
                    content = getattr(result, 'content', str(result))
                elif isinstance(result, dict):
                    file_path = result.get('file_path', 'unknown')
                    content = result.get('content', str(result))

                content = (content or "")[:300] # Reduced from 500

                example = f"# Ex{i+1} ({file_path})\n{content}\n"
                if total_chars + len(example) > max_chars: break
                examples.append(example)
                total_chars += len(example)

            if examples:
                semantic_section = f"REFERENCE PATTERNS:\n{''.join(examples)}\n"

        prompt = f"""
ACT: Security Expert. FRAMEWORK: {framework}. LANG: {language}.
TASK: Fix {issue_type} vulnerabilities.

{semantic_section}
ISSUES:
{"".join(issue_details)}

OUTPUT JSON: [{{ "title": "...", "detail": "...", "code": "...", "auto_fixable": bool }}]
Fix must match project style.
"""
        return prompt

    @staticmethod
    def _sanitize_json_string(json_str: str) -> str:
        """
        Sanitize JSON string to fix common LLM formatting errors.
        Specifically fixes invalid escape sequences (e.g. Windows paths).
        """
        # Fix backslashes that are not valid escape sequences
        # Look for \ that is NOT followed by " \ / b f n r t u
        # and NOT preceded by \
        pattern = r'(?<!\\)\\(?!["\\/bfnrtu])'
        return re.sub(pattern, r'\\\\', json_str)

    @staticmethod
    def parse_llm_response(
        response: str,
        issues: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Parse LLM response into fortification objects."""
        fortifications = []

        try:
            # Safe JSON extraction without greedy regex
            if not response:
                raise ValueError("Empty response from LLM")

            start_idx = response.find('[')
            end_idx = response.rfind(']')

            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = response[start_idx : end_idx + 1]

                try:
                    fixes_data = json.loads(json_str)
                except json.JSONDecodeError:
                    # Retry with sanitization
                    sanitized_str = FortificationPromptBuilder._sanitize_json_string(json_str)
                    fixes_data = json.loads(sanitized_str)

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
            else:
                 raise ValueError("No JSON list structure found in response")

        except (json.JSONDecodeError, ValueError, AttributeError) as e:
            # Only log error if it's not simply "No JSON found" or empty usage which might be expected in some contexts
            # But here failure to parse means we fallback to raw text description
            logger.warning("llm_response_parsing_failed", error=str(e), original_response=response[:100] if response else "Empty")

            # Create basic fortification from response as fallback
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
