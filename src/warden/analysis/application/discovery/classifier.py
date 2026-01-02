"""
File type classifier.

Detects file types based on file extensions.
"""

from pathlib import Path
from typing import Dict, Set

from warden.analysis.application.discovery.models import FileType


class FileClassifier:
    """
    Classifies files by their extension.

    Maps file extensions to FileType enum values.
    """

    # Extension to FileType mapping
    EXTENSION_MAP: Dict[str, FileType] = {
        # Python
        ".py": FileType.PYTHON,
        ".pyw": FileType.PYTHON,
        ".pyi": FileType.PYTHON,
        # JavaScript
        ".js": FileType.JAVASCRIPT,
        ".mjs": FileType.JAVASCRIPT,
        ".cjs": FileType.JAVASCRIPT,
        # TypeScript
        ".ts": FileType.TYPESCRIPT,
        ".mts": FileType.TYPESCRIPT,
        ".cts": FileType.TYPESCRIPT,
        # JSX/TSX
        ".jsx": FileType.JSX,
        ".tsx": FileType.TSX,
        # Web
        ".html": FileType.HTML,
        ".htm": FileType.HTML,
        ".css": FileType.CSS,
        ".scss": FileType.CSS,
        ".sass": FileType.CSS,
        ".less": FileType.CSS,
        # Data
        ".json": FileType.JSON,
        ".yaml": FileType.YAML,
        ".yml": FileType.YAML,
        # Documentation
        ".md": FileType.MARKDOWN,
        ".markdown": FileType.MARKDOWN,
        ".rst": FileType.MARKDOWN,
        # Shell
        ".sh": FileType.SHELL,
        ".bash": FileType.SHELL,
        ".zsh": FileType.SHELL,
        ".fish": FileType.SHELL,
        # SQL
        ".sql": FileType.SQL,
        # Go
        ".go": FileType.GO,
        # Rust
        ".rs": FileType.RUST,
        # Java
        ".java": FileType.JAVA,
        # Kotlin
        ".kt": FileType.KOTLIN,
        ".kts": FileType.KOTLIN,
        # Swift
        ".swift": FileType.SWIFT,
        # Ruby
        ".rb": FileType.RUBY,
        ".rake": FileType.RUBY,
        # PHP
        ".php": FileType.PHP,
        # C/C++
        ".c": FileType.C,
        ".h": FileType.C,
        ".cpp": FileType.CPP,
        ".cc": FileType.CPP,
        ".cxx": FileType.CPP,
        ".hpp": FileType.CPP,
        ".hxx": FileType.CPP,
        # C#
        ".cs": FileType.CSHARP,
    }

    # Common non-code files to skip
    SKIP_EXTENSIONS: Set[str] = {
        # Images
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".webp",
        # Videos
        ".mp4",
        ".avi",
        ".mov",
        ".wmv",
        # Audio
        ".mp3",
        ".wav",
        ".ogg",
        # Archives
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".rar",
        # Binary
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        # Documents
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        # Fonts
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        # Other
        ".lock",
        ".log",
        ".tmp",
        ".cache",
    }

    @classmethod
    def classify(cls, file_path: Path) -> FileType:
        """
        Classify a file by its extension.

        Args:
            file_path: Path to the file to classify

        Returns:
            FileType enum value

        Examples:
            >>> classifier = FileClassifier()
            >>> classifier.classify(Path("main.py"))
            FileType.PYTHON
            >>> classifier.classify(Path("app.tsx"))
            FileType.TSX
        """
        extension = file_path.suffix.lower()

        # Check if extension is in our mapping
        if extension in cls.EXTENSION_MAP:
            return cls.EXTENSION_MAP[extension]

        # Unknown file type
        return FileType.UNKNOWN

    @classmethod
    def should_skip(cls, file_path: Path) -> bool:
        """
        Check if a file should be skipped (non-code files).

        Args:
            file_path: Path to check

        Returns:
            True if file should be skipped, False otherwise

        Examples:
            >>> FileClassifier.should_skip(Path("image.png"))
            True
            >>> FileClassifier.should_skip(Path("main.py"))
            False
        """
        extension = file_path.suffix.lower()
        return extension in cls.SKIP_EXTENSIONS

    @classmethod
    def is_analyzable(cls, file_path: Path) -> bool:
        """
        Check if a file can be analyzed by Warden.

        Args:
            file_path: Path to check

        Returns:
            True if file is analyzable, False otherwise

        Examples:
            >>> FileClassifier.is_analyzable(Path("main.py"))
            True
            >>> FileClassifier.is_analyzable(Path("README.md"))
            False
        """
        if cls.should_skip(file_path):
            return False

        file_type = cls.classify(file_path)
        return file_type.is_analyzable

    @classmethod
    def get_supported_extensions(cls) -> Set[str]:
        """
        Get all supported file extensions.

        Returns:
            Set of file extensions (including the dot)

        Examples:
            >>> extensions = FileClassifier.get_supported_extensions()
            >>> ".py" in extensions
            True
        """
        return set(cls.EXTENSION_MAP.keys())

    @classmethod
    def get_analyzable_extensions(cls) -> Set[str]:
        """
        Get file extensions that can be analyzed.

        Returns:
            Set of analyzable file extensions

        Examples:
            >>> extensions = FileClassifier.get_analyzable_extensions()
            >>> ".py" in extensions
            True
            >>> ".md" in extensions
            False
        """
        return {
            ext
            for ext, file_type in cls.EXTENSION_MAP.items()
            if file_type.is_analyzable
        }
