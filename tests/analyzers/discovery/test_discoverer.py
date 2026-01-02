"""
Unit tests for the Discovery module.

Tests file discovery, classification, and framework detection.
"""

import tempfile
from pathlib import Path
from typing import Generator

import pytest

from warden.analyzers.discovery import (
    FileDiscoverer,
    FileClassifier,
    GitignoreFilter,
    FrameworkDetector,
    FileType,
    Framework,
    discover_project_files,
)


@pytest.fixture
def temp_project() -> Generator[Path, None, None]:
    """Create a temporary project directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        # Create directory structure
        (project_root / "src").mkdir()
        (project_root / "tests").mkdir()
        (project_root / "node_modules").mkdir()
        (project_root / ".git").mkdir()

        # Create Python files
        (project_root / "src" / "main.py").write_text("print('hello')")
        (project_root / "src" / "utils.py").write_text("def util(): pass")
        (project_root / "tests" / "test_main.py").write_text("def test(): pass")

        # Create JavaScript files
        (project_root / "src" / "app.js").write_text("console.log('hi')")
        (project_root / "src" / "component.tsx").write_text("export const Comp = () => {}")

        # Create config files
        (project_root / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}')
        (project_root / "requirements.txt").write_text("flask==2.0.0\npytest==7.0.0")

        # Create .gitignore
        gitignore_content = """
