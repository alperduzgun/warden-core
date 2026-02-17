"""
Language definitions and metadata.
"""

from pydantic import BaseModel, Field

from warden.ast.domain.enums import CodeLanguage


class LanguageDefinition(BaseModel):
    """Rich metadata for a programming language."""

    name: str
    id: CodeLanguage
    extensions: set[str]
    primary_extension: str
    aliases: list[str] = Field(default_factory=list)
    is_compiled: bool = False
    is_web: bool = False
    is_mobile: bool = False
    is_analyzable: bool = False
    tree_sitter_id: str | None = None
    proto_type_name: str | None = None
    linter_names: list[str] = Field(default_factory=list)


# Central Registry of Language Metadata
LANGUAGE_DEFINITIONS: list[LanguageDefinition] = [
    LanguageDefinition(
        name="Python",
        id=CodeLanguage.PYTHON,
        extensions={".py", ".pyw"},
        primary_extension=".py",
        aliases=["python3", "py"],
        tree_sitter_id="python",
        proto_type_name="PYTHON",
        is_analyzable=True,
        linter_names=["flake8", "pylint", "ruff"],
    ),
    LanguageDefinition(
        name="JavaScript",
        id=CodeLanguage.JAVASCRIPT,
        extensions={".js", ".jsx", ".mjs", ".cjs"},
        primary_extension=".js",
        aliases=["js", "jsx", "node"],
        is_web=True,
        tree_sitter_id="javascript",
        proto_type_name="JAVASCRIPT",
        is_analyzable=True,
        linter_names=["eslint"],
    ),
    LanguageDefinition(
        name="TypeScript",
        id=CodeLanguage.TYPESCRIPT,
        extensions={".ts"},
        primary_extension=".ts",
        aliases=["ts"],
        is_web=True,
        tree_sitter_id="typescript",
        proto_type_name="TYPESCRIPT",
        is_analyzable=True,
        linter_names=["eslint", "tsc"],
    ),
    LanguageDefinition(
        name="TSX",
        id=CodeLanguage.TSX,
        extensions={".tsx"},
        primary_extension=".tsx",
        is_web=True,
        tree_sitter_id="tsx",
        proto_type_name="TYPESCRIPT",
        is_analyzable=True,
        linter_names=["eslint"],
    ),
    LanguageDefinition(
        name="Go",
        id=CodeLanguage.GO,
        extensions={".go"},
        primary_extension=".go",
        is_compiled=True,
        tree_sitter_id="go",
        proto_type_name="GO",
        is_analyzable=True,
        linter_names=["golangci-lint", "staticcheck"],
    ),
    LanguageDefinition(
        name="Rust",
        id=CodeLanguage.RUST,
        extensions={".rs"},
        primary_extension=".rs",
        is_compiled=True,
        tree_sitter_id="rust",
        proto_type_name="RUST",
        is_analyzable=True,
        linter_names=["clippy"],
    ),
    LanguageDefinition(
        name="Java",
        id=CodeLanguage.JAVA,
        extensions={".java"},
        primary_extension=".java",
        is_compiled=True,
        tree_sitter_id="java",
        proto_type_name="JAVA",
        is_analyzable=True,
        linter_names=["checkstyle"],
    ),
    LanguageDefinition(
        name="Dart",
        id=CodeLanguage.DART,
        extensions={".dart"},
        primary_extension=".dart",
        is_mobile=True,
        tree_sitter_id="dart",
        proto_type_name="DART",
        is_analyzable=True,
        linter_names=["dart_analyze"],
    ),
    LanguageDefinition(
        name="Swift",
        id=CodeLanguage.SWIFT,
        extensions={".swift"},
        primary_extension=".swift",
        is_mobile=True,
        is_compiled=True,
        tree_sitter_id="swift",
        proto_type_name="SWIFT",
        is_analyzable=True,
        linter_names=["swiftlint"],
    ),
    LanguageDefinition(
        name="Kotlin",
        id=CodeLanguage.KOTLIN,
        extensions={".kt", ".kts"},
        primary_extension=".kt",
        is_mobile=True,
        is_compiled=True,
        tree_sitter_id="kotlin",
        proto_type_name="KOTLIN",
        is_analyzable=True,
        linter_names=["ktlint"],
    ),
    LanguageDefinition(
        name="C",
        id=CodeLanguage.C,
        extensions={".c", ".h"},
        primary_extension=".c",
        is_compiled=True,
        tree_sitter_id="c",
        proto_type_name="C",
        is_analyzable=True,
    ),
    LanguageDefinition(
        name="C++",
        id=CodeLanguage.CPP,
        extensions={".cpp", ".hpp", ".cc", ".hh"},
        primary_extension=".cpp",
        is_compiled=True,
        tree_sitter_id="cpp",
        proto_type_name="CPP",
        is_analyzable=True,
    ),
    LanguageDefinition(
        name="C#",
        id=CodeLanguage.CSHARP,
        extensions={".cs"},
        primary_extension=".cs",
        is_compiled=True,
        tree_sitter_id="c_sharp",
        proto_type_name="CSHARP",
        is_analyzable=True,
    ),
    LanguageDefinition(
        name="Ruby",
        id=CodeLanguage.RUBY,
        extensions={".rb"},
        primary_extension=".rb",
        tree_sitter_id="ruby",
        proto_type_name="RUBY",
        is_analyzable=True,
        linter_names=["rubocop"],
    ),
    LanguageDefinition(
        name="PHP",
        id=CodeLanguage.PHP,
        extensions={".php"},
        primary_extension=".php",
        tree_sitter_id="php",
        proto_type_name="PHP",
        is_analyzable=True,
        linter_names=["phpcs", "phpstan"],
    ),
    LanguageDefinition(
        name="Scala",
        id=CodeLanguage.SCALA,
        extensions={".scala", ".sc"},
        primary_extension=".scala",
        is_compiled=True,
        tree_sitter_id="scala",
        proto_type_name="SCALA",
        is_analyzable=True,
    ),
    LanguageDefinition(
        name="Markdown",
        id=CodeLanguage.MARKDOWN,
        extensions={".md", ".markdown"},
        primary_extension=".md",
        tree_sitter_id="markdown",
        proto_type_name="MARKDOWN",
    ),
    LanguageDefinition(
        name="YAML",
        id=CodeLanguage.YAML,
        extensions={".yaml", ".yml"},
        primary_extension=".yaml",
        tree_sitter_id="yaml",
        proto_type_name="YAML",
    ),
    LanguageDefinition(
        name="JSON",
        id=CodeLanguage.JSON,
        extensions={".json"},
        primary_extension=".json",
        tree_sitter_id="json",
        proto_type_name="JSON",
    ),
    LanguageDefinition(
        name="HTML",
        id=CodeLanguage.HTML,
        extensions={".html", ".htm"},
        primary_extension=".html",
        is_web=True,
        tree_sitter_id="html",
        proto_type_name="HTML",
    ),
    LanguageDefinition(
        name="CSS",
        id=CodeLanguage.CSS,
        extensions={".css", ".scss", ".sass", ".less"},
        primary_extension=".css",
        is_web=True,
        tree_sitter_id="css",
        proto_type_name="CSS",
    ),
    LanguageDefinition(
        name="Shell",
        id=CodeLanguage.SHELL,
        extensions={".sh", ".bash", ".zsh"},
        primary_extension=".sh",
        tree_sitter_id="bash",
        proto_type_name="SHELL",
    ),
    LanguageDefinition(
        name="SQL",
        id=CodeLanguage.SQL,
        extensions={".sql"},
        primary_extension=".sql",
        tree_sitter_id="sql",
        proto_type_name="SQL",
    ),
]
