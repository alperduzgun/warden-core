"""
Tests for suppression models.

Tests coverage:
- SuppressionType enum
- SuppressionEntry functionality
- SuppressionConfig functionality
- Panel JSON serialization/deserialization
"""

import pytest
from warden.suppression.models import (
    SuppressionType,
    SuppressionEntry,
    SuppressionConfig,
)


class TestSuppressionType:
    """Test SuppressionType enum."""

    def test_enum_values(self) -> None:
        """Test enum values are correct."""
        assert SuppressionType.INLINE.value == 0
        assert SuppressionType.CONFIG.value == 1
        assert SuppressionType.GLOBAL.value == 2

    def test_enum_names(self) -> None:
        """Test enum names are correct."""
        assert SuppressionType.INLINE.name == 'INLINE'
        assert SuppressionType.CONFIG.name == 'CONFIG'
        assert SuppressionType.GLOBAL.name == 'GLOBAL'


class TestSuppressionEntry:
    """Test SuppressionEntry dataclass."""

    def test_create_basic_entry(self) -> None:
        """Test creating basic suppression entry."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.INLINE,
            rules=['magic-number'],
        )
        assert entry.id == 'test-1'
        assert entry.type == SuppressionType.INLINE
        assert entry.rules == ['magic-number']
        assert entry.enabled is True

    def test_create_with_optional_fields(self) -> None:
        """Test creating entry with optional fields."""
        entry = SuppressionEntry(
            id='test-2',
            type=SuppressionType.CONFIG,
            rules=['sql-injection'],
            file='legacy/*.py',
            line=42,
            reason='Legacy code',
            enabled=False,
        )
        assert entry.file == 'legacy/*.py'
        assert entry.line == 42
        assert entry.reason == 'Legacy code'
        assert entry.enabled is False

    def test_matches_rule_specific(self) -> None:
        """Test matching specific rule."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.INLINE,
            rules=['magic-number', 'unused-import'],
        )
        assert entry.matches_rule('magic-number') is True
        assert entry.matches_rule('unused-import') is True
        assert entry.matches_rule('sql-injection') is False

    def test_matches_rule_all(self) -> None:
        """Test matching all rules (empty rules list)."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.INLINE,
            rules=[],  # Empty = match all
        )
        assert entry.matches_rule('magic-number') is True
        assert entry.matches_rule('sql-injection') is True
        assert entry.matches_rule('any-rule') is True

    def test_matches_rule_disabled(self) -> None:
        """Test disabled entry doesn't match."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.INLINE,
            rules=['magic-number'],
            enabled=False,
        )
        assert entry.matches_rule('magic-number') is False

    def test_matches_location_exact_file(self) -> None:
        """Test matching exact file path."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.CONFIG,
            rules=[],
            file='src/app.py',
        )
        assert entry.matches_location(file_path='src/app.py') is True
        assert entry.matches_location(file_path='src/main.py') is False

    def test_matches_location_glob_pattern(self) -> None:
        """Test matching glob pattern."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.CONFIG,
            rules=[],
            file='test_*.py',
        )
        assert entry.matches_location(file_path='test_app.py') is True
        assert entry.matches_location(file_path='test_main.py') is True
        assert entry.matches_location(file_path='app_test.py') is False

    def test_matches_location_line_number(self) -> None:
        """Test matching line number."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.INLINE,
            rules=[],
            line=42,
        )
        assert entry.matches_location(line_number=42) is True
        assert entry.matches_location(line_number=43) is False

    def test_matches_location_no_constraints(self) -> None:
        """Test matching with no location constraints."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.GLOBAL,
            rules=[],
        )
        assert entry.matches_location() is True
        assert entry.matches_location(file_path='any.py') is True
        assert entry.matches_location(line_number=42) is True

    def test_to_json(self) -> None:
        """Test Panel JSON serialization."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.CONFIG,
            rules=['sql-injection'],
            file='legacy/*.py',
            line=42,
            reason='Legacy code',
        )
        json_data = entry.to_json()

        # Check camelCase conversion
        assert json_data['id'] == 'test-1'
        assert json_data['type'] == 1  # CONFIG = 1
        assert json_data['rules'] == ['sql-injection']
        assert json_data['file'] == 'legacy/*.py'
        assert json_data['line'] == 42
        assert json_data['reason'] == 'Legacy code'
        assert json_data['enabled'] is True


class TestSuppressionConfig:
    """Test SuppressionConfig dataclass."""

    def test_create_empty_config(self) -> None:
        """Test creating empty configuration."""
        config = SuppressionConfig()
        assert config.enabled is True
        assert config.entries == []
        assert config.global_rules == []
        assert config.ignored_files == []

    def test_create_with_entries(self) -> None:
        """Test creating configuration with entries."""
        entry1 = SuppressionEntry(
            id='entry-1',
            type=SuppressionType.CONFIG,
            rules=['magic-number'],
        )
        entry2 = SuppressionEntry(
            id='entry-2',
            type=SuppressionType.CONFIG,
            rules=['sql-injection'],
        )
        config = SuppressionConfig(
            enabled=True,
            entries=[entry1, entry2],
            global_rules=['unused-import'],
            ignored_files=['test_*.py'],
        )
        assert len(config.entries) == 2
        assert config.global_rules == ['unused-import']
        assert config.ignored_files == ['test_*.py']

    def test_add_entry(self) -> None:
        """Test adding entry to configuration."""
        config = SuppressionConfig()
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.CONFIG,
            rules=['magic-number'],
        )
        config.add_entry(entry)
        assert len(config.entries) == 1
        assert config.entries[0].id == 'test-1'

    def test_remove_entry(self) -> None:
        """Test removing entry from configuration."""
        entry1 = SuppressionEntry(id='entry-1', type=SuppressionType.CONFIG)
        entry2 = SuppressionEntry(id='entry-2', type=SuppressionType.CONFIG)
        config = SuppressionConfig(entries=[entry1, entry2])

        assert config.remove_entry('entry-1') is True
        assert len(config.entries) == 1
        assert config.entries[0].id == 'entry-2'

        assert config.remove_entry('nonexistent') is False

    def test_get_entry(self) -> None:
        """Test getting entry by ID."""
        entry = SuppressionEntry(id='test-1', type=SuppressionType.CONFIG)
        config = SuppressionConfig(entries=[entry])

        found = config.get_entry('test-1')
        assert found is not None
        assert found.id == 'test-1'

        not_found = config.get_entry('nonexistent')
        assert not_found is None

    def test_is_file_ignored(self) -> None:
        """Test checking if file is ignored."""
        config = SuppressionConfig(
            ignored_files=['test_*.py', 'migrations/*.py']
        )
        assert config.is_file_ignored('test_app.py') is True
        assert config.is_file_ignored('test_main.py') is True
        assert config.is_file_ignored('migrations/001_init.py') is True
        assert config.is_file_ignored('src/app.py') is False

    def test_is_file_ignored_disabled(self) -> None:
        """Test file ignorance when config is disabled."""
        config = SuppressionConfig(
            enabled=False,
            ignored_files=['test_*.py'],
        )
        assert config.is_file_ignored('test_app.py') is False

    def test_is_rule_globally_suppressed(self) -> None:
        """Test checking if rule is globally suppressed."""
        config = SuppressionConfig(
            global_rules=['unused-import', 'magic-number']
        )
        assert config.is_rule_globally_suppressed('unused-import') is True
        assert config.is_rule_globally_suppressed('magic-number') is True
        assert config.is_rule_globally_suppressed('sql-injection') is False

    def test_is_rule_globally_suppressed_disabled(self) -> None:
        """Test global suppression when config is disabled."""
        config = SuppressionConfig(
            enabled=False,
            global_rules=['unused-import'],
        )
        assert config.is_rule_globally_suppressed('unused-import') is False

    def test_to_json(self) -> None:
        """Test Panel JSON serialization."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.CONFIG,
            rules=['magic-number'],
        )
        config = SuppressionConfig(
            enabled=True,
            entries=[entry],
            global_rules=['unused-import'],
            ignored_files=['test_*.py'],
        )
        json_data = config.to_json()

        # Check camelCase conversion
        assert json_data['enabled'] is True
        assert json_data['globalRules'] == ['unused-import']
        assert json_data['ignoredFiles'] == ['test_*.py']
        assert len(json_data['entries']) == 1
        assert json_data['entries'][0]['id'] == 'test-1'