node_modules/
.git/
*.pyc
__pycache__/
"""
        (project_root / ".gitignore").write_text(gitignore_content)

        # Create files to ignore
        (project_root / "src" / "cache.pyc").write_text("compiled")
        (project_root / "node_modules" / "lib.js").write_text("// library")

        yield project_root


class TestFileClassifier:
    """Test FileClassifier functionality."""

    def test_classify_python_file(self) -> None:
        """Test classification of Python files."""
        assert FileClassifier.classify(Path("main.py")) == FileType.PYTHON
        assert FileClassifier.classify(Path("script.pyw")) == FileType.PYTHON
        assert FileClassifier.classify(Path("types.pyi")) == FileType.PYTHON

    def test_classify_javascript_file(self) -> None:
        """Test classification of JavaScript files."""
        assert FileClassifier.classify(Path("app.js")) == FileType.JAVASCRIPT
        assert FileClassifier.classify(Path("module.mjs")) == FileType.JAVASCRIPT
        assert FileClassifier.classify(Path("common.cjs")) == FileType.JAVASCRIPT

    def test_classify_typescript_file(self) -> None:
        """Test classification of TypeScript files."""
        assert FileClassifier.classify(Path("app.ts")) == FileType.TYPESCRIPT
        assert FileClassifier.classify(Path("component.tsx")) == FileType.TSX
        assert FileClassifier.classify(Path("component.jsx")) == FileType.JSX

    def test_classify_unknown_file(self) -> None:
        """Test classification of unknown files."""
        assert FileClassifier.classify(Path("unknown.xyz")) == FileType.UNKNOWN
        assert FileClassifier.classify(Path("no_extension")) == FileType.UNKNOWN

    def test_should_skip_binary_files(self) -> None:
        """Test skipping binary files."""
        assert FileClassifier.should_skip(Path("image.png")) is True
        assert FileClassifier.should_skip(Path("video.mp4")) is True
        assert FileClassifier.should_skip(Path("archive.zip")) is True

    def test_should_not_skip_code_files(self) -> None:
        """Test not skipping code files."""
        assert FileClassifier.should_skip(Path("main.py")) is False
        assert FileClassifier.should_skip(Path("app.js")) is False

    def test_is_analyzable(self) -> None:
        """Test analyzable file detection."""
        assert FileClassifier.is_analyzable(Path("main.py")) is True
        assert FileClassifier.is_analyzable(Path("app.ts")) is True
        assert FileClassifier.is_analyzable(Path("README.md")) is False
        assert FileClassifier.is_analyzable(Path("image.png")) is False

    def test_get_supported_extensions(self) -> None:
        """Test getting supported extensions."""
        extensions = FileClassifier.get_supported_extensions()
        assert ".py" in extensions
        assert ".js" in extensions
        assert ".ts" in extensions
        assert len(extensions) > 10

    def test_get_analyzable_extensions(self) -> None:
        """Test getting analyzable extensions."""
        extensions = FileClassifier.get_analyzable_extensions()
        assert ".py" in extensions
        assert ".ts" in extensions
        assert ".md" not in extensions


class TestGitignoreFilter:
    """Test GitignoreFilter functionality."""

    def test_filter_initialization(self, temp_project: Path) -> None:
        """Test filter initialization with default patterns."""
        git_filter = GitignoreFilter(temp_project)
        patterns = git_filter.get_patterns()

        assert "node_modules/" in patterns
        assert ".git/" in patterns
        assert "__pycache__/" in patterns

    def test_load_gitignore(self, temp_project: Path) -> None:
        """Test loading patterns from .gitignore file."""
        git_filter = GitignoreFilter(temp_project)
        git_filter.load_gitignore(temp_project / ".gitignore")

        patterns = git_filter.get_patterns()
        assert "*.pyc" in patterns

    def test_should_ignore_node_modules(self, temp_project: Path) -> None:
        """Test ignoring node_modules directory."""
        git_filter = GitignoreFilter(temp_project)

        assert git_filter.should_ignore(temp_project / "node_modules" / "lib.js") is True
        assert git_filter.should_ignore(temp_project / "src" / "main.py") is False

    def test_should_ignore_git_directory(self, temp_project: Path) -> None:
        """Test ignoring .git directory."""
        git_filter = GitignoreFilter(temp_project)

        assert git_filter.should_ignore(temp_project / ".git" / "config") is True

    def test_should_ignore_pyc_files(self, temp_project: Path) -> None:
        """Test ignoring .pyc files."""
        git_filter = GitignoreFilter(temp_project)
        git_filter.load_gitignore(temp_project / ".gitignore")

        assert git_filter.should_ignore(temp_project / "src" / "cache.pyc") is True

    def test_filter_files(self, temp_project: Path) -> None:
        """Test filtering a list of files."""
        git_filter = GitignoreFilter(temp_project)

        files = [
            temp_project / "src" / "main.py",
            temp_project / "node_modules" / "lib.js",
            temp_project / "tests" / "test.py",
        ]

        filtered = git_filter.filter_files(files)
        assert len(filtered) == 2
        assert temp_project / "node_modules" / "lib.js" not in filtered

    def test_add_pattern(self) -> None:
        """Test adding custom patterns."""
        git_filter = GitignoreFilter(Path("/tmp"))
        git_filter.add_pattern("*.log")

        patterns = git_filter.get_patterns()
        assert "*.log" in patterns


class TestFrameworkDetector:
    """Test FrameworkDetector functionality."""

    @pytest.mark.asyncio
    async def test_detect_react_framework(self, temp_project: Path) -> None:
        """Test detecting React framework from package.json."""
        detector = FrameworkDetector(temp_project)
        result = await detector.detect()

        assert Framework.REACT in result.detected_frameworks
        assert result.primary_framework == Framework.REACT
        assert result.confidence_scores.get("react", 0.0) > 0.8

    @pytest.mark.asyncio
    async def test_detect_flask_framework(self, temp_project: Path) -> None:
        """Test detecting Flask framework from requirements.txt."""
        detector = FrameworkDetector(temp_project)
        result = await detector.detect()

        assert Framework.FLASK in result.detected_frameworks
        assert result.confidence_scores.get("flask", 0.0) > 0.8

    @pytest.mark.asyncio
    async def test_no_framework_detected(self) -> None:
        """Test when no framework is detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_project = Path(tmpdir)
            (empty_project / "src").mkdir()
            (empty_project / "src" / "main.py").write_text("print('hello')")

            detector = FrameworkDetector(empty_project)
            result = await detector.detect()

            assert len(result.detected_frameworks) == 0
            assert result.primary_framework is None

    @pytest.mark.asyncio
    async def test_multiple_frameworks_detected(self, temp_project: Path) -> None:
        """Test detecting multiple frameworks."""
        detector = FrameworkDetector(temp_project)
        result = await detector.detect()

        # Should detect both React and Flask
        assert len(result.detected_frameworks) >= 2

    @pytest.mark.asyncio
    async def test_detect_from_python_imports(self) -> None:
        """Test detecting framework from Python imports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            (project / "src").mkdir()
            (project / "src" / "app.py").write_text("from flask import Flask\napp = Flask(__name__)")

            detector = FrameworkDetector(project)
            result = await detector.detect()

            assert Framework.FLASK in result.detected_frameworks


class TestFileDiscoverer:
    """Test FileDiscoverer functionality."""

    @pytest.mark.asyncio
    async def test_discover_async(self, temp_project: Path) -> None:
        """Test asynchronous file discovery."""
        discoverer = FileDiscoverer(root_path=temp_project)
        result = await discoverer.discover_async()

        assert result.stats.total_files > 0
        assert result.stats.analyzable_files > 0
        assert result.project_path == str(temp_project)

    def test_discover_sync(self, temp_project: Path) -> None:
        """Test synchronous file discovery."""
        discoverer = FileDiscoverer(root_path=temp_project)
        result = discoverer.discover_sync()

        assert result.stats.total_files > 0
        assert result.stats.analyzable_files > 0

    @pytest.mark.asyncio
    async def test_discover_respects_gitignore(self, temp_project: Path) -> None:
        """Test that discovery respects .gitignore patterns."""
        discoverer = FileDiscoverer(root_path=temp_project, use_gitignore=True)
        result = await discoverer.discover_async()

        # Should not include node_modules or .git files
        file_paths = [f.relative_path for f in result.files]
        assert not any("node_modules" in path for path in file_paths)
        assert not any(".git" in path for path in file_paths)

    @pytest.mark.asyncio
    async def test_discover_without_gitignore(self, temp_project: Path) -> None:
        """Test discovery without gitignore filtering."""
        discoverer = FileDiscoverer(root_path=temp_project, use_gitignore=False)
        result = await discoverer.discover_async()

        # May include more files, but should still skip binaries
        assert result.stats.total_files > 0

    @pytest.mark.asyncio
    async def test_discover_with_max_depth(self, temp_project: Path) -> None:
        """Test discovery with maximum depth limit."""
        discoverer = FileDiscoverer(root_path=temp_project, max_depth=1)
        result = await discoverer.discover_async()

        # Should find files, but limited by depth
        assert result.stats.total_files > 0

    @pytest.mark.asyncio
    async def test_get_analyzable_files(self, temp_project: Path) -> None:
        """Test getting only analyzable files."""
        result = await discover_project_files(temp_project)
        analyzable_files = result.get_analyzable_files()

        assert len(analyzable_files) > 0
        assert all(f.is_analyzable for f in analyzable_files)

    @pytest.mark.asyncio
    async def test_get_files_by_type(self, temp_project: Path) -> None:
        """Test getting files by specific type."""
        result = await discover_project_files(temp_project)
        python_files = result.get_files_by_type(FileType.PYTHON)

        assert len(python_files) > 0
        assert all(f.file_type == FileType.PYTHON for f in python_files)

    @pytest.mark.asyncio
    async def test_has_framework(self, temp_project: Path) -> None:
        """Test checking for specific framework."""
        result = await discover_project_files(temp_project)

        assert result.has_framework(Framework.REACT) is True
        assert result.has_framework(Framework.FLASK) is True
        assert result.has_framework(Framework.DJANGO) is False

    @pytest.mark.asyncio
    async def test_discovery_stats(self, temp_project: Path) -> None:
        """Test discovery statistics calculation."""
        result = await discover_project_files(temp_project)

        assert result.stats.total_files > 0
        assert result.stats.analyzable_files > 0
        assert result.stats.total_size_bytes > 0
        assert result.stats.scan_duration_seconds >= 0
        assert result.stats.analyzable_percentage >= 0

    def test_get_analyzable_files_sync(self, temp_project: Path) -> None:
        """Test getting analyzable files synchronously."""
        discoverer = FileDiscoverer(root_path=temp_project)
        files = discoverer.get_analyzable_files()

        assert len(files) > 0
        assert all(isinstance(f, Path) for f in files)

    def test_get_files_by_type_sync(self, temp_project: Path) -> None:
        """Test getting files by type synchronously."""
        discoverer = FileDiscoverer(root_path=temp_project)
        python_files = discoverer.get_files_by_type(FileType.PYTHON)

        assert len(python_files) > 0
        assert all(isinstance(f, Path) for f in python_files)


class TestDiscoveryModels:
    """Test discovery model serialization."""

    @pytest.mark.asyncio
    async def test_discovery_result_to_json(self, temp_project: Path) -> None:
        """Test DiscoveryResult serialization to JSON."""
        result = await discover_project_files(temp_project)
        json_data = result.to_json()

        assert "projectPath" in json_data
        assert "files" in json_data
        assert "frameworkDetection" in json_data
        assert "stats" in json_data
        assert isinstance(json_data["files"], list)

    @pytest.mark.asyncio
    async def test_discovery_result_roundtrip(self, temp_project: Path) -> None:
        """Test DiscoveryResult JSON roundtrip."""
        from warden.analyzers.discovery.models import DiscoveryResult

        original = await discover_project_files(temp_project)
        json_data = original.to_json()
        restored = DiscoveryResult.from_json(json_data)

        assert restored.project_path == original.project_path
        assert len(restored.files) == len(original.files)
        assert restored.stats.total_files == original.stats.total_files

    def test_file_type_extension(self) -> None:
        """Test FileType extension property."""
        assert FileType.PYTHON.extension == ".py"
        assert FileType.JAVASCRIPT.extension == ".js"
        assert FileType.TYPESCRIPT.extension == ".ts"

    def test_file_type_is_analyzable(self) -> None:
        """Test FileType analyzable property."""
        assert FileType.PYTHON.is_analyzable is True
        assert FileType.JAVASCRIPT.is_analyzable is True
        assert FileType.MARKDOWN.is_analyzable is False
        assert FileType.UNKNOWN.is_analyzable is False


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_discover_empty_directory(self) -> None:
        """Test discovering files in an empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_dir = Path(tmpdir)
            result = await discover_project_files(empty_dir)

            assert result.stats.total_files == 0
            assert result.stats.analyzable_files == 0

    @pytest.mark.asyncio
    async def test_discover_nonexistent_directory(self) -> None:
        """Test discovering files in a nonexistent directory."""
        nonexistent = Path("/nonexistent/directory")
        discoverer = FileDiscoverer(root_path=nonexistent)

        # Should handle gracefully (no exception)
        result = await discoverer.discover_async()
        assert result.stats.total_files == 0

    def test_classify_file_with_no_extension(self) -> None:
        """Test classifying files without extensions."""
        file_type = FileClassifier.classify(Path("Makefile"))
        assert file_type == FileType.UNKNOWN

    def test_gitignore_with_relative_path(self, temp_project: Path) -> None:
        """Test gitignore with relative paths."""
        git_filter = GitignoreFilter(temp_project)

        relative_path = Path("src/main.py")
        assert git_filter.should_ignore(relative_path) is False

    @pytest.mark.asyncio
    async def test_framework_detection_with_malformed_json(self) -> None:
        """Test framework detection with malformed package.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            (project / "package.json").write_text("{ invalid json }")

            detector = FrameworkDetector(project)
            result = await detector.detect()

            # Should handle gracefully
            assert isinstance(result.detected_frameworks, list)
