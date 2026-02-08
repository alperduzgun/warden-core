"""
Tests for SpecFrame Setup Wizard.

Tests the orchestration of discovery, validation, and configuration generation.
"""

import json
from pathlib import Path

import pytest
import yaml

from warden.validation.frames.spec.setup_wizard import (
    SetupWizard,
    SetupWizardConfig,
    PlatformSetupInput,
)
from warden.validation.frames.spec.platform_detector import DetectedProject
from warden.validation.frames.spec.models import PlatformType, PlatformRole
from warden.validation.frames.spec.validation import IssueSeverity


@pytest.fixture
def wizard(tmp_path):
    """Create a setup wizard with temporary project root."""
    warden_dir = tmp_path / ".warden"
    warden_dir.mkdir()

    config = SetupWizardConfig(
        search_path=str(tmp_path),
        max_depth=2,
        min_confidence=0.5,
    )

    return SetupWizard(config=config, project_root=tmp_path)


@pytest.fixture
def sample_projects(tmp_path):
    """Create sample project directories."""
    # Flutter project
    flutter_dir = tmp_path / "mobile"
    flutter_dir.mkdir()
    pubspec = flutter_dir / "pubspec.yaml"
    pubspec.write_text("""
name: mobile_app
dependencies:
  flutter:
    sdk: flutter
""")

    # Spring Boot project
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

    return tmp_path


@pytest.mark.asyncio
async def test_discover_projects(wizard, sample_projects):
    """Test automatic project discovery."""
    projects = await wizard.discover_projects_async()

    assert len(projects) >= 2

    # Check we have both consumers and providers
    types = {p.platform_type for p in projects}
    assert PlatformType.FLUTTER in types
    assert PlatformType.SPRING_BOOT in types or PlatformType.SPRING in types


@pytest.mark.asyncio
async def test_discover_projects_custom_path(wizard, tmp_path):
    """Test discovery with custom search path."""
    # Create nested project
    nested_dir = tmp_path / "nested" / "projects"
    nested_dir.mkdir(parents=True)

    react_dir = nested_dir / "frontend"
    react_dir.mkdir()
    package_json = react_dir / "package.json"
    package_json.write_text(json.dumps({
        "name": "frontend",
        "dependencies": {"react": "^18.0.0"}
    }))

    projects = await wizard.discover_projects_async(str(nested_dir))

    assert len(projects) >= 1
    assert any(p.platform_type == PlatformType.REACT for p in projects)


def test_validate_detected_projects(wizard, sample_projects):
    """Test validation of detected projects."""
    detected = [
        DetectedProject(
            name="mobile",
            path=str(sample_projects / "mobile"),
            platform_type=PlatformType.FLUTTER,
            confidence=0.95,
            role=PlatformRole.CONSUMER,
        ),
        DetectedProject(
            name="backend",
            path=str(sample_projects / "backend"),
            platform_type=PlatformType.SPRING_BOOT,
            confidence=0.90,
            role=PlatformRole.PROVIDER,
        ),
    ]

    result = wizard.validate_setup(detected)

    assert result.is_valid
    assert result.error_count == 0


def test_validate_manual_inputs(wizard, sample_projects):
    """Test validation of manual platform inputs."""
    inputs = [
        PlatformSetupInput(
            name="mobile",
            path=str(sample_projects / "mobile"),
            platform_type="flutter",
            role="consumer",
        ),
        PlatformSetupInput(
            name="backend",
            path=str(sample_projects / "backend"),
            platform_type="spring-boot",
            role="provider",
        ),
    ]

    result = wizard.validate_setup(inputs)

    assert result.is_valid
    assert result.error_count == 0


def test_validate_invalid_setup(wizard, tmp_path):
    """Test validation fails for invalid setup."""
    # Only one platform (need at least 2)
    inputs = [
        PlatformSetupInput(
            name="mobile",
            path="/nonexistent/path",
            platform_type="flutter",
            role="consumer",
        ),
    ]

    result = wizard.validate_setup(inputs)

    assert not result.is_valid
    assert result.error_count >= 1


