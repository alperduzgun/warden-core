"""
Unit tests for PlatformConfig validation.

Tests enhanced validation with clear error messages for invalid configurations.
"""

import pytest
from warden.validation.frames.spec.models import (
    PlatformConfig,
    PlatformType,
    PlatformRole,
)


class TestPlatformConfigValidation:
    """Test PlatformConfig.from_dict() validation."""

    def test_valid_config(self):
        """Test valid platform configuration."""
        data = {
            "name": "mobile",
            "path": "../my-app",
            "type": "flutter",
            "role": "consumer",
        }
        config = PlatformConfig.from_dict(data)
        assert config.name == "mobile"
        assert config.path == "../my-app"
        assert config.platform_type == PlatformType.FLUTTER
        assert config.role == PlatformRole.CONSUMER

    def test_valid_config_with_description(self):
        """Test valid config with optional description."""
        data = {
            "name": "backend",
            "path": "../api",
            "type": "spring",
            "role": "provider",
            "description": "Main API backend",
        }
        config = PlatformConfig.from_dict(data)
        assert config.description == "Main API backend"

    def test_missing_name(self):
        """Test missing 'name' field raises ValueError."""
        data = {
            "path": "../my-app",
            "type": "flutter",
            "role": "consumer",
        }
        with pytest.raises(ValueError) as exc_info:
            PlatformConfig.from_dict(data)
        assert "name" in str(exc_info.value).lower()
        assert "required" in str(exc_info.value).lower()

    def test_empty_name(self):
        """Test empty 'name' field raises ValueError."""
        data = {
            "name": "   ",  # Whitespace only
            "path": "../my-app",
            "type": "flutter",
            "role": "consumer",
        }
        with pytest.raises(ValueError) as exc_info:
            PlatformConfig.from_dict(data)
        assert "name" in str(exc_info.value).lower()
        assert "required" in str(exc_info.value).lower()

    def test_missing_path(self):
        """Test missing 'path' field raises ValueError."""
        data = {
            "name": "mobile",
            "type": "flutter",
            "role": "consumer",
        }
        with pytest.raises(ValueError) as exc_info:
            PlatformConfig.from_dict(data)
        assert "path" in str(exc_info.value).lower()
        assert "required" in str(exc_info.value).lower()
        assert "mobile" in str(exc_info.value)  # Includes platform name in error

    def test_empty_path(self):
        """Test empty 'path' field raises ValueError."""
        data = {
            "name": "mobile",
            "path": "",
            "type": "flutter",
            "role": "consumer",
        }
        with pytest.raises(ValueError) as exc_info:
            PlatformConfig.from_dict(data)
        assert "path" in str(exc_info.value).lower()
        assert "mobile" in str(exc_info.value)

    def test_missing_type(self):
        """Test missing 'type' field raises ValueError."""
        data = {
            "name": "mobile",
            "path": "../my-app",
            "role": "consumer",
        }
        with pytest.raises(ValueError) as exc_info:
            PlatformConfig.from_dict(data)
        assert "type" in str(exc_info.value).lower()
        assert "required" in str(exc_info.value).lower()
        assert "mobile" in str(exc_info.value)
        # Should suggest valid options
        assert "flutter" in str(exc_info.value).lower() or "valid options" in str(exc_info.value).lower()

    def test_invalid_type(self):
        """Test invalid platform type raises ValueError with suggestions."""
        data = {
            "name": "mobile",
            "path": "../my-app",
            "type": "invalid-type",
            "role": "consumer",
        }
        with pytest.raises(ValueError) as exc_info:
            PlatformConfig.from_dict(data)
        error_msg = str(exc_info.value).lower()
        assert "invalid" in error_msg
        assert "type" in error_msg
        assert "invalid-type" in error_msg
        # Should suggest valid options
        assert "flutter" in error_msg or "spring" in error_msg

    def test_missing_role(self):
        """Test missing 'role' field raises ValueError."""
        data = {
            "name": "mobile",
            "path": "../my-app",
            "type": "flutter",
        }
        with pytest.raises(ValueError) as exc_info:
            PlatformConfig.from_dict(data)
        assert "role" in str(exc_info.value).lower()
        assert "required" in str(exc_info.value).lower()
        assert "mobile" in str(exc_info.value)

    def test_invalid_role(self):
        """Test invalid role raises ValueError with suggestions."""
        data = {
            "name": "mobile",
            "path": "../my-app",
            "type": "flutter",
            "role": "invalid-role",
        }
        with pytest.raises(ValueError) as exc_info:
            PlatformConfig.from_dict(data)
        error_msg = str(exc_info.value).lower()
        assert "invalid" in error_msg
        assert "role" in error_msg
        assert "invalid-role" in error_msg
        # Should suggest valid options
        assert "consumer" in error_msg or "provider" in error_msg

    def test_all_platform_types_valid(self):
        """Test all PlatformType enum values are accepted."""
        for platform_type in PlatformType:
            data = {
                "name": "test",
                "path": "../test",
                "type": platform_type.value,
                "role": "consumer",
            }
            config = PlatformConfig.from_dict(data)
            assert config.platform_type == platform_type

    def test_all_platform_roles_valid(self):
        """Test all PlatformRole enum values are accepted."""
        for role in PlatformRole:
            data = {
                "name": "test",
                "path": "../test",
                "type": "flutter",
                "role": role.value,
            }
            config = PlatformConfig.from_dict(data)
            assert config.role == role

    def test_whitespace_trimming(self):
        """Test that whitespace is trimmed from string fields."""
        data = {
            "name": "  mobile  ",
            "path": "  ../my-app  ",
            "type": "  flutter  ",
            "role": "  consumer  ",
        }
        config = PlatformConfig.from_dict(data)
        assert config.name == "mobile"
        assert config.path == "../my-app"
        assert config.platform_type == PlatformType.FLUTTER
        assert config.role == PlatformRole.CONSUMER

    def test_error_message_clarity(self):
        """Test that error messages are clear and helpful."""
        # Missing name
        with pytest.raises(ValueError) as exc_info:
            PlatformConfig.from_dict({"path": "x", "type": "flutter", "role": "consumer"})
        assert "Example:" in str(exc_info.value)

        # Invalid type
        with pytest.raises(ValueError) as exc_info:
            PlatformConfig.from_dict({
                "name": "test",
                "path": "x",
                "type": "invalid",
                "role": "consumer",
            })
        assert "Valid options:" in str(exc_info.value)
        assert "test" in str(exc_info.value)  # Includes platform name


