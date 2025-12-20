"""
Tests for suppression configuration loader.

Tests coverage:
- Loading configuration from YAML
- Saving configuration to YAML
- Creating default configuration
- Error handling for malformed YAML
- camelCase ↔ snake_case conversion
"""

import pytest
import tempfile
from pathlib import Path

from warden.suppression.config_loader import (
    load_suppression_config,
    save_suppression_config,
    create_default_config,
)
from warden.suppression.models import (
    SuppressionConfig,
    SuppressionEntry,
    SuppressionType,
)


class TestLoadSuppressionConfig:
    """Test loading suppression configuration."""

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        """Test loading when file doesn't exist returns default config."""
        config_path = tmp_path / "suppressions.yaml"
        config = load_suppression_config(config_path=config_path)

        assert isinstance(config, SuppressionConfig)
        assert config.enabled is True
        assert config.entries == []
        assert config.global_rules == []
        assert config.ignored_files == []

    def test_load_empty_file(self, tmp_path: Path) -> None:
        """Test loading empty YAML file."""
        config_path = tmp_path / "suppressions.yaml"
        config_path.write_text("")

        config = load_suppression_config(config_path=config_path)
        assert isinstance(config, SuppressionConfig)
        assert config.enabled is True

    def test_load_basic_config(self, tmp_path: Path) -> None:
        """Test loading basic configuration."""
        config_path = tmp_path / "suppressions.yaml"
        config_path.write_text("""
enabled: true
globalRules:
  - unused-import
  - magic-number
ignoredFiles:
  - test_*.py
  - migrations/*.py
""")

        config = load_suppression_config(config_path=config_path)
        assert config.enabled is True
        assert config.global_rules == ['unused-import', 'magic-number']
        assert config.ignored_files == ['test_*.py', 'migrations/*.py']

    def test_load_with_entries(self, tmp_path: Path) -> None:
        """Test loading configuration with entries."""
        config_path = tmp_path / "suppressions.yaml"
        config_path.write_text("""
enabled: true
entries:
  - id: suppress-1
    type: config
    rules:
      - sql-injection
    file: legacy/*.py
    reason: Legacy code to be refactored
  - id: suppress-2
    type: global
    rules: []
    reason: Suppress all in generated code
    enabled: false
""")

        config = load_suppression_config(config_path=config_path)
        assert len(config.entries) == 2

        # First entry
        entry1 = config.entries[0]
        assert entry1.id == 'suppress-1'
        assert entry1.type == SuppressionType.CONFIG
        assert entry1.rules == ['sql-injection']
        assert entry1.file == 'legacy/*.py'
        assert entry1.reason == 'Legacy code to be refactored'
        assert entry1.enabled is True

        # Second entry
        entry2 = config.entries[1]
        assert entry2.id == 'suppress-2'
        assert entry2.type == SuppressionType.GLOBAL
        assert entry2.rules == []
        assert entry2.enabled is False

    def test_load_inline_type(self, tmp_path: Path) -> None:
        """Test loading inline suppression type."""
        config_path = tmp_path / "suppressions.yaml"
        config_path.write_text("""
entries:
  - id: inline-1
    type: inline
    rules: [magic-number]
    line: 42
""")

        config = load_suppression_config(config_path=config_path)
        entry = config.entries[0]
        assert entry.type == SuppressionType.INLINE
        assert entry.line == 42

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        """Test loading invalid YAML raises error."""
        config_path = tmp_path / "suppressions.yaml"
        config_path.write_text("""
enabled: true
invalid: [unclosed list
""")

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_suppression_config(config_path=config_path)

    def test_load_missing_entry_id(self, tmp_path: Path) -> None:
        """Test loading entry without ID raises error."""
        config_path = tmp_path / "suppressions.yaml"
        config_path.write_text("""
entries:
  - type: config
    rules: [magic-number]
""")

        with pytest.raises(ValueError, match="Missing required field"):
            load_suppression_config(config_path=config_path)

    def test_load_invalid_type(self, tmp_path: Path) -> None:
        """Test loading entry with invalid type raises error."""
        config_path = tmp_path / "suppressions.yaml"
        config_path.write_text("""
entries:
  - id: test-1
    type: invalid-type
""")

        with pytest.raises(ValueError, match="Invalid suppression type"):
            load_suppression_config(config_path=config_path)

    def test_load_with_project_root(self, tmp_path: Path) -> None:
        """Test loading with project root."""
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        config_path = warden_dir / "suppressions.yaml"
        config_path.write_text("enabled: true")

        config = load_suppression_config(project_root=tmp_path)
        assert config.enabled is True


