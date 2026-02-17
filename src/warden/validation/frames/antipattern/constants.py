"""
Anti-Pattern Detection Constants

Universal AST node type mappings and pattern configurations.
"""

from typing import Any

# =============================================================================
# UNIVERSAL AST NODE TYPE MAPPINGS
# =============================================================================

# Tree-sitter node types that represent try-catch/exception handling
TRY_CATCH_NODE_TYPES: set[str] = {
    # Python
    "try_statement",
    "except_clause",
    # JavaScript/TypeScript
    "catch_clause",
    # Java/Kotlin
    "try_with_resources_statement",
    # C#
    "catch_declaration",
    # Go (error handling is different but we check for patterns)
    "if_statement",  # if err != nil {...}
    # Ruby
    "begin",
    "rescue",
    "rescue_block",
    # PHP
    # Rust (Result/Option handling)
    "match_expression",
    "if_let_expression",
    # Swift
    "do_statement",  # Scala
    "try_expression",
}

# Tree-sitter node types for class definitions
CLASS_NODE_TYPES: set[str] = {
    # Python
    "class_definition",
    # JavaScript/TypeScript
    "class_declaration",
    "class",
    # Java
    "interface_declaration",
    # C#
    "struct_declaration",
    # Go
    "type_declaration",
    "type_spec",  # struct
    # Rust
    "struct_item",
    "impl_item",
    "trait_item",
    # Ruby
    "module",
    # PHP
    # Kotlin
    "object_declaration",
    # Swift
    "protocol_declaration",
    # Scala
    "object_definition",
    "trait_definition",
}

# Tree-sitter node types for function calls (debug output detection)
CALL_NODE_TYPES: set[str] = {
    "call_expression",
    "call",
    "invocation_expression",
    "method_invocation",
    "function_call",
    "application",
}

# Debug function names by category (language-agnostic where possible)
DEBUG_FUNCTION_NAMES: set[str] = {
    # Python
    "print",
    "pprint",
    # JavaScript/TypeScript (console methods detected separately)
    # Java
    "println",
    "printStackTrace",
    # Go
    "Println",
    "Printf",
    "Print",
    # Rust
    "println!",
    "print!",
    "dbg!",
    "eprintln!",  # Rust macros
    # Ruby
    "puts",
    "p",
    "pp",
    # PHP
    "var_dump",
    "print_r",
    "dd",
    "dump",
    "die",
    # Kotlin
    # Swift
    "debugPrint",  # Scala
    # Dart
    # C/C++
    "printf",
    "fprintf",
    "cout",
}

# Debug member access patterns (e.g., console.log, System.out.println)
DEBUG_MEMBER_PATTERNS: dict[str, set[str]] = {
    "console": {"log", "debug", "info", "warn", "error", "trace"},
    "System.out": {"print", "println", "printf"},
    "System.err": {"print", "println", "printf"},
    "Debug": {"Write", "WriteLine", "Print"},
    "Trace": {"Write", "WriteLine"},
    "Console": {"Write", "WriteLine"},
    "fmt": {"Print", "Println", "Printf"},
    "log": {"Print", "Println", "Printf"},
    "std::cout": {"<<"},
    "std::cerr": {"<<"},
}


# =============================================================================
# LANGUAGE-SPECIFIC PATTERNS
# =============================================================================


def get_exception_patterns(language: str) -> dict[str, Any]:
    """Get exception handling patterns for a language."""
    patterns = {
        "python": {
            "bare_catch": [r"except\s*:", r"except\s+BaseException\s*:"],
            "empty_catch": r"except.*:\s*\n\s+pass\s*$",
            "generic_raise": r"raise\s+Exception\s*\(",
        },
        "javascript": {
            "bare_catch": [r"catch\s*\{\s*\}", r"catch\s*\(\s*\w*\s*\)\s*\{\s*\}"],
            "empty_catch": r"catch\s*\([^)]*\)\s*\{\s*\}",
            "generic_raise": r"throw\s+new\s+Error\s*\(",
        },
        "typescript": {
            "bare_catch": [r"catch\s*\{\s*\}", r"catch\s*\(\s*\w*\s*\)\s*\{\s*\}"],
            "empty_catch": r"catch\s*\([^)]*\)\s*\{\s*\}",
            "generic_raise": r"throw\s+new\s+Error\s*\(",
        },
        "java": {
            "bare_catch": [r"catch\s*\(\s*Throwable\s+\w+\s*\)"],
            "empty_catch": r"catch\s*\([^)]+\)\s*\{\s*\}",
            "generic_raise": r"throw\s+new\s+Exception\s*\(",
        },
        "csharp": {
            "bare_catch": [r"catch\s*\{\s*\}", r"catch\s*\(\s*Exception\s*\)"],
            "empty_catch": r"catch\s*(\([^)]*\))?\s*\{\s*\}",
            "generic_raise": r"throw\s+new\s+Exception\s*\(",
        },
        "go": {
            "bare_catch": [],
            "empty_catch": r"if\s+err\s*!=\s*nil\s*\{\s*\}",
            "generic_raise": [],
        },
        "rust": {
            "bare_catch": [],
            "empty_catch": [],
            "generic_raise": r"panic!\s*\(",
        },
        "ruby": {
            "bare_catch": [r"rescue\s*$", r"rescue\s+Exception"],
            "empty_catch": r"rescue.*\n\s*end",
            "generic_raise": r"raise\s+['\"]",
        },
        "php": {
            "bare_catch": [r"catch\s*\(\s*\\?Throwable\s+"],
            "empty_catch": r"catch\s*\([^)]+\)\s*\{\s*\}",
            "generic_raise": r"throw\s+new\s+\\?Exception\s*\(",
        },
    }
    return patterns.get(language, {})


def get_debug_patterns(language: str) -> list[str]:
    """Get debug output patterns for a language."""
    patterns = {
        "python": [r"print\s*\("],
        "javascript": [r"console\.(log|debug|info|warn|error)\s*\(", r"debugger\s*;"],
        "typescript": [r"console\.(log|debug|info|warn|error)\s*\(", r"debugger\s*;"],
        "java": [r"System\.(out|err)\.(print|println)\s*\(", r"\.printStackTrace\s*\("],
        "csharp": [r"Console\.(Write|WriteLine)\s*\(", r"Debug\.(Write|WriteLine)\s*\("],
        "go": [r"fmt\.(Print|Println|Printf)\s*\("],
        "rust": [r"println!\s*\(", r"dbg!\s*\("],
        "ruby": [r"\bputs\s+", r"\bp\s+"],
        "php": [r"var_dump\s*\(", r"print_r\s*\(", r"dd\s*\("],
        "kotlin": [r"println\s*\("],
        "swift": [r"print\s*\(", r"debugPrint\s*\("],
    }
    return patterns.get(language, [])
