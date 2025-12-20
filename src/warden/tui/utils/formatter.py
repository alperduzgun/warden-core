"""Visual formatting utilities for TUI display."""

from typing import List


class TreeFormatter:
    """
    Format output with visual tree/hierarchy structure.

    Uses Claude Code-style formatting:
    > parent
      ⎿ child
    """

    # Tree symbols
    ARROW = ">"
    BRANCH = "⎿"
    INDENT = "  "

    @staticmethod
    def header(text: str) -> str:
        """
        Create a header line.

        Args:
            text: Header text

        Returns:
            Formatted header: "> text"
        """
        return f"{TreeFormatter.ARROW} {text}"

    @staticmethod
    def item(text: str, level: int = 1) -> str:
        """
        Create an indented item.

        Args:
            text: Item text
            level: Indentation level (1 = one indent)

        Returns:
            Formatted item: "  ⎿ text"
        """
        indent = TreeFormatter.INDENT * level
        return f"{indent}{TreeFormatter.BRANCH} {text}"

    @staticmethod
    def tree(header: str, items: List[str], sub_items: dict = None) -> str:
        """
        Create a full tree structure.

        Args:
            header: Tree header text
            items: List of first-level items
            sub_items: Optional dict mapping item indices to sub-item lists

        Returns:
            Complete formatted tree as string
        """
        lines = [TreeFormatter.header(header)]

        for idx, item in enumerate(items):
            lines.append(TreeFormatter.item(item, level=1))

            # Add sub-items if provided
            if sub_items and idx in sub_items:
                for sub_item in sub_items[idx]:
                    lines.append(TreeFormatter.item(sub_item, level=2))

        return "\n".join(lines)


class ProgressBar:
    """Simple progress bar formatter."""

    @staticmethod
    def create(current: int, total: int, width: int = 20) -> str:
        """
        Create a progress bar.

        Args:
            current: Current progress
            total: Total items
            width: Bar width in characters

        Returns:
            Progress bar string: [████████░░] 8/10 (80%)
        """
        if total == 0:
            percentage = 0
        else:
            percentage = int((current / total) * 100)

        filled = int((current / total) * width) if total > 0 else 0
        empty = width - filled

        bar = "█" * filled + "░" * empty
        return f"[{bar}] {current}/{total} ({percentage}%)"
