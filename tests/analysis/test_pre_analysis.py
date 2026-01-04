"""
Tests for PRE-ANALYSIS Phase components.

Tests project context detection, file context analysis, and
false positive suppression mechanisms.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import tempfile
import os

from warden.analysis.domain.project_context import (
    ProjectContext,
    ProjectType,
    Framework,
    Architecture,
    TestFramework,
    BuildTool,
)
from warden.analysis.domain.file_context import (
    FileContext,
    FileContextInfo,
    PreAnalysisResult,
)
from warden.analysis.application.project_structure_analyzer import ProjectStructureAnalyzer
from warden.analysis.application.file_context_analyzer import FileContextAnalyzer
from warden.analysis.application.pre_analysis_phase import PreAnalysisPhase
from warden.validation.domain.frame import CodeFile


class TestFileContextAnalyzer:
    """Tests for FileContextAnalyzer."""

    def setup_method(self):
        """Setup test fixtures."""
        self.analyzer = FileContextAnalyzer()

    def test_detect_test_file_by_path(self):
        """Test files should be detected by path patterns."""
        test_paths = [
            Path("tests/test_security.py"),
            Path("test_utils.py"),
            Path("src/utils_test.py"),
            Path("spec/feature_spec.rb"),
            Path("__tests__/component.test.js"),
        ]

        for path in test_paths:
            result = self.analyzer.analyze_file(path)
            assert result.context == FileContext.TEST
            assert result.confidence > 0.9
            assert "sql_injection" in result.suppressed_issues

    def test_detect_example_file(self):
        """Example files should be detected correctly."""
        example_paths = [
            Path("examples/demo.py"),
            Path("demo/sample.js"),
            Path("tutorials/lesson1.py"),
        ]

        for path in example_paths:
            result = self.analyzer.analyze_file(path)
            assert result.context == FileContext.EXAMPLE
            assert result.confidence > 0.9

    def test_detect_framework_file(self):
        """Framework files should be detected."""
        framework_paths = [
            Path(".warden/frames/security_frame.py"),
            Path("src/warden/validation/frames/chaos_frame.py"),
        ]

        for path in framework_paths:
            result = self.analyzer.analyze_file(path)
            assert result.context == FileContext.FRAMEWORK
            assert result.confidence > 0.9

    def test_detect_vendor_file(self):
        """Vendor files should be detected and marked for skipping."""
        vendor_paths = [
            Path("vendor/library.py"),
            Path("node_modules/package/index.js"),
            Path("third_party/tool.py"),
        ]

        for path in vendor_paths:
            result = self.analyzer.analyze_file(path)
            assert result.context == FileContext.VENDOR
            assert result.is_vendor
            assert result.suppressed_issues == ["*"] or len(result.suppressed_issues) > 0

    def test_detect_production_file_default(self):
        """Unknown files default to production context."""
        prod_path = Path("src/api/users.py")
        result = self.analyzer.analyze_file(prod_path)

        assert result.context == FileContext.PRODUCTION
        assert result.suppressed_issues == []
        assert not result.is_vendor
        assert not result.is_generated

    def test_should_suppress_issue(self):
        """Test issue suppression logic."""
        # Test file with SQL injection
        test_file = FileContextInfo(
            file_path="test_db.py",
            context=FileContext.TEST,
            confidence=0.95,
            detection_method="path",
        )

        assert test_file.should_suppress_issue("sql_injection")
        assert test_file.should_suppress_issue("hardcoded_password")
        assert not test_file.should_suppress_issue("syntax_error")  # Not in suppression list

        # Production file should not suppress
        prod_file = FileContextInfo(
            file_path="api.py",
            context=FileContext.PRODUCTION,
            confidence=0.95,
            detection_method="default",
        )

        assert not prod_file.should_suppress_issue("sql_injection")
        assert not prod_file.should_suppress_issue("hardcoded_password")

    def test_context_weights(self):
        """Test that different contexts have different weights."""
        test_file = self.analyzer.analyze_file(Path("test_utils.py"))
        prod_file = self.analyzer.analyze_file(Path("src/api.py"))

        # Test files should have high testability weight
        assert test_file.weights.weights["testability"] > 0.5
        assert test_file.weights.weights["complexity"] < 0.2

        # Production files should have balanced weights
        assert prod_file.weights.weights["complexity"] > 0.2
        assert prod_file.weights.weights["maintainability"] > 0.15

    @patch("builtins.open", create=True)
    def test_detect_by_content(self, mock_open):
        """Test content-based detection."""
        # Mock file with test content
        test_content = """