def test_generate_config_from_detected(wizard, sample_projects):
    """Test configuration generation from detected projects."""
    detected = [
        DetectedProject(
            name="mobile",
            path=str(sample_projects / "mobile"),
            platform_type=PlatformType.FLUTTER,
            confidence=0.95,
            role=PlatformRole.CONSUMER,
            evidence=["pubspec.yaml"],
            metadata={"version": "1.0.0"},
        ),
        DetectedProject(
            name="backend",
            path=str(sample_projects / "backend"),
            platform_type=PlatformType.SPRING_BOOT,
            confidence=0.90,
            role=PlatformRole.PROVIDER,
        ),
    ]

    config = wizard.generate_config(detected)

    assert "frames" in config
    assert "spec" in config["frames"]
    assert "platforms" in config["frames"]["spec"]

    platforms = config["frames"]["spec"]["platforms"]
    assert len(platforms) == 2

    # Check first platform
    assert platforms[0]["name"] == "mobile"
    assert platforms[0]["type"] == "flutter"
    assert platforms[0]["role"] == "consumer"


def test_generate_config_without_metadata(wizard, sample_projects):
    """Test config generation without metadata."""
    detected = [
        DetectedProject(
            name="mobile",
            path=str(sample_projects / "mobile"),
            platform_type=PlatformType.FLUTTER,
            confidence=0.95,
            role=PlatformRole.CONSUMER,
        ),
        DetectedProject(
            name="backend",
            path=str(sample_projects / "backend"),
            platform_type=PlatformType.SPRING,
            confidence=0.90,
            role=PlatformRole.PROVIDER,
        ),
    ]

    config = wizard.generate_config(detected, include_metadata=False)

    platforms = config["frames"]["spec"]["platforms"]

    # Should not have _metadata field
    assert "_metadata" not in platforms[0]


def test_generate_config_with_metadata(wizard, sample_projects):
    """Test config generation with metadata."""
    detected = [
        DetectedProject(
            name="mobile",
            path=str(sample_projects / "mobile"),
            platform_type=PlatformType.FLUTTER,
            confidence=0.95,
            role=PlatformRole.CONSUMER,
            evidence=["pubspec.yaml"],
        ),
        DetectedProject(
            name="backend",
            path=str(sample_projects / "backend"),
            platform_type=PlatformType.SPRING,
            confidence=0.90,
            role=PlatformRole.PROVIDER,
        ),
    ]

    config = wizard.generate_config(detected, include_metadata=True)

    platforms = config["frames"]["spec"]["platforms"]

    # Should have _metadata field
    assert "_metadata" in platforms[0]
    assert platforms[0]["_metadata"]["confidence"] == 0.95
    assert "pubspec.yaml" in platforms[0]["_metadata"]["evidence"]


def test_save_config(wizard, sample_projects):
    """Test configuration saving."""
    config = {
        "frames": {
            "spec": {
                "platforms": [
                    {
                        "name": "mobile",
                        "path": "mobile",
                        "type": "flutter",
                        "role": "consumer",
                    }
                ]
            }
        }
    }

    config_path = wizard.save_config(config, merge=False, backup=False)

    assert config_path.exists()
    assert config_path.name == "config.yaml"

    # Verify content
    saved = yaml.safe_load(config_path.read_text())
    assert "frames" in saved
    assert "spec" in saved["frames"]


