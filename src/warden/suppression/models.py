"""
Suppression models for Panel compatibility.

These models define suppression entries and configuration:
- SuppressionType: Type of suppression (inline, config, global)
- SuppressionEntry: Individual suppression rule
- SuppressionConfig: Configuration for suppressions

Panel JSON format: camelCase
Python internal format: snake_case
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional

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


@dataclass
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
    rules: List[str] = field(default_factory=list)  # Empty = suppress all
    file: Optional[str] = None  # File path pattern (glob supported)
    line: Optional[int] = None  # Line number (for inline suppressions)
    reason: Optional[str] = None  # Justification for suppression
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

    def matches_location(self, file_path: Optional[str] = None,
                        line_number: Optional[int] = None) -> bool:
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
            # TODO: Add glob pattern matching if needed
            if '*' in self.file or '?' in self.file:
                import fnmatch
                if fnmatch.fnmatch(file_path, self.file):
                    return True
                return False

        # Check line number if specified
        if self.line is not None and line_number is not None:
            return self.line == line_number

        # If no location constraints, it matches
        if self.file is None and self.line is None:
            return True

        return False

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        data = super().to_json()
        # Enum is automatically converted to int by BaseDomainModel
        return data


@dataclass
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
    entries: List[SuppressionEntry] = field(default_factory=list)
    global_rules: List[str] = field(default_factory=list)
    ignored_files: List[str] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
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

    def get_entry(self, entry_id: str) -> Optional[SuppressionEntry]:
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
        for pattern in self.ignored_files:
            if fnmatch.fnmatch(file_path, pattern):
                return True
        return False

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