import pytest
from unittest import TestCase

class TestUserAPI(TestCase):
    def test_create_user(self):
        assert True
"""
        mock_open.return_value.__enter__.return_value.read.return_value = test_content

        result = self.analyzer.analyze_file(Path("api.py"))  # Name doesn't suggest test
        assert result.context == FileContext.TEST
        assert result.detection_method == "content"

    @patch("builtins.open", create=True)
    def test_detect_by_metadata(self, mock_open):
        """Test metadata-based detection."""
        # File with explicit context declaration
        content = """
# warden-context: example
# This is an example file for demonstration

def demo_function():
    pass
"""
        mock_open.return_value.__enter__.return_value.read.return_value = content

        result = self.analyzer.analyze_file(Path("utils.py"))
        assert result.context == FileContext.EXAMPLE
        assert result.confidence == 1.0
        assert result.detection_method == "metadata"


class TestProjectStructureAnalyzer:
    """Tests for ProjectStructureAnalyzer."""

    @pytest.mark.asyncio
    async def test_detect_python_project(self):
        """Test Python project detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create Python project structure
            (project_root / "pyproject.toml").write_text("[tool.poetry]")
            (project_root / "src").mkdir()
            (project_root / "tests").mkdir()
            (project_root / "src" / "main.py").write_text("print('hello')")

            analyzer = ProjectStructureAnalyzer(project_root)
            context = await analyzer.analyze_async()

            assert context.project_type in [ProjectType.APPLICATION, ProjectType.LIBRARY]
            # Since we didn't add dependencies in pyproject.toml, it might not detect build tool as poetry
            # relying on default file detection
            assert "pyproject.toml" in context.config_files
            assert context.primary_language == "python"

    @pytest.mark.asyncio
    async def test_detect_fastapi_framework(self):
        """Test FastAPI framework detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create FastAPI indicators
            (project_root / "requirements.txt").write_text("fastapi==0.100.0\nuvicorn")
            (project_root / "app.py").write_text("from fastapi import FastAPI")

            analyzer = ProjectStructureAnalyzer(project_root)
            context = await analyzer.analyze_async()

            assert context.framework == Framework.FASTAPI
            assert context.project_type == ProjectType.API

    @pytest.mark.asyncio
    async def test_detect_test_framework(self):
        """Test framework detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create pytest indicators
            (project_root / "pytest.ini").write_text("[tool:pytest]")
            (project_root / "tests").mkdir()

            analyzer = ProjectStructureAnalyzer(project_root)
            context = await analyzer.analyze_async()

            assert context.test_framework == TestFramework.PYTEST

    @pytest.mark.asyncio
    async def test_detect_special_directories(self):
        """Test special directory detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create special directories
            (project_root / "vendor").mkdir()
            (project_root / "tests").mkdir()
            (project_root / "docs").mkdir()
            (project_root / "migrations").mkdir()

            analyzer = ProjectStructureAnalyzer(project_root)
            context = await analyzer.analyze_async()

            assert "vendor" in context.special_dirs
            assert "test" in context.special_dirs
            assert "docs" in context.special_dirs


class TestPreAnalysisPhase:
    """Tests for PreAnalysisPhase orchestrator."""

    @pytest.mark.asyncio
    async def test_execute_pre_analysis(self):
        """Test complete PRE-ANALYSIS execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create project structure
            (project_root / "src").mkdir()
            (project_root / "tests").mkdir()
            (project_root / "src" / "api.py").write_text("def get_user(): pass")
            (project_root / "tests" / "test_api.py").write_text("def test_user(): pass")

            # Create code files
            code_files = [
                CodeFile(path=str(project_root / "src" / "api.py"), content="def get_user(): pass", language="python"),
                CodeFile(path=str(project_root / "tests" / "test_api.py"), content="def test_user(): pass", language="python"),
            ]

            phase = PreAnalysisPhase(project_root)
            result = await phase.execute(code_files)

            assert isinstance(result, PreAnalysisResult)
            assert result.total_files_analyzed == 2
            assert "production" in result.files_by_context
            assert "test" in result.files_by_context

    @pytest.mark.asyncio
    async def test_file_context_distribution(self):
        """Test that files are correctly distributed by context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create mixed file structure
            (project_root / "src").mkdir()
            (project_root / "tests").mkdir()
            (project_root / "examples").mkdir()

            files = [
                ("src/main.py", FileContext.PRODUCTION),
                ("tests/test_main.py", FileContext.TEST),
                ("examples/demo.py", FileContext.EXAMPLE),
            ]

            code_files = []
            for path, expected_context in files:
                full_path = project_root / path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text("# code")
                code_files.append(CodeFile(path=str(full_path), content="# code", language="python"))

            phase = PreAnalysisPhase(project_root)
            result = await phase.execute(code_files)

            # Check context distribution
            assert result.files_by_context.get("production", 0) >= 1
            assert result.files_by_context.get("test", 0) >= 1
            assert result.files_by_context.get("example", 0) >= 1

    @pytest.mark.asyncio
    async def test_suppression_configuration(self):
        """Test that suppressions are properly configured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create test file
            test_file = project_root / "test_security.py"
            test_file.write_text("def test_sql_injection(): pass")

            code_files = [CodeFile(path=str(test_file), content="def test_sql_injection(): pass", language="python")]

            phase = PreAnalysisPhase(project_root)
            result = await phase.execute(code_files)

            # Check suppression configuration
            context_info = result.file_contexts.get(str(test_file))
            assert context_info is not None
            assert context_info.context == FileContext.TEST
            assert "sql_injection" in context_info.suppressed_issues

    @pytest.mark.asyncio
    async def test_should_skip_file(self):
        """Test file skipping logic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create vendor file
            vendor_dir = project_root / "vendor"
            vendor_dir.mkdir()
            vendor_file = vendor_dir / "library.py"
            vendor_file.write_text("# third party")

            # Create documentation file
            doc_file = project_root / "README.md"
            doc_file.write_text("# Documentation")

            code_files = [
                CodeFile(path=str(vendor_file), content="# third party", language="python"),
                CodeFile(path=str(doc_file), content="# Documentation", language="python"),
            ]

            phase = PreAnalysisPhase(project_root)
            result = await phase.execute(code_files)

            # Vendor file should be skipped
            assert phase.should_skip_file(str(vendor_file), result)

            # Documentation file should be skipped
            assert phase.should_skip_file(str(doc_file), result)

    @pytest.mark.asyncio
    async def test_progress_callback(self):
        """Test that progress callbacks are invoked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "test.py").write_text("print('test')")

            progress_events = []

            def progress_callback(event, data):
                progress_events.append((event, data))

            code_files = [CodeFile(path=str(project_root / "test.py"), content="print('test')", language="python")]

            phase = PreAnalysisPhase(project_root, progress_callback)
            await phase.execute(code_files)

            # Check that progress events were fired
            event_names = [event for event, _ in progress_events]
            assert "pre_analysis_started" in event_names
            assert "pre_analysis_completed" in event_names


    @pytest.mark.asyncio
    async def test_end_to_end_context_awareness(self):
        """End-to-end test of context-aware analysis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create a mixed project structure
            src_dir = project_root / "src"
            test_dir = project_root / "tests"
            src_dir.mkdir()
            test_dir.mkdir()

            # Production file with SQL injection
            prod_file = src_dir / "database.py"
            prod_file.write_text("""
