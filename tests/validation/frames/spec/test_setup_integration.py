#!/usr/bin/env python3
"""
Quick test script for SpecFrame setup modules.

Tests basic functionality of platform detector, validator, and setup wizard.
"""

import asyncio
import tempfile
from pathlib import Path
import json

from warden.validation.frames.spec.platform_detector import (
    PlatformDetector,
    DetectedProject,
)
from warden.validation.frames.spec.validation import (
    SpecConfigValidator,
    ValidationIssue,
    IssueSeverity,
)
from warden.validation.frames.spec.setup_wizard import (
    SetupWizard,
    SetupWizardConfig,
    PlatformSetupInput,
)
from warden.validation.frames.spec.models import PlatformType, PlatformRole


def test_platform_detector():
    """Test platform detector."""
    print("Testing Platform Detector...")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create a Flutter project
        flutter_dir = tmp_path / "my_flutter_app"
        flutter_dir.mkdir()
        pubspec = flutter_dir / "pubspec.yaml"
        pubspec.write_text("""
name: my_flutter_app
dependencies:
  flutter:
    sdk: flutter
""")

        # Create a Spring Boot project
        spring_dir = tmp_path / "my_api"
        spring_dir.mkdir()
        pom = spring_dir / "pom.xml"
        pom.write_text("""<?xml version="1.0"?>
<project>
    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
    </parent>
</project>
""")

        # Detect projects
        detector = PlatformDetector(max_depth=2, min_confidence=0.5)

        async def detect():
            projects = await detector.detect_projects_async(tmp_path)
            return projects

        projects = asyncio.run(detect())

        assert len(projects) >= 2, f"Expected at least 2 projects, got {len(projects)}"
        assert any(p.platform_type == PlatformType.FLUTTER for p in projects)
        assert any(p.platform_type in [PlatformType.SPRING, PlatformType.SPRING_BOOT] for p in projects)

        print(f"  ✓ Detected {len(projects)} projects")
        for p in projects:
            print(f"    - {p.name}: {p.platform_type.value} ({p.role.value}) - {p.confidence:.0%}")


def test_config_validator():
    """Test config validator."""
    print("\nTesting Config Validator...")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()

        # Create platform directories
        mobile_dir = tmp_path / "mobile"
        mobile_dir.mkdir()
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()

        validator = SpecConfigValidator(project_root=tmp_path)

        # Valid configuration
        valid_platforms = [
            {
                "name": "mobile",
                "path": "mobile",
                "type": "flutter",
                "role": "consumer",
            },
            {
                "name": "backend",
                "path": "backend",
                "type": "spring-boot",
                "role": "provider",
            },
        ]

        result = validator.validate_platforms(valid_platforms)

        assert result.is_valid, f"Expected valid config, got {result.error_count} errors"
        assert result.error_count == 0
        print(f"  ✓ Valid configuration passed validation")

        # Invalid configuration (missing path)
        invalid_platforms = [
            {
                "name": "mobile",
                "path": "nonexistent",
                "type": "flutter",
                "role": "consumer",
            },
        ]

        result = validator.validate_platforms(invalid_platforms)

        assert not result.is_valid
        assert result.error_count > 0
        print(f"  ✓ Invalid configuration caught {result.error_count} errors")


def test_setup_wizard():
    """Test setup wizard."""
    print("\nTesting Setup Wizard...")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()

        # Create projects
        flutter_dir = tmp_path / "mobile"
        flutter_dir.mkdir()
        pubspec = flutter_dir / "pubspec.yaml"
        pubspec.write_text("name: mobile\ndependencies:\n  flutter:\n    sdk: flutter")

        spring_dir = tmp_path / "backend"
        spring_dir.mkdir()
        pom = spring_dir / "pom.xml"
        pom.write_text("""<?xml version="1.0"?>
<project>
    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
    </parent>
</project>
""")

        config = SetupWizardConfig(
            search_path=str(tmp_path),
            max_depth=2,
            min_confidence=0.5,
        )

        wizard = SetupWizard(config=config, project_root=tmp_path)

        # Discover projects
        async def discover():
            projects = await wizard.discover_projects_async()
            return projects

        projects = asyncio.run(discover())

        assert len(projects) >= 2
        print(f"  ✓ Discovered {len(projects)} projects")

        # Validate
        validation = wizard.validate_setup(projects)
        assert validation.is_valid
        print(f"  ✓ Validation passed")

        # Generate config
        config_dict = wizard.generate_config(projects)
        assert "frames" in config_dict
        assert "spec" in config_dict["frames"]
        print(f"  ✓ Generated configuration")

        # Save config
        config_path = wizard.save_config(config_dict, merge=False, backup=False)
        assert config_path.exists()
        print(f"  ✓ Saved configuration to {config_path}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("SpecFrame Setup Modules Test Suite")
    print("=" * 60)

    try:
        test_platform_detector()
        test_config_validator()
        test_setup_wizard()

        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