def test_save_config_with_merge(wizard, tmp_path):
    """Test configuration saving with merge."""
    config_path = tmp_path / ".warden" / "config.yaml"

    # Create existing config with other frame
    existing = {
        "frames": {
            "security": {
                "enabled": True,
            }
        }
    }
    config_path.write_text(yaml.dump(existing))

    # Save new spec config
    new_config = {
        "frames": {
            "spec": {
                "platforms": [
                    {
                        "name": "mobile",
                        "path": "mobile",
                        "type": "flutter",
                        "role": "consumer",
                    }
                ]
            }
        }
    }

    wizard.save_config(new_config, merge=True, backup=False)

    # Verify merge
    saved = yaml.safe_load(config_path.read_text())

    # Should have both frames
    assert "security" in saved["frames"]
    assert "spec" in saved["frames"]
    assert saved["frames"]["security"]["enabled"] is True


def test_save_config_with_backup(wizard, tmp_path):
    """Test configuration saving with backup."""
    config_path = tmp_path / ".warden" / "config.yaml"

    # Create existing config
    existing = {"test": "data"}
    config_path.write_text(yaml.dump(existing))

    # Save new config with backup
    new_config = {"frames": {"spec": {"platforms": []}}}
    wizard.save_config(new_config, merge=False, backup=True)

    # Verify backup exists
    backup_path = config_path.with_suffix(".yaml.backup")
    assert backup_path.exists()

    # Backup should contain original data
    backup = yaml.safe_load(backup_path.read_text())
    assert backup["test"] == "data"


def test_load_existing_config(wizard, tmp_path):
    """Test loading existing configuration."""
    config_path = tmp_path / ".warden" / "config.yaml"

    # Create config
    config = {
        "frames": {
            "spec": {
                "platforms": [
                    {"name": "test", "path": "test", "type": "flutter", "role": "consumer"}
                ]
            }
        }
    }
    config_path.write_text(yaml.dump(config))

    # Load
    loaded = wizard.load_existing_config()

    assert loaded is not None
    assert "frames" in loaded
    assert "spec" in loaded["frames"]


def test_load_nonexistent_config(wizard):
    """Test loading nonexistent configuration returns None."""
    loaded = wizard.load_existing_config()
    assert loaded is None


@pytest.mark.asyncio
async def test_deduplicate_projects(wizard, tmp_path):
    """Test deduplication of detected projects."""
    # Create a project
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    pubspec = project_dir / "pubspec.yaml"
    pubspec.write_text("name: test\ndependencies:\n  flutter:\n    sdk: flutter")

    # Create two detections for same path
    projects = [
        DetectedProject(
            name="test_flutter",
            path=str(project_dir),
            platform_type=PlatformType.FLUTTER,
            confidence=0.95,
            role=PlatformRole.CONSUMER,
        ),
        DetectedProject(
            name="test_universal",
            path=str(project_dir),
            platform_type=PlatformType.UNIVERSAL,
            confidence=0.60,
            role=PlatformRole.CONSUMER,
        ),
    ]

    # Deduplicate (internal method)
    deduplicated = wizard._deduplicate_projects(projects)

    # Should keep only one (highest confidence)
    assert len(deduplicated) == 1
    assert deduplicated[0].platform_type == PlatformType.FLUTTER
    assert deduplicated[0].confidence == 0.95


def test_platform_setup_input_to_dict():
    """Test PlatformSetupInput serialization."""
    input_obj = PlatformSetupInput(
        name="test",
        path="/path/to/test",
        platform_type="flutter",
        role="consumer",
        description="Test platform",
    )

    data = input_obj.to_dict()

    assert data["name"] == "test"
    assert data["path"] == "/path/to/test"
    assert data["type"] == "flutter"
    assert data["role"] == "consumer"
    assert data["description"] == "Test platform"


def test_platform_setup_input_without_description():
    """Test PlatformSetupInput without optional description."""
    input_obj = PlatformSetupInput(
        name="test",
        path="/path",
        platform_type="react",
        role="consumer",
    )

    data = input_obj.to_dict()

    assert "description" not in data