def get_user(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"  # SQL injection!
    return execute(query)
""")

            # Test file with intentional SQL injection
            test_file = test_dir / "test_sql.py"
            test_file.write_text("""
import pytest

def test_sql_injection_detection():
    # Intentional SQL injection for testing
    query = f"SELECT * FROM users WHERE id = {user_input}"
    assert detect_injection(query) == True
""")

            code_files = [
                CodeFile(path=str(prod_file), content=prod_file.read_text(), language="python"),
                CodeFile(path=str(test_file), content=test_file.read_text(), language="python"),
            ]

            # Run PRE-ANALYSIS
            phase = PreAnalysisPhase(project_root)
            result = await phase.execute(code_files)

            # Production file should NOT suppress SQL injection
            prod_context = result.file_contexts[str(prod_file)]
            assert prod_context.context == FileContext.PRODUCTION
            assert not prod_context.should_suppress_issue("sql_injection")

            # Test file SHOULD suppress SQL injection
            test_context = result.file_contexts[str(test_file)]
            assert test_context.context == FileContext.TEST
            assert test_context.should_suppress_issue("sql_injection")

            # Weights should be different
            assert prod_context.weights.weights["complexity"] > test_context.weights.weights["complexity"]
            assert test_context.weights.weights["testability"] > prod_context.weights.weights["testability"]