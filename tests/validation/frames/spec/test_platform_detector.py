"""
Tests for Platform Detector module.

Tests automatic detection of projects and platform type suggestion.
"""

import asyncio
import json
from pathlib import Path

import pytest

from warden.validation.frames.spec.platform_detector import (
    PlatformDetector,
    DetectedProject,
)
from warden.validation.frames.spec.models import PlatformType, PlatformRole


@pytest.fixture
def detector():
    """Create a platform detector with default settings."""
    return PlatformDetector(max_depth=2, min_confidence=0.5)


@pytest.fixture
def flutter_project(tmp_path):
    """Create a mock Flutter project."""
    project_dir = tmp_path / "my_flutter_app"
    project_dir.mkdir()

    # Create pubspec.yaml
    pubspec = project_dir / "pubspec.yaml"
    pubspec.write_text("""
name: my_flutter_app
description: A Flutter application

dependencies:
  flutter:
    sdk: flutter
  cupertino_icons: ^1.0.2
""")

    return project_dir


@pytest.fixture
def spring_boot_project(tmp_path):
    """Create a mock Spring Boot project."""
    project_dir = tmp_path / "my_api"
    project_dir.mkdir()

    # Create pom.xml
    pom = project_dir / "pom.xml"
    pom.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>2.7.0</version>
    </parent>
    <groupId>com.example</groupId>
    <artifactId>my-api</artifactId>
</project>
""")

    return project_dir


@pytest.fixture
def react_project(tmp_path):
    """Create a mock React project."""
    project_dir = tmp_path / "my_frontend"
    project_dir.mkdir()

    # Create package.json
    package_json = project_dir / "package.json"
    package_json.write_text(json.dumps({
        "name": "my-frontend",
        "version": "1.0.0",
        "dependencies": {
            "react": "^18.2.0",
            "react-dom": "^18.2.0"
        }
    }, indent=2))

    return project_dir


@pytest.fixture
def fastapi_project(tmp_path):
    """Create a mock FastAPI project."""
    project_dir = tmp_path / "my_backend"
    project_dir.mkdir()

    # Create requirements.txt
    requirements = project_dir / "requirements.txt"
    requirements.write_text("""
fastapi==0.95.0
uvicorn[standard]==0.21.1
pydantic==1.10.7
""")

    return project_dir


@pytest.mark.asyncio
async def test_detect_flutter_project(detector, flutter_project):
    """Test detection of Flutter project."""
    projects = await detector.detect_projects_async(flutter_project.parent)

    assert len(projects) == 1
    project = projects[0]

    assert project.name == "my_flutter_app"
    assert project.platform_type == PlatformType.FLUTTER
    assert project.role == PlatformRole.CONSUMER
    assert project.confidence >= 0.5
    assert "pubspec.yaml" in str(project.evidence)


@pytest.mark.asyncio
async def test_detect_spring_boot_project(detector, spring_boot_project):
    """Test detection of Spring Boot project."""
    projects = await detector.detect_projects_async(spring_boot_project.parent)

    assert len(projects) == 1
    project = projects[0]

    assert project.name == "my_api"
    assert project.platform_type in [PlatformType.SPRING_BOOT, PlatformType.SPRING]
    assert project.role == PlatformRole.PROVIDER
    assert project.confidence >= 0.5


@pytest.mark.asyncio
async def test_detect_react_project(detector, react_project):
    """Test detection of React project."""
    projects = await detector.detect_projects_async(react_project.parent)

    assert len(projects) == 1
    project = projects[0]

    assert project.name == "my_frontend"
    assert project.platform_type == PlatformType.REACT
    assert project.role == PlatformRole.CONSUMER
    assert project.confidence >= 0.5


@pytest.mark.asyncio
async def test_detect_fastapi_project(detector, fastapi_project):
    """Test detection of FastAPI project."""
    projects = await detector.detect_projects_async(fastapi_project.parent)

    assert len(projects) == 1
    project = projects[0]

    assert project.name == "my_backend"
    assert project.platform_type == PlatformType.FASTAPI
    assert project.role == PlatformRole.PROVIDER
    assert project.confidence >= 0.5


@pytest.mark.asyncio
async def test_detect_multiple_projects(
    detector,
    flutter_project,
    spring_boot_project,
    react_project,
):
    """Test detection of multiple projects in same directory."""
    # All projects are in tmp_path
    search_root = flutter_project.parent

    projects = await detector.detect_projects_async(search_root)

    # Should find all 3 projects
    assert len(projects) >= 3

    # Check we have both consumers and providers
    roles = {p.role for p in projects}
    assert PlatformRole.CONSUMER in roles
    assert PlatformRole.PROVIDER in roles


@pytest.mark.asyncio
async def test_confidence_threshold_filtering(tmp_path):
    """Test that low confidence projects are filtered out."""
    # Create detector with high confidence threshold
    high_conf_detector = PlatformDetector(min_confidence=0.9)

    # Create a partial Flutter project (low confidence)
    partial_project = tmp_path / "partial_flutter"
    partial_project.mkdir()
    pubspec = partial_project / "pubspec.yaml"
    pubspec.write_text("name: test")  # Missing flutter dependency

    projects = await high_conf_detector.detect_projects_async(tmp_path)

    # Should not find the partial project (confidence too low)
    assert len(projects) == 0


@pytest.mark.asyncio
async def test_max_depth_limit(tmp_path):
    """Test that max_depth is respected."""
    # Create detector with depth limit
    shallow_detector = PlatformDetector(max_depth=1)

    # Create nested project (too deep)
    nested = tmp_path / "level1" / "level2" / "level3" / "deep_flutter"
    nested.mkdir(parents=True)
    pubspec = nested / "pubspec.yaml"
    pubspec.write_text("""