class TestSaveSuppressionConfig:
    """Test saving suppression configuration."""

    def test_save_basic_config(self, tmp_path: Path) -> None:
        """Test saving basic configuration."""
        config = SuppressionConfig(
            enabled=True,
            global_rules=['unused-import'],
            ignored_files=['test_*.py'],
        )

        config_path = tmp_path / "suppressions.yaml"
        save_suppression_config(config, config_path=config_path)

        assert config_path.exists()
        content = config_path.read_text()
        assert 'enabled: true' in content
        assert 'globalRules:' in content
        assert '- unused-import' in content
        assert 'ignoredFiles:' in content
        assert '- test_*.py' in content

    def test_save_with_entries(self, tmp_path: Path) -> None:
        """Test saving configuration with entries."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.CONFIG,
            rules=['sql-injection'],
            file='legacy/*.py',
            reason='Legacy code',
        )
        config = SuppressionConfig(entries=[entry])

        config_path = tmp_path / "suppressions.yaml"
        save_suppression_config(config, config_path=config_path)

        content = config_path.read_text()
        assert 'entries:' in content
        assert 'id: test-1' in content
        assert 'type: config' in content
        assert 'sql-injection' in content
        assert 'file: legacy/*.py' in content
        assert 'reason: Legacy code' in content

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        """Test saving creates parent directory if needed."""
        config = SuppressionConfig(enabled=True)
        config_path = tmp_path / ".warden" / "suppressions.yaml"

        save_suppression_config(config, config_path=config_path)

        assert config_path.exists()
        assert config_path.parent.exists()

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """Test save and load round-trip."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.CONFIG,
            rules=['magic-number', 'sql-injection'],
            file='src/*.py',
            line=42,
            reason='Test reason',
            enabled=False,
        )
        original_config = SuppressionConfig(
            enabled=True,
            entries=[entry],
            global_rules=['unused-import'],
            ignored_files=['test_*.py'],
        )

        config_path = tmp_path / "suppressions.yaml"
        save_suppression_config(original_config, config_path=config_path)

        loaded_config = load_suppression_config(config_path=config_path)

        # Compare configurations
        assert loaded_config.enabled == original_config.enabled
        assert loaded_config.global_rules == original_config.global_rules
        assert loaded_config.ignored_files == original_config.ignored_files
        assert len(loaded_config.entries) == len(original_config.entries)

        # Compare entry
        loaded_entry = loaded_config.entries[0]
        assert loaded_entry.id == entry.id
        assert loaded_entry.type == entry.type
        assert loaded_entry.rules == entry.rules
        assert loaded_entry.file == entry.file
        assert loaded_entry.line == entry.line
        assert loaded_entry.reason == entry.reason
        assert loaded_entry.enabled == entry.enabled

    def test_save_minimal_config(self, tmp_path: Path) -> None:
        """Test saving minimal configuration."""
        config = SuppressionConfig(enabled=False)
        config_path = tmp_path / "suppressions.yaml"

        save_suppression_config(config, config_path=config_path)

        content = config_path.read_text()
        assert 'enabled: false' in content
        # Should not include empty lists
        assert 'globalRules' not in content
        assert 'ignoredFiles' not in content
        assert 'entries' not in content

    def test_save_with_project_root(self, tmp_path: Path) -> None:
        """Test saving with project root."""
        config = SuppressionConfig(enabled=True)

        save_suppression_config(config, project_root=tmp_path)

        config_path = tmp_path / ".warden" / "suppressions.yaml"
        assert config_path.exists()


