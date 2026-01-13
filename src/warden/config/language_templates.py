"""Language-specific configuration templates for Warden initialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any


@dataclass
class LanguageTemplate:
    """Template for language-specific Warden configuration."""

    language: str
    """Programming language name."""

    recommended_frames: List[str]
    """Recommended validation frames for this language."""

    required_ast_providers: List[str]
    """Required AST provider packages (built-in or PyPI)."""

    default_rules: Dict[str, Any]
    """Default frame configuration and rules."""

    llm_recommended: bool
    """Whether LLM analysis is recommended for this language."""

    description: str = ""
    """Optional description of why these frames are recommended."""


# Python Template
PYTHON_TEMPLATE = LanguageTemplate(
    language="python",
    recommended_frames=[
        "security",        # SQL injection, secrets detection
        "chaos",          # Error handling, resilience
        "orphan",         # Unused code detection (LLM-powered)
        "architectural",  # Design pattern consistency
    ],
    required_ast_providers=["python-native"],  # Built-in Python AST
    default_rules={
        "orphan": {
            "enabled": True,
            "use_llm_filter": True,  # LLM dramatically reduces false positives
            "ignore_test_files": True,
            "ignore_private": False,  # Check private methods too
            "ignore_imports": ["annotations", "TYPE_CHECKING"],
        },
        "security": {
            "enabled": True,
            "priority": "critical",
            "is_blocker": True,
            "checks": [
                "sql_injection",
                "xss",
                "hardcoded_secrets",
                "command_injection",
                "path_traversal",
            ],
        },
        "chaos": {
            "enabled": True,
            "priority": "high",
            "checks": [
                "timeout_handling",
                "retry_logic",
                "circuit_breaker",
                "error_recovery",
            ],
        },
        "architectural": {
            "enabled": False,  # Optional, needs configuration
            "priority": "low",
        },
    },
    llm_recommended=True,
    description="Python benefits from LLM analysis for dead code detection and architectural patterns",
)


# JavaScript/TypeScript Template
JAVASCRIPT_TEMPLATE = LanguageTemplate(
    language="javascript",
    recommended_frames=[
        "security",  # XSS, injection attacks
        "chaos",     # Async error handling
        "fuzz",      # Edge cases, type coercion
    ],
    required_ast_providers=["tree-sitter"],  # Universal parser
    default_rules={
        "security": {
            "enabled": True,
            "priority": "critical",
            "is_blocker": True,
            "checks": [
                "xss",
                "command_injection",
                "path_traversal",
                "prototype_pollution",
                "regex_dos",
            ],
        },
        "chaos": {
            "enabled": True,
            "priority": "high",
            "checks": [
                "promise_rejection",
                "async_error_handling",
                "timeout_handling",
            ],
        },
        "fuzz": {
            "enabled": True,
            "priority": "medium",
            "checks": [
                "null_handling",
                "undefined_handling",
                "type_coercion",
                "nan_handling",
                "empty_string",
            ],
        },
    },
    llm_recommended=True,
    description="JavaScript's dynamic nature benefits from LLM analysis for type safety and edge cases",
)


# Java Template
JAVA_TEMPLATE = LanguageTemplate(
    language="java",
    recommended_frames=[
        "security",  # SQL injection, deserialization
        "chaos",     # Exception handling
        "stress",    # Performance, memory leaks
    ],
    required_ast_providers=["warden-ast-java"],  # External provider from PyPI
    default_rules={
        "security": {
            "enabled": True,
            "priority": "critical",
            "is_blocker": True,
            "checks": [
                "sql_injection",
                "deserialization",
                "xxe",
                "ldap_injection",
                "log_injection",
            ],
        },
        "chaos": {
            "enabled": True,
            "priority": "high",
            "checks": [
                "exception_handling",
                "resource_cleanup",
                "concurrency_issues",
            ],
        },
        "stress": {
            "enabled": True,
            "priority": "medium",
            "checks": [
                "memory_leak",
                "thread_safety",
                "performance_under_load",
            ],
        },
    },
    llm_recommended=False,
    description="Java's static typing and AST analysis usually sufficient without LLM",
)


# Go Template
GO_TEMPLATE = LanguageTemplate(
    language="go",
    recommended_frames=[
        "security",  # Command injection, path traversal
        "property",  # Idempotency, pure functions
        "stress",    # Goroutine leaks, race conditions
    ],
    required_ast_providers=["warden-ast-go"],
    default_rules={
        "security": {
            "enabled": True,
            "priority": "critical",
            "is_blocker": True,
            "checks": [
                "command_injection",
                "path_traversal",
                "sql_injection",
                "hardcoded_secrets",
            ],
        },
        "property": {
            "enabled": True,
            "priority": "medium",
            "checks": [
                "idempotency",
                "pure_functions",
                "error_handling",
            ],
        },
        "stress": {
            "enabled": True,
            "priority": "high",
            "checks": [
                "goroutine_leak",
                "race_condition",
                "channel_deadlock",
            ],
        },
    },
    llm_recommended=False,
    description="Go's simplicity and strong typing reduce need for LLM analysis",
)


# Rust Template
RUST_TEMPLATE = LanguageTemplate(
    language="rust",
    recommended_frames=[
        "property",  # Ownership, borrowing rules
        "stress",    # Performance, unsafe blocks
    ],
    required_ast_providers=["warden-ast-rust"],
    default_rules={
        "property": {
            "enabled": True,
            "priority": "high",
            "checks": [
                "ownership_rules",
                "lifetime_annotations",
                "unsafe_usage",
            ],
        },
        "stress": {
            "enabled": True,
            "priority": "medium",
            "checks": [
                "performance_optimization",
                "memory_safety",
                "concurrent_access",
            ],
        },
    },
    llm_recommended=False,
    description="Rust compiler already catches most issues, Warden adds extra validation",
)


# C# Template
CSHARP_TEMPLATE = LanguageTemplate(
    language="csharp",
    recommended_frames=[
        "security",
        "chaos",
        "architectural",
    ],
    required_ast_providers=["warden-ast-csharp"],
    default_rules={
        "security": {
            "enabled": True,
            "priority": "critical",
            "is_blocker": True,
            "checks": [
                "sql_injection",
                "xss",
                "xxe",
                "deserialization",
                "ldap_injection",
            ],
        },
        "chaos": {
            "enabled": True,
            "priority": "high",
            "checks": [
                "exception_handling",
                "async_await",
                "disposal_pattern",
            ],
        },
        "architectural": {
            "enabled": True,
            "priority": "medium",
            "checks": [
                "dependency_injection",
                "repository_pattern",
                "solid_principles",
            ],
        },
    },
    llm_recommended=True,
    description="C# benefits from LLM for architectural patterns and async/await analysis",
)


# Ruby Template
RUBY_TEMPLATE = LanguageTemplate(
    language="ruby",
    recommended_frames=[
        "security",
        "chaos",
        "orphan",
    ],
    required_ast_providers=["warden-ast-ruby"],
    default_rules={
        "security": {
            "enabled": True,
            "priority": "critical",
            "checks": [
                "sql_injection",
                "command_injection",
                "yaml_deserialization",
            ],
        },
        "chaos": {
            "enabled": True,
            "priority": "high",
            "checks": [
                "exception_handling",
                "block_usage",
            ],
        },
        "orphan": {
            "enabled": True,
            "use_llm_filter": True,
        },
    },
    llm_recommended=True,
    description="Ruby's dynamic metaprogramming benefits from LLM analysis",
)


# PHP Template
PHP_TEMPLATE = LanguageTemplate(
    language="php",
    recommended_frames=[
        "security",  # Critical for web apps
        "chaos",
        "fuzz",
    ],
    required_ast_providers=["warden-ast-php"],
    default_rules={
        "security": {
            "enabled": True,
            "priority": "critical",
            "is_blocker": True,
            "checks": [
                "sql_injection",
                "xss",
                "command_injection",
                "file_inclusion",
                "session_fixation",
            ],
        },
    },
    llm_recommended=True,
    description="PHP web applications need thorough security analysis",
)


# Generic/Fallback Template
GENERIC_TEMPLATE = LanguageTemplate(
    language="generic",
    recommended_frames=[
        "security",
        "chaos",
    ],
    required_ast_providers=["tree-sitter"],  # Universal fallback
    default_rules={
        "security": {
            "enabled": True,
            "priority": "high",
            "checks": ["generic_security"],
        },
        "chaos": {
            "enabled": True,
            "priority": "medium",
            "checks": ["error_handling"],
        },
    },
    llm_recommended=True,
    description="Generic configuration for unsupported languages",
)


# Template Registry
LANGUAGE_TEMPLATES: Dict[str, LanguageTemplate] = {
    "python": PYTHON_TEMPLATE,
    "javascript": JAVASCRIPT_TEMPLATE,
    "typescript": JAVASCRIPT_TEMPLATE,  # Same as JS
    "java": JAVA_TEMPLATE,
    "go": GO_TEMPLATE,
    "rust": RUST_TEMPLATE,
    "csharp": CSHARP_TEMPLATE,
    "cs": CSHARP_TEMPLATE,  # Alias
    "ruby": RUBY_TEMPLATE,
    "php": PHP_TEMPLATE,
    "c": GENERIC_TEMPLATE,  # Use generic for C
    "cpp": GENERIC_TEMPLATE,  # Use generic for C++
    "kotlin": JAVA_TEMPLATE,  # Similar to Java
    "swift": GENERIC_TEMPLATE,
}


def get_language_template(language: str) -> LanguageTemplate:
    """
    Get language template by name, with fallback to generic.

    Args:
        language: Programming language name

    Returns:
        Language template (generic if not found)
    """
    return LANGUAGE_TEMPLATES.get(language.lower(), GENERIC_TEMPLATE)


def get_supported_languages() -> List[str]:
    """Get list of languages with specific templates."""
    return [
        lang for lang in LANGUAGE_TEMPLATES.keys()
        if LANGUAGE_TEMPLATES[lang] != GENERIC_TEMPLATE
    ]