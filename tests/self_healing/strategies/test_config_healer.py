"""Tests for ConfigHealer strategy."""

from __future__ import annotations

import pytest

from warden.self_healing.models import ErrorCategory
from warden.self_healing.strategies.config_healer import ConfigHealer


class TestConfigHealer:
    @pytest.mark.asyncio
    async def test_can_heal_yaml_error(self):
        healer = ConfigHealer()
        err = Exception("yaml.scanner.ScannerError: mapping values are not allowed here")
        assert await healer.can_heal(err, ErrorCategory.CONFIG_ERROR) is True

    @pytest.mark.asyncio
    async def test_can_heal_config_error(self):
        healer = ConfigHealer()
        err = Exception("invalid config value for 'provider'")
        assert await healer.can_heal(err, ErrorCategory.CONFIG_ERROR) is True

    @pytest.mark.asyncio
    async def test_can_heal_unrelated_error(self):
        healer = ConfigHealer()
        err = Exception("some unrelated error")
        assert await healer.can_heal(err, ErrorCategory.CONFIG_ERROR) is False

    @pytest.mark.asyncio
    async def test_heal_missing_config(self, tmp_path):
        """No config file → cannot repair."""
        healer = ConfigHealer(project_root=tmp_path)
        err = Exception("yaml.scanner error")
        result = await healer.heal(err)
        assert result.fixed is False
        assert "not found" in result.diagnosis

    @pytest.mark.asyncio
    async def test_heal_corrupt_config(self, tmp_path):
        """Corrupt YAML → backup + reset defaults."""
        config_dir = tmp_path / ".warden"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text("{{{{invalid yaml!!!!!", encoding="utf-8")

        healer = ConfigHealer(project_root=tmp_path)
        err = Exception("yaml.scanner.ScannerError")
        result = await healer.heal(err)

        assert result.fixed is True
        assert result.config_repaired is True
        assert result.should_retry is True
        assert result.strategy_used == "config_healer"

        # Backup should exist
        backups = list(config_dir.glob("config.yaml.bak.*"))
        assert len(backups) == 1

        # Config should be reset to defaults
        new_content = config_path.read_text(encoding="utf-8")
        assert "provider:" in new_content

    @pytest.mark.asyncio
    async def test_heal_preserves_backup(self, tmp_path):
        """Backup preserves original content."""
        config_dir = tmp_path / ".warden"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        original = "corrupt: {{{bad yaml"
        config_path.write_text(original, encoding="utf-8")

        healer = ConfigHealer(project_root=tmp_path)
        await healer.heal(Exception("yaml error"))

        backups = list(config_dir.glob("config.yaml.bak.*"))
        assert backups[0].read_text(encoding="utf-8") == original

    def test_name_and_priority(self):
        healer = ConfigHealer()
        assert healer.name == "config_healer"
        assert healer.priority == 150
        assert ErrorCategory.CONFIG_ERROR in healer.handles

    def test_default_config_valid_yaml(self):
        """DEFAULT_CONFIG must be parseable YAML."""
        import yaml

        from warden.self_healing.strategies.config_healer import DEFAULT_CONFIG

        parsed = yaml.safe_load(DEFAULT_CONFIG)
        assert isinstance(parsed, dict)
        assert "provider" in parsed
