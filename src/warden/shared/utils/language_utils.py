"""
Language detection utilities.

Maps file extensions to supported programming languages.
"""

from pathlib import Path
from typing import Dict, List, Set
from warden.ast.domain.enums import CodeLanguage

# Mapping of file extensions to CodeLanguage
EXTENSION_TO_LANGUAGE: Dict[str, CodeLanguage] = {
    # Backend / General
    ".py": CodeLanguage.PYTHON,
    ".go": CodeLanguage.GO,
    ".rs": CodeLanguage.RUST,
    ".java": CodeLanguage.JAVA,
    ".cs": CodeLanguage.CSHARP,
    ".rb": CodeLanguage.RUBY,
    ".php": CodeLanguage.PHP,
    ".c": CodeLanguage.C,
    ".h": CodeLanguage.C,
    ".cpp": CodeLanguage.CPP,
    ".hpp": CodeLanguage.CPP,
    ".cc": CodeLanguage.CPP,
    ".hh": CodeLanguage.CPP,
    
    # Web / Frontend
    ".js": CodeLanguage.JAVASCRIPT,
    ".jsx": CodeLanguage.JAVASCRIPT,
    ".ts": CodeLanguage.TYPESCRIPT,
    ".tsx": CodeLanguage.TSX,
    
    # Mobile
    ".dart": CodeLanguage.DART,
    ".swift": CodeLanguage.SWIFT,
    ".kt": CodeLanguage.KOTLIN,
    ".kts": CodeLanguage.KOTLIN,
    
    # Data / Config (can be indexed as generic by tree-sitter)
    ".json": CodeLanguage.JSON,
    ".yaml": CodeLanguage.YAML,
    ".yml": CodeLanguage.YAML,
    ".md": CodeLanguage.MARKDOWN,
    ".sql": CodeLanguage.SQL,
    ".sh": CodeLanguage.SHELL,
    ".html": CodeLanguage.HTML,
    ".css": CodeLanguage.CSS,
    ".proto": CodeLanguage.UNKNOWN,
}

# Primary extension for each language (reverse mapping)
LANGUAGE_TO_EXTENSION: Dict[CodeLanguage, str] = {
    CodeLanguage.PYTHON: ".py",
    CodeLanguage.GO: ".go",
    CodeLanguage.RUST: ".rs",
    CodeLanguage.JAVA: ".java",
    CodeLanguage.CSHARP: ".cs",
    CodeLanguage.RUBY: ".rb",
    CodeLanguage.PHP: ".php",
    CodeLanguage.C: ".c",
    CodeLanguage.CPP: ".cpp",
    CodeLanguage.JAVASCRIPT: ".js",
    CodeLanguage.TYPESCRIPT: ".ts",
    CodeLanguage.TSX: ".tsx",
    CodeLanguage.DART: ".dart",
    CodeLanguage.SWIFT: ".swift",
    CodeLanguage.KOTLIN: ".kt",
    CodeLanguage.HTML: ".html",
    CodeLanguage.CSS: ".css",
    CodeLanguage.JSON: ".json",
    CodeLanguage.YAML: ".yaml",
    CodeLanguage.MARKDOWN: ".md",
    CodeLanguage.SHELL: ".sh",
    CodeLanguage.SQL: ".sql",
}

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

def get_language_from_path(path: Path | str) -> CodeLanguage:
    """
    Detect programming language from file path.
    
    Args:
        path: File path or string
        
    Returns:
        Detected CodeLanguage (UNKNOWN if not recognized)
    """
    if not path:
        return CodeLanguage.UNKNOWN

    try:
        # Handle string input and ensure it's a valid path format
        if isinstance(path, str):
            if '\0' in path: # Basic malformed path check
                 logger.warning("malformed_path_input", path=path)
                 return CodeLanguage.UNKNOWN
            path = Path(path)
            
        ext = path.suffix.lower()
        lang = EXTENSION_TO_LANGUAGE.get(ext)
        
        if lang:
            return lang
            
        # Fallback with logging for resilience
        if ext:
            logger.debug("unknown_extension_encountered", extension=ext, path=str(path))
            
        return CodeLanguage.UNKNOWN
    except (TypeError, ValueError, OSError) as e:
        # Catch specific path-related errors
        logger.warning("language_detection_failed", error=str(e), path=str(path))
        return CodeLanguage.UNKNOWN
    except Exception as e:
        # Catch-all for unexpected failures (critical for resilience)
        logger.error("unexpected_error_in_language_detection", error=str(e), path=str(path))
        return CodeLanguage.UNKNOWN

def get_primary_extension(language: CodeLanguage | str) -> str:
    """
    Get primary file extension for a language.
    
    Args:
        language: CodeLanguage enum or string value
        
    Returns:
        Extension string (e.g., '.py') or empty string if not found
    """
    if not language:
        return ""

    try:
        if isinstance(language, str):
            try:
                language = CodeLanguage(language.lower())
            except ValueError:
                return ""
                
        return LANGUAGE_TO_EXTENSION.get(language, "")
    except Exception as e:
        logger.warning("get_primary_extension_failed", error=str(e), language=str(language))
        return ""

def get_supported_extensions() -> List[str]:
    """Get list of supported file extensions for indexing."""
    return list(EXTENSION_TO_LANGUAGE.keys())

def get_code_extensions() -> Set[str]:
    """Get set of primary source code extensions (excluding generic config)."""
    return {
        ext for ext, lang in EXTENSION_TO_LANGUAGE.items() 
        if lang != CodeLanguage.UNKNOWN
    }