name: deep_flutter
dependencies:
  flutter:
    sdk: flutter
""")

    projects = await shallow_detector.detect_projects_async(tmp_path)

    # Should not find deeply nested project
    assert len(projects) == 0


@pytest.mark.asyncio
async def test_exclude_dirs(tmp_path):
    """Test that excluded directories are skipped."""
    # Create project in node_modules (should be excluded)
    excluded_dir = tmp_path / "node_modules" / "some_package"
    excluded_dir.mkdir(parents=True)
    package_json = excluded_dir / "package.json"
    package_json.write_text(json.dumps({
        "name": "excluded",
        "dependencies": {"react": "^18.0.0"}
    }))

    detector = PlatformDetector()
    projects = await detector.detect_projects_async(tmp_path)

    # Should not find project in excluded directory
    assert len(projects) == 0


@pytest.mark.asyncio
async def test_nonexistent_path(detector):
    """Test that nonexistent path raises ValueError."""
    with pytest.raises(ValueError, match="does not exist"):
        await detector.detect_projects_async("/nonexistent/path")


@pytest.mark.asyncio
async def test_file_instead_of_directory(detector, tmp_path):
    """Test that file path raises ValueError."""
    file_path = tmp_path / "file.txt"
    file_path.write_text("test")

    with pytest.raises(ValueError, match="not a directory"):
        await detector.detect_projects_async(file_path)


@pytest.mark.asyncio
async def test_react_native_detection(tmp_path):
    """Test React Native is detected separately from React."""
    rn_project = tmp_path / "mobile_app"
    rn_project.mkdir()

    package_json = rn_project / "package.json"
    package_json.write_text(json.dumps({
        "name": "mobile-app",
        "dependencies": {
            "react": "^18.2.0",
            "react-native": "^0.71.0"
        }
    }))

    detector = PlatformDetector()
    projects = await detector.detect_projects_async(tmp_path)

    assert len(projects) == 1
    assert projects[0].platform_type == PlatformType.REACT_NATIVE


@pytest.mark.asyncio
async def test_nestjs_detection(tmp_path):
    """Test NestJS is detected separately from Express."""
    nest_project = tmp_path / "nest_api"
    nest_project.mkdir()

    package_json = nest_project / "package.json"
    package_json.write_text(json.dumps({
        "name": "nest-api",
        "dependencies": {
            "@nestjs/core": "^9.0.0",
            "@nestjs/common": "^9.0.0"
        }
    }))

    detector = PlatformDetector()
    projects = await detector.detect_projects_async(tmp_path)

    assert len(projects) == 1
    assert projects[0].platform_type == PlatformType.NESTJS
    assert projects[0].role == PlatformRole.PROVIDER


@pytest.mark.asyncio
async def test_bff_pattern_detection(tmp_path):
    """Test BFF (Backend for Frontend) pattern detection."""
    # Next.js with API routes
    bff_project = tmp_path / "nextjs_bff"
    bff_project.mkdir()

    # Create pages/api directory
    api_dir = bff_project / "pages" / "api"
    api_dir.mkdir(parents=True)

    package_json = bff_project / "package.json"
    package_json.write_text(json.dumps({
        "name": "nextjs-bff",
        "dependencies": {
            "react": "^18.2.0",
            "next": "^13.0.0"
        }
    }))

    detector = PlatformDetector()
    projects = await detector.detect_projects_async(tmp_path)

    assert len(projects) == 1
    # Should detect as BOTH role due to API directory
    assert projects[0].role == PlatformRole.BOTH


@pytest.mark.asyncio
async def test_metadata_extraction_from_package_json(tmp_path):
    """Test metadata extraction from package.json."""
    project = tmp_path / "versioned_app"
    project.mkdir()

    package_json = project / "package.json"
    package_json.write_text(json.dumps({
        "name": "versioned-app",
        "version": "2.5.0",
        "dependencies": {
            "react": "^18.2.0"
        }
    }))

    detector = PlatformDetector()
    projects = await detector.detect_projects_async(tmp_path)

    assert len(projects) == 1
    assert projects[0].metadata.get("version") == "2.5.0"
    assert projects[0].metadata.get("package_name") == "versioned-app"
    assert "react_version" in projects[0].metadata


def test_detected_project_to_dict():
    """Test DetectedProject serialization."""
    project = DetectedProject(
        name="test_project",
        path="/path/to/project",
        platform_type=PlatformType.FLUTTER,
        confidence=0.95,
        role=PlatformRole.CONSUMER,
        evidence=["pubspec.yaml"],
        metadata={"version": "1.0.0"},
    )

    data = project.to_dict()

    assert data["name"] == "test_project"
    assert data["path"] == "/path/to/project"
    assert data["type"] == "flutter"
    assert data["role"] == "consumer"
    assert data["confidence"] == 0.95
    assert "pubspec.yaml" in data["evidence"]
    assert data["metadata"]["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_exclusion_patterns(tmp_path):
    """Test exclusion patterns reduce confidence."""
    # Create React Native project (has react-native in package.json)
    # This should trigger exclusion pattern in React detection
    rn_project = tmp_path / "rn_app"
    rn_project.mkdir()

    package_json = rn_project / "package.json"
    package_json.write_text(json.dumps({
        "name": "rn-app",
        "dependencies": {
            "react": "^18.2.0",
            "react-native": "^0.71.0"
        }
    }))

    detector = PlatformDetector()
    projects = await detector.detect_projects_async(tmp_path)

    # Should detect as React Native, not React
    # React detection should have reduced confidence due to exclusion pattern
    assert any(p.platform_type == PlatformType.REACT_NATIVE for p in projects)


@pytest.mark.asyncio
async def test_permission_error_handling(tmp_path, monkeypatch):
    """Test graceful handling of permission errors."""
    project = tmp_path / "restricted"
    project.mkdir()

    # Mock iterdir to raise PermissionError
    original_iterdir = Path.iterdir

    def mock_iterdir(self):
        if "restricted" in str(self):
            raise PermissionError("Access denied")
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", mock_iterdir)

    detector = PlatformDetector()
    # Should not raise, but log warning
    projects = await detector.detect_projects_async(tmp_path)

    # No crash, empty results
    assert isinstance(projects, list)