class TestSpecFramePlatformConfigParsing:
    """Test SpecFrame platform config parsing with validation."""

    def test_parse_valid_platforms(self):
        """Test parsing valid platform configurations."""
        from warden.validation.frames.spec.spec_frame import SpecFrame

        config = {
            "platforms": [
                {
                    "name": "mobile",
                    "path": "../app",
                    "type": "flutter",
                    "role": "consumer",
                },
                {
                    "name": "backend",
                    "path": "../api",
                    "type": "spring",
                    "role": "provider",
                },
            ],
        }
        frame = SpecFrame(config=config)
        assert len(frame.platforms) == 2
        assert frame.platforms[0].name == "mobile"
        assert frame.platforms[1].name == "backend"

    def test_parse_invalid_platform_continues(self):
        """Test that parsing continues after invalid platform (graceful degradation)."""
        from warden.validation.frames.spec.spec_frame import SpecFrame

        config = {
            "platforms": [
                {
                    "name": "mobile",
                    "path": "../app",
                    "type": "flutter",
                    "role": "consumer",
                },
                {
                    "name": "invalid",
                    "path": "../api",
                    "type": "INVALID_TYPE",  # Invalid
                    "role": "provider",
                },
                {
                    "name": "backend",
                    "path": "../api",
                    "type": "spring",
                    "role": "provider",
                },
            ],
        }
        frame = SpecFrame(config=config)
        # Should have 2 valid platforms (invalid one skipped)
        assert len(frame.platforms) == 2
        assert frame.platforms[0].name == "mobile"
        assert frame.platforms[1].name == "backend"

    def test_parse_missing_required_field(self):
        """Test parsing platform with missing required field."""
        from warden.validation.frames.spec.spec_frame import SpecFrame

        config = {
            "platforms": [
                {
                    "name": "mobile",
                    # Missing 'path'
                    "type": "flutter",
                    "role": "consumer",
                },
                {
                    "name": "backend",
                    "path": "../api",
                    "type": "spring",
                    "role": "provider",
                },
            ],
        }
        frame = SpecFrame(config=config)
        # Should have 1 valid platform (first one skipped)
        assert len(frame.platforms) == 1
        assert frame.platforms[0].name == "backend"

    def test_parse_empty_platforms(self):
        """Test parsing empty platforms list."""
        from warden.validation.frames.spec.spec_frame import SpecFrame

        config = {"platforms": []}
        frame = SpecFrame(config=config)
        assert len(frame.platforms) == 0

    def test_parse_no_platforms_key(self):
        """Test parsing config with no platforms key."""
        from warden.validation.frames.spec.spec_frame import SpecFrame

        config = {}
        frame = SpecFrame(config=config)
        assert len(frame.platforms) == 0
