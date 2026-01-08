"""
AST domain enums.

Defines AST provider priorities and node types.
"""

from enum import IntEnum, Enum


class ASTProviderPriority(IntEnum):
    """
    AST provider priority for auto-selection.

    Lower values are preferred (higher priority).
    When multiple providers support a language, highest priority is used.
    """

    NATIVE = 1  # Language-specific native parser (e.g., Python ast module)
    SPECIALIZED = 2  # Specialized third-party parser (e.g., esprima for JS)
    TREE_SITTER = 3  # Tree-sitter universal parser
    COMMUNITY = 4  # Community-contributed providers
    FALLBACK = 5  # Fallback/basic parsers


class ASTNodeType(str, Enum):
    """
    Universal AST node types.

    Language-agnostic node classification for cross-language analysis.
    """

    # Program Structure
    MODULE = "module"
    CLASS = "class"
    INTERFACE = "interface"
    FUNCTION = "function"
    METHOD = "method"
    PROPERTY = "property"
    FIELD = "field"

    # Statements
    IMPORT = "import"
    EXPORT = "export"
    VARIABLE_DECLARATION = "variable_declaration"
    ASSIGNMENT = "assignment"
    EXPRESSION_STATEMENT = "expression_statement"
    RETURN_STATEMENT = "return_statement"
    IF_STATEMENT = "if_statement"
    LOOP_STATEMENT = "loop_statement"
    TRY_CATCH = "try_catch"
    THROW_STATEMENT = "throw_statement"

    # Expressions
    CALL_EXPRESSION = "call_expression"
    BINARY_EXPRESSION = "binary_expression"
    UNARY_EXPRESSION = "unary_expression"
    LITERAL = "literal"
    IDENTIFIER = "identifier"
    MEMBER_ACCESS = "member_access"
    ARRAY_ACCESS = "array_access"

    # Special
    COMMENT = "comment"
    DECORATOR = "decorator"
    ANNOTATION = "annotation"
    GENERIC_TYPE = "generic_type"
    UNKNOWN = "unknown"


class ParseStatus(str, Enum):
    """Parse operation status."""

    SUCCESS = "success"
    PARTIAL = "partial"  # Some errors but AST available
    FAILED = "failed"  # Complete failure
    UNSUPPORTED = "unsupported"  # Language not supported


class CodeLanguage(str, Enum):
    """
    Supported programming languages.

    Must match Panel TypeScript CodeLanguage enum.
    """

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    CSHARP = "csharp"
    JAVA = "java"
    DART = "dart"
    GO = "go"
    RUST = "rust"
    KOTLIN = "kotlin"
    SWIFT = "swift"
    PHP = "php"
    RUBY = "ruby"
    CPP = "cpp"
    C = "c"
    TSX = "tsx"
    HTML = "html"
    CSS = "css"
    JSON = "json"
    YAML = "yaml"
    MARKDOWN = "markdown"
    SHELL = "shell"
    SQL = "sql"
    UNKNOWN = "unknown"
