"""@ file injection command handler."""

import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from .types import (
    CommandActionReturn,
    CommandContext,
    FileContent,
    SubmitPromptReturn,
    TextContent,
)

if TYPE_CHECKING:
    pass


# Default patterns to ignore (similar to .gitignore)
DEFAULT_IGNORE_PATTERNS = [
    ".git/*",
    ".git/**/*",
    "node_modules/*",
    "node_modules/**/*",
    ".venv/*",
    ".venv/**/*",
    "venv/*",
    "venv/**/*",
    "__pycache__/*",
    "__pycache__/**/*",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".Python",
    "build/*",
    "build/**/*",
    "dist/*",
    "dist/**/*",
    "*.egg-info/*",
    "*.egg-info/**/*",
    ".mypy_cache/*",
    ".mypy_cache/**/*",
    ".pytest_cache/*",
    ".pytest_cache/**/*",
    ".ruff_cache/*",
    ".ruff_cache/**/*",
    "htmlcov/*",
    "htmlcov/**/*",
    ".coverage",
    "*.log",
]


class AtCommandHandler:
    """Handler for @ file injection commands."""

    def __init__(self, project_root: Path):
        """
        Initialize the handler.

        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root
        self.ignore_patterns = self._load_ignore_patterns()

    def _load_ignore_patterns(self) -> list[str]:
        """
        Load ignore patterns from .gitignore and .wardenignore.

        Returns:
            List of ignore patterns
        """
        patterns = DEFAULT_IGNORE_PATTERNS.copy()

        # Load .gitignore
        gitignore_path = self.project_root / ".gitignore"
        if gitignore_path.exists():
            try:
                with open(gitignore_path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            patterns.append(line)
            except Exception:
                pass  # Ignore errors

        # Load .wardenignore
        wardenignore_path = self.project_root / ".wardenignore"
        if wardenignore_path.exists():
            try:
                with open(wardenignore_path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            patterns.append(line)
            except Exception:
                pass  # Ignore errors

        return patterns

    def _is_ignored(self, path: Path) -> bool:
        """
        Check if a path should be ignored.

        Args:
            path: Path to check

        Returns:
            True if the path should be ignored
        """
        relative_path = path.relative_to(self.project_root)
        path_str = str(relative_path)

        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(path_str, pattern):
                return True
            # Also check directory patterns
            if fnmatch.fnmatch(path_str + "/*", pattern):
                return True

        return False

    def _detect_language(self, path: Path) -> str | None:
        """
        Detect programming language from file extension.

        Args:
            path: File path

        Returns:
            Language identifier or None
        """
        extension_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".jsx": "jsx",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".hpp": "cpp",
            ".cs": "csharp",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".sh": "bash",
            ".bash": "bash",
            ".zsh": "zsh",
            ".fish": "fish",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".toml": "toml",
            ".xml": "xml",
            ".html": "html",
            ".css": "css",
            ".scss": "scss",
            ".sass": "sass",
            ".md": "markdown",
            ".rst": "rst",
            ".txt": "text",
            ".sql": "sql",
            ".tf": "terraform",
            ".dockerfile": "dockerfile",
        }

        suffix = path.suffix.lower()
        return extension_map.get(suffix)

    async def read_file(self, path: Path) -> FileContent | None:
        """
        Read a single file.

        Args:
            path: File path to read

        Returns:
            FileContent object or None if file cannot be read
        """
        if not path.exists():
            return None

        if not path.is_file():
            return None

        if self._is_ignored(path):
            return None

        try:
            content = path.read_text(encoding="utf-8")
            language = self._detect_language(path)
            return FileContent(path=path, content=content, language=language)
        except UnicodeDecodeError:
            # Skip binary files
            return None
        except Exception:
            # Skip files that can't be read
            return None

    async def read_directory(
        self, directory: Path, max_files: int = 100
    ) -> list[FileContent]:
        """
        Recursively read all files in a directory.

        Args:
            directory: Directory path to read
            max_files: Maximum number of files to read

        Returns:
            List of FileContent objects
        """
        if not directory.exists() or not directory.is_dir():
            return []

        files: list[FileContent] = []
        count = 0

        for item in directory.rglob("*"):
            if count >= max_files:
                break

            if item.is_file() and not self._is_ignored(item):
                file_content = await self.read_file(item)
                if file_content:
                    files.append(file_content)
                    count += 1

        return files

    async def handle_at_command(
        self, path_str: str, context: CommandContext
    ) -> CommandActionReturn:
        """
        Handle @ file injection command.

        Args:
            path_str: Path string (relative or absolute)
            context: Command execution context

        Returns:
            CommandActionReturn with file content
        """
        # Resolve path
        path = Path(path_str)
        if not path.is_absolute():
            path = self.project_root / path

        # Normalize path
        try:
            path = path.resolve()
        except Exception:
            context.add_message(
                f"Invalid path: `{path_str}`", "error-message", True
            )
            return None

        # Check if path is within project
        try:
            path.relative_to(self.project_root)
        except ValueError:
            context.add_message(
                f"Path is outside project root: `{path_str}`", "error-message", True
            )
            return None

        content_list: list[FileContent | TextContent] = []

        if path.is_file():
            # Read single file
            file_content = await self.read_file(path)
            if file_content:
                content_list.append(file_content)
            else:
                context.add_message(
                    f"Could not read file: `{path_str}`", "error-message", True
                )
                return None
        elif path.is_dir():
            # Read directory
            files = await self.read_directory(path)
            if files:
                content_list.extend(files)
                context.add_message(
                    f"Loaded {len(files)} files from `{path_str}`",
                    "info-message",
                    True,
                )
            else:
                context.add_message(
                    f"No readable files found in: `{path_str}`", "error-message", True
                )
                return None
        else:
            context.add_message(
                f"Path does not exist: `{path_str}`", "error-message", True
            )
            return None

        return SubmitPromptReturn(type="submit_prompt", content=content_list)


def parse_at_command(input_text: str) -> str | None:
    """
    Parse @ command from input text.

    Args:
        input_text: Input text to parse

    Returns:
        Path string if @ command found, None otherwise
    """
    input_text = input_text.strip()
    if input_text.startswith("@"):
        return input_text[1:].strip()
    return None
