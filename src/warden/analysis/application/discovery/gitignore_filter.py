"""
Gitignore filter implementation.

Parses .gitignore files and filters file paths accordingly.
"""

import re
from pathlib import Path
from typing import List, Set, Pattern


class GitignoreFilter:
    """
    Filters files based on .gitignore patterns.

    Implements gitignore pattern matching rules.
    """

    def __init__(self, root_path: Path) -> None:
        """
        Initialize the gitignore filter.

        Args:
            root_path: Root directory of the project
        """
        self.root_path = root_path
        self.patterns: List[Pattern[str]] = []
        self.raw_patterns: List[str] = []

        # Default patterns to always ignore
        self._add_default_patterns()

    def _add_default_patterns(self) -> None:
        """Add default ignore patterns (common files/dirs to skip)."""
        default_patterns = [
            # Version control
            ".git/",
            ".svn/",
            ".hg/",
            # Dependencies
            "node_modules/",
            "venv/",
            ".venv/",
            "env/",
            ".env/",
            "virtualenv/",
            "__pycache__/",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            # Build outputs
            "dist/",
            "build/",
            "*.egg-info/",
            ".eggs/",
            "target/",
            "out/",
            # IDE
            ".idea/",
            ".vscode/",
            ".vs/",
            "*.swp",
            "*.swo",
            "*~",
            # OS
            ".DS_Store",
            "Thumbs.db",
            # Coverage
            ".coverage",
            "htmlcov/",
            "coverage/",
            ".pytest_cache/",
            ".mypy_cache/",
            ".ruff_cache/",
        ]

        for pattern in default_patterns:
            self.add_pattern(pattern)

    def load_gitignore(self, gitignore_path: Path) -> None:
        """
        Load patterns from a .gitignore file.

        Args:
            gitignore_path: Path to the .gitignore file

        Examples:
            >>> filter = GitignoreFilter(Path("/project"))
            >>> filter.load_gitignore(Path("/project/.gitignore"))
        """
        if not gitignore_path.exists():
            return

        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()

                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue

                    self.add_pattern(line)
        except (IOError, UnicodeDecodeError):
            # If we can't read the file, just skip it
            pass

    def add_pattern(self, pattern: str) -> None:
        """
        Add a gitignore pattern.

        Args:
            pattern: Gitignore pattern string

        Examples:
            >>> filter = GitignoreFilter(Path("/project"))
            >>> filter.add_pattern("*.pyc")
            >>> filter.add_pattern("node_modules/")
        """
        if not pattern or pattern.startswith("#"):
            return

        self.raw_patterns.append(pattern)

        # Convert gitignore pattern to regex
        regex_pattern = self._pattern_to_regex(pattern)
        if regex_pattern:
            self.patterns.append(re.compile(regex_pattern))

    def _pattern_to_regex(self, pattern: str) -> str:
        """
        Convert a gitignore pattern to a regex pattern.

        Args:
            pattern: Gitignore pattern

        Returns:
            Regex pattern string

        Gitignore pattern rules:
        - * matches anything except /
        - ** matches anything including /
        - ? matches any one character
        - / at end means directory only
        - / at start means from root
        """
        # Handle negation (we'll skip negations for simplicity)
        if pattern.startswith("!"):
            return ""

        # Strip leading/trailing slashes for processing
        is_directory = pattern.endswith("/")
        pattern = pattern.strip("/")

        # Escape special regex characters except * and ?
        regex = re.escape(pattern)

        # Replace gitignore wildcards with regex equivalents
        regex = regex.replace(r"\*\*", "DOUBLESTAR")
        regex = regex.replace(r"\*", "[^/]*")
        regex = regex.replace("DOUBLESTAR", ".*")
        regex = regex.replace(r"\?", ".")

        # If pattern is for directory only, match directory and its contents
        if is_directory:
            regex = f"(^|/){regex}(/|$)"
        else:
            # Match pattern anywhere in path
            regex = f"(^|/){regex}(/|$)"

        return regex

    def should_ignore(self, file_path: Path) -> bool:
        """
        Check if a file should be ignored based on patterns.

        Args:
            file_path: File path to check (can be absolute or relative)

        Returns:
            True if file should be ignored, False otherwise

        Examples:
            >>> filter = GitignoreFilter(Path("/project"))
            >>> filter.should_ignore(Path("/project/node_modules/lib.js"))
            True
            >>> filter.should_ignore(Path("/project/src/main.py"))
            False
        """
        # Convert to relative path from root
        try:
            if file_path.is_absolute():
                relative_path = file_path.relative_to(self.root_path)
            else:
                relative_path = file_path
        except ValueError:
            # Path is not relative to root, don't ignore
            return False

        # Convert to string with forward slashes (gitignore uses /)
        path_str = str(relative_path).replace("\\", "/")

        # Check against all patterns
        for pattern in self.patterns:
            if pattern.search(path_str):
                return True

        return False

    def filter_files(self, file_paths: List[Path]) -> List[Path]:
        """
        Filter a list of file paths, removing ignored files.

        Args:
            file_paths: List of file paths to filter

        Returns:
            List of file paths that should not be ignored

        Examples:
            >>> filter = GitignoreFilter(Path("/project"))
            >>> paths = [Path("src/main.py"), Path("node_modules/lib.js")]
            >>> filtered = filter.filter_files(paths)
            >>> len(filtered)
            1
        """
        return [path for path in file_paths if not self.should_ignore(path)]

    def get_patterns(self) -> List[str]:
        """
        Get all loaded patterns.

        Returns:
            List of raw pattern strings

        Examples:
            >>> filter = GitignoreFilter(Path("/project"))
            >>> patterns = filter.get_patterns()
            >>> "node_modules/" in patterns
            True
        """
        return self.raw_patterns.copy()


def create_gitignore_filter(project_root: Path) -> GitignoreFilter:
    """
    Create a gitignore filter and load project's .gitignore.

    Args:
        project_root: Root directory of the project

    Returns:
        Configured GitignoreFilter instance

    Examples:
        >>> filter = create_gitignore_filter(Path("/my/project"))
        >>> filter.should_ignore(Path("/my/project/node_modules/lib.js"))
        True
    """
    git_filter = GitignoreFilter(project_root)

    # Load .gitignore from project root
    gitignore_path = project_root / ".gitignore"
    git_filter.load_gitignore(gitignore_path)

    return git_filter
