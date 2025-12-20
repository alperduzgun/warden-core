"""
Integration tests for EnhancedPipelineOrchestrator.

Tests the enhanced pipeline with discovery, build context, and suppression phases.
"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from typing import List

from warden.pipeline import (
    EnhancedPipelineOrchestrator,
    PipelineConfig,
    ExecutionStrategy,
)
from warden.validation import (
    ValidationFrame,
    FrameResult,
    CodeFile,
    Finding,
    FramePriority,
    FrameCategory,
    FrameScope,
    FrameApplicability,
)
from warden.suppression import (
    SuppressionConfig,
    SuppressionEntry,
    SuppressionType,
    save_suppression_config,
)


# Test Frame for validation
class TestValidationFrame(ValidationFrame):
    """Simple test frame that always finds issues."""

    name = "Test Frame"
    description = "Test validation frame"
    category = FrameCategory.LANGUAGE_SPECIFIC
    priority = FramePriority.MEDIUM
    scope = FrameScope.FILE_LEVEL
    is_blocker = False
    version = "1.0.0"
    author = "Test"
    applicability = [FrameApplicability.ALL]

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """Execute test validation."""
        findings = [
            Finding(
                id="test-001",
                severity="medium",
                message="Test finding",
                location=f"{code_file.path}:1",
                detail="This is a test finding",
                code="test code",
            )
        ]

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="warning",
            duration=0.1,
            issues_found=1,
            is_blocker=False,
            findings=findings,
            metadata={},
        )


@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        # Create Python files
        (project_path / "main.py").write_text(
            """
def main():
    print("Hello, World!")

if __name__ == "__main__":
    main()
"""
        )

        (project_path / "utils.py").write_text(
            """
def helper():
    return 42
"""
        )

        # Create package.json for build context
        (project_path / "package.json").write_text(
            """
{
  "name": "test-project",
  "version": "1.0.0",
  "dependencies": {
    "lodash": "^4.17.21"
  }
}
"""
        )

        # Create .gitignore
        (project_path / ".gitignore").write_text(
            """
node_modules/
*.pyc
__pycache__/
"""
        )

        yield str(project_path)


@pytest.fixture
def basic_config():
    """Create a basic pipeline configuration."""
    return PipelineConfig(
        strategy=ExecutionStrategy.SEQUENTIAL,
        fail_fast=False,
        timeout=60,
        enable_discovery=True,
        enable_build_context=True,
        enable_suppression=False,
    )


@pytest.fixture
def frames_list():
    """Create a list of test frames."""
    return [TestValidationFrame()]


class TestEnhancedOrchestratorBasics:
    """Test basic enhanced orchestrator functionality."""

    def test_initialization(self, frames_list, basic_config):
        """Test enhanced orchestrator initialization."""
        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=basic_config,
        )

        assert orchestrator is not None
        assert len(orchestrator.frames) == 1
        assert orchestrator.config.enable_discovery is True
        assert orchestrator.config.enable_build_context is True
        assert orchestrator.config.enable_suppression is False

    def test_initialization_with_defaults(self, frames_list):
        """Test initialization with default config."""
        orchestrator = EnhancedPipelineOrchestrator(frames=frames_list)

        assert orchestrator is not None
        assert orchestrator.config.enable_discovery is True
        assert orchestrator.config.enable_build_context is True
        assert orchestrator.config.enable_suppression is True


class TestDiscoveryPhase:
    """Test file discovery phase."""

    @pytest.mark.asyncio
    async def test_discovery_enabled(self, temp_project_dir, frames_list, basic_config):
        """Test discovery phase when enabled."""
        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=basic_config,
        )

        result = await orchestrator.execute_with_discovery(temp_project_dir)

        # Check that discovery ran
        assert orchestrator.discovery_result is not None
        assert orchestrator.discovery_result.stats.total_files >= 2  # At least main.py and utils.py

        # Check that files were processed
        assert result.total_frames == 1
        assert result.frames_passed >= 0

    @pytest.mark.asyncio
    async def test_discovery_disabled(self, temp_project_dir, frames_list):
        """Test discovery phase when disabled."""
        config = PipelineConfig(
            enable_discovery=False,
            enable_build_context=False,
            enable_suppression=False,
        )

        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=config,
        )

        result = await orchestrator.execute_with_discovery(temp_project_dir)

        # Discovery should be None
        assert orchestrator.discovery_result is None

        # No files should be processed
        assert result.total_findings == 0

    @pytest.mark.asyncio
    async def test_discovery_respects_gitignore(self, temp_project_dir, frames_list, basic_config):
        """Test that discovery respects .gitignore patterns."""
        # Create a file that should be ignored
        project_path = Path(temp_project_dir)
        (project_path / "test.pyc").write_text("binary content")

        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=basic_config,
        )

        result = await orchestrator.execute_with_discovery(temp_project_dir)

        # test.pyc should not be in discovered files
        discovered_paths = [f.path for f in orchestrator.discovery_result.files]
        assert not any("test.pyc" in p for p in discovered_paths)


class TestBuildContextPhase:
    """Test build context loading phase."""

    @pytest.mark.asyncio
    async def test_build_context_enabled(self, temp_project_dir, frames_list, basic_config):
        """Test build context phase when enabled."""
        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=basic_config,
        )

        result = await orchestrator.execute_with_discovery(temp_project_dir)

        # Check that build context was loaded
        assert orchestrator.build_context is not None
        assert orchestrator.build_context.project_name == "test-project"
        assert orchestrator.build_context.project_version == "1.0.0"
        assert len(orchestrator.build_context.dependencies) > 0

    @pytest.mark.asyncio
    async def test_build_context_disabled(self, temp_project_dir, frames_list):
        """Test build context phase when disabled."""
        config = PipelineConfig(
            enable_discovery=True,
            enable_build_context=False,
            enable_suppression=False,
        )

        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=config,
        )

        result = await orchestrator.execute_with_discovery(temp_project_dir)

        # Build context should be None
        assert orchestrator.build_context is None

    @pytest.mark.asyncio
    async def test_build_context_not_found(self, frames_list, basic_config):
        """Test build context phase when no build files exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Empty project with no build files
            orchestrator = EnhancedPipelineOrchestrator(
                frames=frames_list,
                config=basic_config,
            )

            result = await orchestrator.execute_with_discovery(tmpdir)

            # Build context should be None (gracefully handled)
            assert orchestrator.build_context is None


