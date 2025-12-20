"""
Warden AST Module - Pluggable AST Parsing System.

This module provides a pluggable architecture for parsing Abstract Syntax Trees (AST)
from multiple programming languages.

Key Features:
    - Universal AST representation (language-agnostic)
    - Priority-based provider selection (Native > Tree-sitter > Community)
    - Auto-discovery of providers (built-in, PyPI, local plugins, env vars)
    - Extensible architecture for community providers

Example usage:
    from warden.ast import ASTService
    from warden.ast.domain import CodeLanguage

    # Initialize service (auto-loads all providers)
    ast_service = ASTService()
    await ast_service.initialize()

    # Parse Python code (uses PythonASTProvider - highest priority)
    result = await ast_service.parse(source_code, CodeLanguage.PYTHON)

    if result.is_success():
        # Access universal AST
        functions = result.ast_root.find_nodes(ASTNodeType.FUNCTION)

Community Provider Example (PyPI):
    # In your package setup.py/pyproject.toml:
    entry_points={
        'warden.ast_providers': [
            'kotlin = warden_ast_kotlin:KotlinASTProvider'
        ]
    }

    # Warden auto-discovers and registers your provider
"""

from warden.ast.domain import (
    ASTNode,
    ASTNodeType,
    ASTProviderMetadata,
    ASTProviderPriority,
    CodeLanguage,
    ParseError,
    ParseResult,
    ParseStatus,
    SourceLocation,
)
from warden.ast.application import (
    IASTProvider,
    ASTProviderLoader,
    ASTProviderRegistry,
)

__all__ = [
    # Domain Models
    "ASTNode",
    "ASTNodeType",
    "ASTProviderMetadata",
    "ASTProviderPriority",
    "CodeLanguage",
    "ParseError",
    "ParseResult",
    "ParseStatus",
    "SourceLocation",
    # Application Services
    "IASTProvider",
    "ASTProviderLoader",
    "ASTProviderRegistry",
]
