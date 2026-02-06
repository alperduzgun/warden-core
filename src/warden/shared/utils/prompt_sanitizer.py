"""
Prompt Sanitizer - Prevents indirect prompt injection attacks.

Encapsulates user-provided code and input in XML tags to prevent
malicious users from hijacking LLM behavior through carefully crafted code.
"""

import re
from typing import Optional


class PromptSanitizer:
    """Sanitizes user input and code for safe LLM injection."""

    @staticmethod
    def sanitize_code_content(code: str, filename: str = "source.py") -> str:
        """
        Wrap user code in XML tags with explicit boundaries.

        Args:
            code: User-provided code to sanitize
            filename: Optional filename for context

        Returns:
            XML-wrapped and escaped code content
        """
        # Escape XML special characters in user code
        escaped_code = PromptSanitizer._escape_xml(code)

        return f"""<source_code filename="{filename}">
{escaped_code}
</source_code>"""

    @staticmethod
    def create_safe_prompt(
        system_instruction: str,
        user_query: str,
        code_context: Optional[str] = None,
        language: str = "unknown"
    ) -> dict:
        """
        Create a safe prompt structure with explicit role separation.

        Args:
            system_instruction: System prompt (trusted)
            user_query: User question (untrusted)
            code_context: Optional code for analysis (untrusted)
            language: Programming language of code

        Returns:
            Dict with safe prompt structure
        """
        # Sanitize untrusted inputs
        safe_query = PromptSanitizer._escape_xml(user_query)
        safe_code = PromptSanitizer._escape_xml(code_context) if code_context else ""

        prompt_parts = [
            f"<system_instruction>\n{system_instruction}\n</system_instruction>",
            f"\n<user_query>\n{safe_query}\n</user_query>"
        ]

        if code_context:
            prompt_parts.append(
                f"\n<source_code language=\"{language}\">\n{safe_code}\n</source_code>"
            )

        return {
            "system_prompt": prompt_parts[0],
            "user_message": "".join(prompt_parts[1:]),
            "safe_formatted": True,
            "injection_protected": True
        }

    @staticmethod
    def escape_prompt_injection(text: str) -> str:
        """
        Escape text to prevent prompt injection via string interpolation.

        Args:
            text: Text that will be embedded in a prompt

        Returns:
            Escaped text
        """
        # Escape dangerous prompt keywords and XML-like structures
        dangerous_patterns = {
            r"(?i)ignore.*instruction": "[FILTERED_INSTRUCTION_OVERRIDE]",
            r"(?i)forget.*prompt": "[FILTERED_CONTEXT_RESET]",
            r"(?i)system.*prompt": "[FILTERED_SYSTEM_REF]",
            r"<\s*/?system": "[FILTERED_XML_SYSTEM]",
            r"<\s*/?prompt": "[FILTERED_XML_PROMPT]",
        }

        escaped = text
        for pattern, replacement in dangerous_patterns.items():
            escaped = re.sub(pattern, replacement, escaped)

        return escaped

    @staticmethod
    def _escape_xml(text: str) -> str:
        """Escape XML special characters in text."""
        return (
            text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    @staticmethod
    def validate_code_for_analysis(code: str, max_length: int = 100000) -> tuple[bool, str]:
        """
        Validate code before sending to LLM for analysis.

        Args:
            code: Code to validate
            max_length: Maximum allowed code length

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not code:
            return False, "Code cannot be empty"

        if len(code) > max_length:
            return False, f"Code exceeds maximum length of {max_length} characters"

        # Check for obviously malicious patterns
        malicious_patterns = [
            r"(?i)__import__.*subprocess",  # Subprocess execution
            r"(?i)exec\s*\(",  # Dynamic code execution
            r"(?i)eval\s*\(",  # Dynamic evaluation
        ]

        for pattern in malicious_patterns:
            if re.search(pattern, code):
                return False, f"Code contains potentially dangerous pattern: {pattern}"

        return True, ""
