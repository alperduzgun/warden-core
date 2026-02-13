"""
Suppression models for Panel compatibility.

These models define suppression entries and configuration:
- SuppressionType: Type of suppression (inline, config, global)
- SuppressionEntry: Individual suppression rule
- SuppressionConfig: Configuration for suppressions

Panel JSON format: camelCase
Python internal format: snake_case
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from warden.shared.domain.base_model import BaseDomainModel


class SuppressionType(Enum):
    """
    Type of suppression.

    Panel TypeScript equivalent:
    ```typescript
    enum SuppressionType {
      INLINE = 0,
      CONFIG = 1,
      GLOBAL = 2
    }
    ```
    """

    INLINE = 0  # Inline comment (# warden-ignore)
    CONFIG = 1  # Configuration file (.warden/suppressions.yaml)
    GLOBAL = 2  # Global suppression (all instances)


class SuppressionEntry(BaseDomainModel):
    """
    Individual suppression entry.

    Panel TypeScript equivalent:
    ```typescript
    export interface SuppressionEntry {
      id: string
      type: SuppressionType
      rules: string[]  // Empty array = suppress all rules
      file?: string  // Optional file path pattern
      line?: number  // Optional line number
      reason?: string  // Why this is suppressed
      enabled: boolean
    }
    ```

    Examples:
    - Inline: SuppressionEntry(id="inline-1", type=INLINE, rules=["magic-number"], line=42)
    - Config: SuppressionEntry(id="config-1", type=CONFIG, rules=[], file="test_*.py")
    - Global: SuppressionEntry(id="global-1", type=GLOBAL, rules=["unused-import"])
    """

    id: str
    type: SuppressionType
    rules: list[str] = []  # Empty = suppress all
    file: str | None = None  # File path pattern (glob supported)
    line: int | None = None  # Line number (for inline suppressions)
    reason: str | None = None  # Justification for suppression
    enabled: bool = True

    def matches_rule(self, rule: str) -> bool:
        """
        Check if this suppression applies to a specific rule.

        Args:
            rule: Rule name to check

        Returns:
            True if suppression applies to this rule, False otherwise
        """
        if not self.enabled:
            return False

        # Empty rules list means suppress all
        if not self.rules:
            return True

        # Check if rule is in the list
        return rule in self.rules

    def matches_location(self, file_path: str | None = None,
                        line_number: int | None = None) -> bool:
        """
        Check if this suppression applies to a specific location.

        Args:
            file_path: File path to check
            line_number: Line number to check

        Returns:
            True if suppression applies to this location, False otherwise
        """
        if not self.enabled:
            return False

        # Check file pattern if specified
        if self.file and file_path:
            # Simple pattern matching (exact match or glob)
            if self.file == file_path:
                return True
            if '*' in self.file or '?' in self.file:
                import fnmatch
                return bool(fnmatch.fnmatch(file_path, self.file))

        # Check line number if specified
        if self.line is not None and line_number is not None:
            return self.line == line_number

        # If no location constraints, it matches
        return bool(self.file is None and self.line is None)

    def to_json(self) -> dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        data = super().to_json()
        # Enum is automatically converted to int by BaseDomainModel
        return data


class SuppressionConfig(BaseDomainModel):
    """
    Configuration for suppressions.

    Panel TypeScript equivalent:
    ```typescript
    export interface SuppressionConfig {
      enabled: boolean
      entries: SuppressionEntry[]
      globalRules: string[]  // Rules to suppress globally
      ignoredFiles: string[]  // File patterns to ignore entirely
    }
    ```

    Loaded from .warden/suppressions.yaml:
    ```yaml
    enabled: true
    globalRules:
      - unused-import
      - magic-number
    ignoredFiles:
      - test_*.py
      - migrations/*.py
    entries:
      - id: suppress-1
        type: config
        rules: [sql-injection]
        file: legacy/*.py
        reason: Legacy code, to be refactored
    ```
    """

    enabled: bool = True
    entries: list[SuppressionEntry] = []
    global_rules: list[str] = []
    ignored_files: list[str] = []

    def to_json(self) -> dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        data = super().to_json()
        # Convert entries
        data['entries'] = [e.to_json() for e in self.entries]
        return data

    def add_entry(self, entry: SuppressionEntry) -> None:
        """
        Add a suppression entry.

        Args:
            entry: Suppression entry to add
        """
        self.entries.append(entry)

    def remove_entry(self, entry_id: str) -> bool:
        """
        Remove a suppression entry by ID.

        Args:
            entry_id: ID of entry to remove

        Returns:
            True if entry was removed, False if not found
        """
        for i, entry in enumerate(self.entries):
            if entry.id == entry_id:
                self.entries.pop(i)
                return True
        return False

    def get_entry(self, entry_id: str) -> SuppressionEntry | None:
        """
        Get a suppression entry by ID.

        Args:
            entry_id: ID of entry to get

        Returns:
            SuppressionEntry if found, None otherwise
        """
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None

    def is_file_ignored(self, file_path: str) -> bool:
        """
        Check if a file should be completely ignored.

        Args:
            file_path: File path to check

        Returns:
            True if file is ignored, False otherwise
        """
        if not self.enabled:
            return False

        import fnmatch
        return any(fnmatch.fnmatch(file_path, pattern) for pattern in self.ignored_files)

    def is_rule_globally_suppressed(self, rule: str) -> bool:
        """
        Check if a rule is globally suppressed.

        Args:
            rule: Rule name to check

        Returns:
            True if rule is globally suppressed, False otherwise
        """
        if not self.enabled:
            return False

        return rule in self.global_rules