class TestCreateDefaultConfig:
    """Test creating default configuration."""

    def test_create_default_config(self, tmp_path: Path) -> None:
        """Test creating default configuration."""
        config_path = tmp_path / "suppressions.yaml"
        config = create_default_config(config_path=config_path)

        assert config.enabled is True
        assert config.global_rules == []
        assert len(config.ignored_files) > 0  # Should have some default patterns
        assert config.entries == []

        # File should be created
        assert config_path.exists()

    def test_create_default_with_project_root(self, tmp_path: Path) -> None:
        """Test creating default config with project root."""
        config = create_default_config(project_root=tmp_path)

        assert config.enabled is True

        config_path = tmp_path / ".warden" / "suppressions.yaml"
        assert config_path.exists()

    def test_default_config_has_test_patterns(self, tmp_path: Path) -> None:
        """Test default config includes test file patterns."""
        config_path = tmp_path / "suppressions.yaml"
        config = create_default_config(config_path=config_path)

        # Should ignore common test patterns
        assert any('test' in pattern for pattern in config.ignored_files)


class TestCamelCaseConversion:
    """Test camelCase ↔ snake_case conversion in YAML."""

    def test_camel_case_in_yaml(self, tmp_path: Path) -> None:
        """Test YAML uses camelCase."""
        config = SuppressionConfig(
            global_rules=['test-rule'],
            ignored_files=['test.py'],
        )

        config_path = tmp_path / "suppressions.yaml"
        save_suppression_config(config, config_path=config_path)

        content = config_path.read_text()
        # Should use camelCase in YAML
        assert 'globalRules:' in content
        assert 'ignoredFiles:' in content
        # Should not use snake_case
        assert 'global_rules' not in content
        assert 'ignored_files' not in content

    def test_load_camel_case_yaml(self, tmp_path: Path) -> None:
        """Test loading YAML with camelCase."""
        config_path = tmp_path / "suppressions.yaml"
        config_path.write_text("""
enabled: true
globalRules:
  - rule1
ignoredFiles:
  - file1.py
""")

        config = load_suppression_config(config_path=config_path)
        assert config.global_rules == ['rule1']
        assert config.ignored_files == ['file1.py']


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_load_with_extra_fields(self, tmp_path: Path) -> None:
        """Test loading with extra unknown fields."""
        config_path = tmp_path / "suppressions.yaml"
        config_path.write_text("""
enabled: true
unknownField: value
globalRules:
  - test-rule
""")

        # Should not raise error, just ignore unknown fields
        config = load_suppression_config(config_path=config_path)
        assert config.enabled is True
        assert config.global_rules == ['test-rule']

    def test_save_empty_entries_list(self, tmp_path: Path) -> None:
        """Test saving with empty entries list."""
        config = SuppressionConfig(
            enabled=True,
            entries=[],
        )

        config_path = tmp_path / "suppressions.yaml"
        save_suppression_config(config, config_path=config_path)

        content = config_path.read_text()
        # Empty list should not be saved
        assert 'entries' not in content

    def test_unicode_in_config(self, tmp_path: Path) -> None:
        """Test handling Unicode in configuration."""
        entry = SuppressionEntry(
            id='test-1',
            type=SuppressionType.CONFIG,
            rules=['rule'],
            reason='Reason with émojis 🎉 and ünicode',
        )
        config = SuppressionConfig(entries=[entry])

        config_path = tmp_path / "suppressions.yaml"
        save_suppression_config(config, config_path=config_path)

        loaded = load_suppression_config(config_path=config_path)
        assert loaded.entries[0].reason == entry.reason
