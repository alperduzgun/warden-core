"""
Code display widget with syntax highlighting

Provides a widget for displaying code with proper syntax highlighting.
"""

from textual.widgets import Static
from rich.syntax import Syntax
from pathlib import Path


class CodeWidget(Static):
    """
    Widget for displaying code with syntax highlighting

    Uses Rich's Syntax for automatic language detection and highlighting.
    """

    def __init__(
        self,
        code: str,
        language: str = "python",
        theme: str = "monokai",
        line_numbers: bool = True,
        **kwargs
    ):
        """
        Initialize code widget

        Args:
            code: Code to display
            language: Programming language (auto-detected from file extension)
            theme: Color theme for syntax highlighting
            line_numbers: Whether to show line numbers
        """
        # Create syntax-highlighted renderable
        syntax = Syntax(
            code,
            language,
            theme=theme,
            line_numbers=line_numbers,
            word_wrap=False,
            background_color="default"
        )

        super().__init__(syntax, **kwargs)

    @classmethod
    def from_file(cls, file_path: Path, **kwargs):
        """
        Create CodeWidget from a file

        Args:
            file_path: Path to file
            **kwargs: Additional arguments for CodeWidget

        Returns:
            CodeWidget instance
        """
        # Read file
        with open(file_path) as f:
            code = f.read()

        # Detect language from file extension
        language = cls._detect_language(file_path)

        return cls(code, language=language, **kwargs)

    @staticmethod
    def _detect_language(file_path: Path) -> str:
        """
        Detect programming language from file extension

        Args:
            file_path: Path to file

        Returns:
            Language identifier for syntax highlighting
        """
        extension_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "jsx",
            ".tsx": "tsx",
            ".go": "go",
            ".rs": "rust",
            ".c": "c",
            ".cpp": "cpp",
            ".cs": "csharp",
            ".java": "java",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
            ".dart": "dart",
            ".sh": "bash",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".toml": "toml",
            ".xml": "xml",
            ".html": "html",
            ".css": "css",
            ".sql": "sql",
            ".md": "markdown",
        }

        ext = file_path.suffix.lower()
        return extension_map.get(ext, "text")


class CodeBlockWidget(Static):
    """
    Widget for inline code blocks in markdown-style messages

    For use in chat messages with code snippets.
    """

    DEFAULT_CSS = """
    CodeBlockWidget {
        background: $boost;
        border: solid $primary;
        padding: 1;
        margin: 1 0;
    }
    """

    def __init__(self, code: str, language: str = "python", **kwargs):
        """
        Initialize code block widget

        Args:
            code: Code snippet
            language: Programming language
        """
        syntax = Syntax(
            code,
            language,
            theme="monokai",
            line_numbers=False,
            word_wrap=True,
            background_color="default"
        )

        super().__init__(syntax, **kwargs)
