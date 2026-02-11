"""
Normalized Hasher Utility.

Provides content normalization for various programming languages to enable
semantic/structural hashing that ignores non-functional changes like
whitespace and comments.
"""

import hashlib
import re

from warden.ast.domain.enums import CodeLanguage


class NormalizedHasher:
    """
    Normalizes source code content for robust hashing.
    """

    @staticmethod
    def normalize(content: str, language: CodeLanguage) -> str:
        """
        Normalize content based on language specific rules.

        Args:
            content: Raw source code content
            language: CodeLanguage enum

        Returns:
            Normalized string suitable for semantic hashing
        """
        if not content:
            return ""

        # 1. Normalize line endings
        content = content.replace('\r\n', '\n').replace('\r', '\n')

        # 2. Language-specific comment removal
        content = NormalizedHasher._remove_comments(content, language)

        # 3. Structural normalization
        # Replace all whitespace sequences (including newlines) with a single space
        # This effectively ignores formatting changes while preserving necessary spaces
        content = re.sub(r'\s+', ' ', content)

        # 4. Remove spaces around common separators that don't need them
        # (This helps ignore differences like 'foo( )' vs 'foo()')
        content = re.sub(r'\s*([{}()\[\],;.:<>])\s*', r'\1', content)

        return content.strip()

    @staticmethod
    def _remove_comments(content: str, language: CodeLanguage) -> str:
        """Remove comments based on language patterns."""

        # Patterns for different language families

        # Family: C-style (// and /* */)
        # Python uses # but can also have docstrings
        # SQL uses --

        if language in [CodeLanguage.PYTHON]:
            # Remove # comments
            content = re.sub(r'#.*$', '', content, flags=re.MULTILINE)
            # Note: We don't remove docstrings as they often contain important metadata
            # or versioning that might be relevant for some frames.

        elif language in [
            CodeLanguage.JAVASCRIPT, CodeLanguage.TYPESCRIPT, CodeLanguage.TSX,
            CodeLanguage.JAVA, CodeLanguage.CSHARP, CodeLanguage.GO,
            CodeLanguage.RUST, CodeLanguage.KOTLIN, CodeLanguage.SWIFT,
            CodeLanguage.CPP, CodeLanguage.C, CodeLanguage.DART, CodeLanguage.PHP
        ]:
            # Remove /* */ multi-line comments
            content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
            # Remove // single-line comments
            content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)

        elif language == CodeLanguage.SQL:
            # Remove -- comments
            content = re.sub(r'--.*$', '', content, flags=re.MULTILINE)
            # Remove /* */ comments
            content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

        elif language in [CodeLanguage.YAML, CodeLanguage.SHELL]:
            # Remove # comments
            content = re.sub(r'#.*$', '', content, flags=re.MULTILINE)

        elif language == CodeLanguage.HTML:
            # Remove <!-- --> comments
            content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)

        return content

    @staticmethod
    def calculate_normalized_hash(content: str, language: CodeLanguage) -> str:
        """Calculate SHA-256 hash of normalized content."""
        normalized = NormalizedHasher.normalize(content, language)
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
