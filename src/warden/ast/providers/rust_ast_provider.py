"""
Rust AST Provider.

Wraps the Rust warden_core_rust.get_ast_metadata() function to provide
shallow AST trees via the IASTProvider interface.

The Rust extension returns flat metadata (functions, classes, imports,
references) — not a full nested AST. This provider converts that metadata
into a shallow ASTNode tree suitable for lightweight queries.

Priority: COMMUNITY (4) — below TreeSitter (3) because the tree is shallow.
Falls back gracefully when the Rust extension is not available.
"""

import time
from typing import Any

import structlog

from warden.ast.application.provider_interface import IASTProvider
from warden.ast.domain.enums import (
    ASTNodeType,
    ASTProviderPriority,
    CodeLanguage,
    ParseStatus,
)
from warden.ast.domain.models import (
    ASTNode,
    ASTProviderMetadata,
    ParseResult,
    SourceLocation,
)

logger = structlog.get_logger(__name__)

# Try to import the Rust extension
try:
    import warden_core_rust

    _RUST_AVAILABLE = True
except ImportError:
    warden_core_rust = None
    _RUST_AVAILABLE = False

# Languages supported by Rust tree-sitter (must match get_language_parser in lib.rs)
_SUPPORTED_LANGUAGES = [
    CodeLanguage.PYTHON,
    CodeLanguage.TYPESCRIPT,
    CodeLanguage.JAVASCRIPT,
    CodeLanguage.GO,
    CodeLanguage.JAVA,
]


class RustASTProvider(IASTProvider):
    """
    AST provider backed by Rust + tree-sitter.

    Produces shallow AST trees from Rust's get_ast_metadata() output.
    Each tree has a MODULE root with flat FUNCTION, CLASS, and IMPORT children.
    The root node carries references in its attributes dict.

    The ``is_shallow`` attribute on the root node signals to consumers that
    the tree lacks nested structure.
    """

    @property
    def metadata(self) -> ASTProviderMetadata:
        return ASTProviderMetadata(
            name="RustASTProvider",
            priority=ASTProviderPriority.COMMUNITY,
            supported_languages=list(_SUPPORTED_LANGUAGES),
            version="1.0.0",
            description="Rust tree-sitter based shallow AST provider",
            author="warden",
        )

    def supports_language(self, language: CodeLanguage) -> bool:
        return _RUST_AVAILABLE and language in _SUPPORTED_LANGUAGES

    async def validate(self) -> bool:
        return _RUST_AVAILABLE

    async def parse(
        self,
        source_code: str,
        language: CodeLanguage,
        file_path: str | None = None,
    ) -> ParseResult:
        if not _RUST_AVAILABLE:
            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name="RustASTProvider",
                file_path=file_path,
            )

        if language not in _SUPPORTED_LANGUAGES:
            return ParseResult(
                status=ParseStatus.UNSUPPORTED,
                language=language,
                provider_name="RustASTProvider",
                file_path=file_path,
            )

        start = time.perf_counter()

        try:
            meta = warden_core_rust.get_ast_metadata(source_code, language.value)
        except Exception as e:
            logger.debug("rust_ast_parse_error", error=str(e), file=file_path)
            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name="RustASTProvider",
                file_path=file_path,
            )

        # Build shallow ASTNode tree
        children: list[ASTNode] = []

        for func in meta.functions:
            children.append(
                _make_node(ASTNodeType.FUNCTION, func, file_path)
            )

        for cls in meta.classes:
            children.append(
                _make_node(ASTNodeType.CLASS, cls, file_path)
            )

        for imp in meta.imports:
            children.append(
                _make_node(ASTNodeType.IMPORT, imp, file_path)
            )

        root = ASTNode(
            node_type=ASTNodeType.MODULE,
            name=file_path,
            children=children,
            attributes={
                "references": list(meta.references),
                "is_shallow": True,
            },
        )

        elapsed = (time.perf_counter() - start) * 1000

        return ParseResult(
            status=ParseStatus.SUCCESS,
            language=language,
            provider_name="RustASTProvider",
            ast_root=root,
            parse_time_ms=elapsed,
            file_path=file_path,
        )

    def extract_dependencies(
        self, source_code: str, language: CodeLanguage
    ) -> list[str]:
        if not _RUST_AVAILABLE or language not in _SUPPORTED_LANGUAGES:
            return []

        try:
            meta = warden_core_rust.get_ast_metadata(source_code, language.value)
            return [imp.name for imp in meta.imports]
        except Exception:
            return []


def _make_node(
    node_type: ASTNodeType,
    info: Any,
    file_path: str | None,
) -> ASTNode:
    """Convert a Rust AstNodeInfo into a universal ASTNode."""
    location = SourceLocation(
        file_path=file_path or "",
        start_line=info.line_number,
        start_column=0,
        end_line=info.line_number,
        end_column=0,
    )
    return ASTNode(
        node_type=node_type,
        name=info.name,
        value=info.code_snippet,
        location=location,
    )