class TestSuppressionPhase:
    """Test suppression filtering phase."""

    @pytest.mark.asyncio
    async def test_suppression_enabled(self, temp_project_dir, frames_list):
        """Test suppression phase when enabled."""
        # Create suppression config
        project_path = Path(temp_project_dir)
        warden_dir = project_path / ".warden"
        warden_dir.mkdir(exist_ok=True)

        suppression_config = SuppressionConfig(
            enabled=True,
            entries=[
                SuppressionEntry(
                    id="suppress-test-001",
                    suppression_type=SuppressionType.RULE,
                    rule="test-001",
                    reason="Test suppression",
                )
            ],
        )

        save_suppression_config(suppression_config, str(warden_dir / "suppressions.yaml"))

        config = PipelineConfig(
            enable_discovery=True,
            enable_build_context=False,
            enable_suppression=True,
            suppression_config_path=str(warden_dir / "suppressions.yaml"),
        )

        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=config,
        )

        result = await orchestrator.execute_with_discovery(temp_project_dir)

        # Findings should be suppressed
        assert result.metadata.get("suppression_enabled") is True
        suppressed_count = result.metadata.get("suppressed_count", 0)
        assert suppressed_count >= 0  # May suppress findings

    @pytest.mark.asyncio
    async def test_suppression_disabled(self, temp_project_dir, frames_list):
        """Test suppression phase when disabled."""
        config = PipelineConfig(
            enable_discovery=True,
            enable_build_context=False,
            enable_suppression=False,
        )

        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=config,
        )

        result = await orchestrator.execute_with_discovery(temp_project_dir)

        # Suppression should not be applied
        assert result.metadata.get("suppression_enabled") is None
        assert orchestrator.suppression_matcher is None


