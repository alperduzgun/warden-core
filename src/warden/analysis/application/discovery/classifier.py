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
        """
        from warden.shared.utils.language_utils import get_language_from_path
        lang = get_language_from_path(file_path)
        try:
            return FileType(lang.value)
        except ValueError:
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
        """Get all supported file extensions."""
        from warden.shared.utils.language_utils import get_supported_extensions
        return set(get_supported_extensions())

    @classmethod
    def get_analyzable_extensions(cls) -> Set[str]:
        """Get file extensions that can be analyzed."""
        from warden.shared.utils.language_utils import get_code_extensions
        return get_code_extensions()
