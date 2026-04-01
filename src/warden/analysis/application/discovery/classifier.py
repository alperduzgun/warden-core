"""
File type classifier.

Detects file types based on file extensions.
"""

from pathlib import Path

from warden.analysis.application.discovery.models import FileType


class FileClassifier:
    """
    Classifies files by their extension.

    Maps file extensions to FileType enum values.
    """

    # Common non-code files to skip (extension-based fast path).
    # When the extension is not in this set *and* not a known code extension,
    # should_skip() falls back to a 512-byte content probe (null-byte check).
    SKIP_EXTENSIONS: set[str] = {
        # Images
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".webp",
        ".bmp",
        ".tiff",
        ".tif",
        ".psd",
        ".ai",
        ".sketch",
        ".fig",
        ".cur",
        ".heic",
        ".heif",
        ".raw",
        ".cr2",
        ".nef",
        ".dng",
        # Videos
        ".mp4",
        ".avi",
        ".mov",
        ".wmv",
        ".mkv",
        ".webm",
        ".m4v",
        ".flv",
        ".f4v",
        ".3gp",
        # Audio
        ".mp3",
        ".wav",
        ".ogg",
        ".flac",
        ".aac",
        ".m4a",
        ".wma",
        ".aiff",
        # Archives / compressed
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".rar",
        ".xz",
        ".zst",
        ".cab",
        ".lz4",
        ".br",
        ".zlib",
        ".lzma",
        ".lzo",
        # Compiled / bytecode
        ".pyc",
        ".pyo",
        ".pyd",
        ".class",
        ".jar",
        ".war",
        ".ear",
        ".wasm",
        ".o",
        ".obj",
        ".a",
        ".lib",
        ".pdb",
        # Native binaries / executables
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".out",
        ".elf",
        # Disk / package images
        ".iso",
        ".dmg",
        ".img",
        ".pkg",
        ".deb",
        ".rpm",
        ".msi",
        ".apk",
        ".ipa",
        ".appimage",
        # Databases
        ".db",
        ".sqlite",
        ".sqlite3",
        ".mdb",
        ".accdb",
        ".dat",
        ".dump",
        # Documents (binary formats)
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".odt",
        ".ods",
        ".odp",
        ".key",
        ".numbers",
        ".pages",
        # Fonts
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        ".eot",
        # Other
        ".lock",
        ".log",
        ".tmp",
        ".cache",
    }

    # 512-byte content probe: if first chunk contains a null byte the file is
    # treated as binary regardless of extension.  Only runs for files whose
    # extension is neither in SKIP_EXTENSIONS nor a recognised code extension,
    # keeping the overhead negligible on typical codebases.
    _BINARY_PROBE_BYTES: int = 512

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

        Decision order:
        1. Extension in SKIP_EXTENSIONS → skip immediately (fast path).
        2. Extension is a known code extension → keep (no I/O needed).
        3. Otherwise probe the first _BINARY_PROBE_BYTES bytes: if a null
           byte is present the file is binary and should be skipped.

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

        # Fast path: known binary extension.
        if extension in cls.SKIP_EXTENSIONS:
            return True

        # Fast path: known code extension — no content probe needed.
        from warden.shared.utils.language_utils import get_supported_extensions

        if extension in get_supported_extensions():
            return False

        # Slow path: unknown extension — probe for null bytes.
        try:
            with open(file_path, "rb") as fh:
                probe = fh.read(cls._BINARY_PROBE_BYTES)
            if b"\x00" in probe:
                return True
        except OSError:
            pass

        return False

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
    def get_supported_extensions(cls) -> set[str]:
        """Get all supported file extensions."""
        from warden.shared.utils.language_utils import get_supported_extensions

        return set(get_supported_extensions())

    @classmethod
    def get_analyzable_extensions(cls) -> set[str]:
        """Get file extensions that can be analyzed."""
        from warden.shared.utils.language_utils import get_code_extensions

        return get_code_extensions()