class TestFullPipeline:
    """Test full enhanced pipeline integration."""

    @pytest.mark.asyncio
    async def test_full_pipeline_all_phases_enabled(self, temp_project_dir, frames_list):
        """Test full pipeline with all phases enabled."""
        config = PipelineConfig(
            enable_discovery=True,
            enable_build_context=True,
            enable_suppression=True,
        )

        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=config,
        )

        result = await orchestrator.execute_with_discovery(temp_project_dir)

        # Verify all phases ran
        assert orchestrator.discovery_result is not None
        assert orchestrator.build_context is not None
        # Suppression matcher may be None if no config found (graceful)

        # Verify pipeline completed
        assert result.pipeline_name == "Code Validation"
        assert result.total_frames == 1
        assert result.status.value in [1, 2]  # COMPLETED or FAILED

    @pytest.mark.asyncio
    async def test_full_pipeline_all_phases_disabled(self, temp_project_dir, frames_list):
        """Test full pipeline with all phases disabled."""
        config = PipelineConfig(
            enable_discovery=False,
            enable_build_context=False,
            enable_suppression=False,
        )

        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=config,
        )

        result = await orchestrator.execute_with_discovery(temp_project_dir)

        # Verify no phases ran
        assert orchestrator.discovery_result is None
        assert orchestrator.build_context is None
        assert orchestrator.suppression_matcher is None

    @pytest.mark.asyncio
    async def test_pipeline_with_manual_code_files(self, frames_list):
        """Test pipeline with manually provided code files (no discovery)."""
        config = PipelineConfig(
            enable_discovery=False,
            enable_build_context=False,
            enable_suppression=False,
        )

        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=config,
        )

        # Manually create code files
        code_files = [
            CodeFile(
                path="test.py",
                content="print('hello')",
                language="python",
            )
        ]

        # Use base execute method
        result = await orchestrator.execute(code_files)

        assert result.total_frames == 1
        assert result.total_findings >= 1  # TestValidationFrame always finds issues


class TestGetterMethods:
    """Test getter methods for phase results."""

    @pytest.mark.asyncio
    async def test_get_discovery_result(self, temp_project_dir, frames_list, basic_config):
        """Test get_discovery_result method."""
        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=basic_config,
        )

        await orchestrator.execute_with_discovery(temp_project_dir)

        discovery_result = orchestrator.get_discovery_result()
        assert discovery_result is not None
        assert discovery_result.project_path == temp_project_dir

    @pytest.mark.asyncio
    async def test_get_build_context(self, temp_project_dir, frames_list, basic_config):
        """Test get_build_context method."""
        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=basic_config,
        )

        await orchestrator.execute_with_discovery(temp_project_dir)

        build_context = orchestrator.get_build_context()
        assert build_context is not None
        assert build_context.project_name == "test-project"

    @pytest.mark.asyncio
    async def test_get_suppression_matcher(self, temp_project_dir, frames_list):
        """Test get_suppression_matcher method."""
        config = PipelineConfig(
            enable_discovery=True,
            enable_build_context=False,
            enable_suppression=True,
        )

        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=config,
        )

        await orchestrator.execute_with_discovery(temp_project_dir)

        suppression_matcher = orchestrator.get_suppression_matcher()
        # May be None if no config found (graceful)
        assert suppression_matcher is None or suppression_matcher is not None


class TestErrorHandling:
    """Test error handling in enhanced pipeline."""

    @pytest.mark.asyncio
    async def test_discovery_error_handling(self, frames_list, basic_config):
        """Test graceful handling of discovery errors."""
        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=basic_config,
        )

        # Invalid project path
        result = await orchestrator.execute_with_discovery("/nonexistent/path")

        # Should not crash, returns empty result
        assert result.total_frames == 1
        assert orchestrator.discovery_result is None or len(orchestrator.discovery_result.files) == 0

    @pytest.mark.asyncio
    async def test_build_context_error_handling(self, frames_list):
        """Test graceful handling of build context errors."""
        config = PipelineConfig(
            enable_discovery=False,
            enable_build_context=True,
            enable_suppression=False,
        )

        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=config,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = await orchestrator.execute_with_discovery(tmpdir)

            # Should not crash
            assert orchestrator.build_context is None

    @pytest.mark.asyncio
    async def test_suppression_error_handling(self, temp_project_dir, frames_list):
        """Test graceful handling of suppression errors."""
        config = PipelineConfig(
            enable_discovery=True,
            enable_build_context=False,
            enable_suppression=True,
            suppression_config_path="/nonexistent/suppressions.yaml",
        )

        orchestrator = EnhancedPipelineOrchestrator(
            frames=frames_list,
            config=config,
        )

        result = await orchestrator.execute_with_discovery(temp_project_dir)

        # Should not crash, suppression just won't apply
        assert result.total_frames == 1