def test_create_interactive_summary_with_projects(wizard, sample_projects):
    """Test interactive summary generation with projects."""
    projects = [
        DetectedProject(
            name="mobile",
            path=str(sample_projects / "mobile"),
            platform_type=PlatformType.FLUTTER,
            confidence=0.95,
            role=PlatformRole.CONSUMER,
        ),
        DetectedProject(
            name="backend",
            path=str(sample_projects / "backend"),
            platform_type=PlatformType.SPRING_BOOT,
            confidence=0.90,
            role=PlatformRole.PROVIDER,
        ),
    ]

    summary = wizard.create_interactive_summary(projects)

    assert "CONSUMERS" in summary
    assert "PROVIDERS" in summary
    assert "mobile" in summary
    assert "backend" in summary
    assert "flutter" in summary
    assert "95%" in summary


def test_create_interactive_summary_empty(wizard):
    """Test interactive summary with no projects."""
    summary = wizard.create_interactive_summary([])

    assert "No projects detected" in summary
    assert "Try:" in summary


def test_create_interactive_summary_with_validation(wizard, sample_projects):
    """Test interactive summary with validation results."""
    from warden.validation.frames.spec.validation import (
        ValidationResult,
        ValidationIssue,
    )

    projects = [
        DetectedProject(
            name="mobile",
            path=str(sample_projects / "mobile"),
            platform_type=PlatformType.FLUTTER,
            confidence=0.95,
            role=PlatformRole.CONSUMER,
        ),
    ]

    validation = ValidationResult(
        is_valid=False,
        issues=[
            ValidationIssue(
                severity=IssueSeverity.ERROR,
                message="Test error",
                field="test",
                suggestion="Fix it",
            )
        ],
    )

    summary = wizard.create_interactive_summary(projects, validation)

    assert "VALIDATION: FAILED" in summary
    assert "Test error" in summary
    assert "Fix it" in summary


def test_create_interactive_summary_with_bff(wizard, tmp_path):
    """Test interactive summary with BFF pattern platforms."""
    projects = [
        DetectedProject(
            name="bff",
            path=str(tmp_path / "bff"),
            platform_type=PlatformType.REACT,
            confidence=0.85,
            role=PlatformRole.BOTH,
        ),
    ]

    summary = wizard.create_interactive_summary(projects)

    assert "BOTH (BFF Pattern)" in summary
    assert "bff" in summary


def test_config_includes_default_settings(wizard, sample_projects):
    """Test that generated config includes default settings."""
    detected = [
        DetectedProject(
            name="mobile",
            path=str(sample_projects / "mobile"),
            platform_type=PlatformType.FLUTTER,
            confidence=0.95,
            role=PlatformRole.CONSUMER,
        ),
        DetectedProject(
            name="backend",
            path=str(sample_projects / "backend"),
            platform_type=PlatformType.SPRING,
            confidence=0.90,
            role=PlatformRole.PROVIDER,
        ),
    ]

    config = wizard.generate_config(detected)

    spec_config = config["frames"]["spec"]

    # Should have default settings
    assert "gap_analysis" in spec_config
    assert "resilience" in spec_config
    assert spec_config["gap_analysis"]["fuzzy_threshold"] == 0.8
    assert spec_config["resilience"]["extraction_timeout"] == 300


@pytest.mark.asyncio
async def test_full_wizard_workflow(wizard, sample_projects):
    """Test complete wizard workflow: discover -> validate -> generate -> save."""
    # 1. Discover
    projects = await wizard.discover_projects_async()
    assert len(projects) >= 2

    # 2. Validate
    validation = wizard.validate_setup(projects)
    assert validation.is_valid

    # 3. Generate
    config = wizard.generate_config(projects)
    assert "frames" in config

    # 4. Save
    config_path = wizard.save_config(config, merge=False, backup=False)
    assert config_path.exists()

    # Verify saved config
    saved = yaml.safe_load(config_path.read_text())
    assert "spec" in saved["frames"]
    assert len(saved["frames"]["spec"]["platforms"]) >= 2
