"""E2E tests for warden install CLI command.

Tests the REAL install pipeline using local path dependencies.
No mocks — exercises FrameFetcher, lockfile, integrity verification, etc.

Test fixture structure:
  fixtures/
    sample_frame/           # A minimal frame package
      frame.py              # Frame implementation
      __init__.py
      warden.manifest.yaml  # Package manifest
      rules/
        sample_rule.yaml    # Bundled rules
"""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from warden.main import app


FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def frame_package(tmp_path):
    """Create a minimal frame package for local install testing."""
    pkg = tmp_path / "my_test_frame"
    pkg.mkdir()

    # Frame code
    (pkg / "__init__.py").write_text('"""Test frame package."""\n')
    (pkg / "frame.py").write_text('''"""Test validation frame."""

class TestFrame:
    """A minimal test frame for install testing."""

    name = "test_frame"
    priority = "low"

    def validate(self, code):
        return []
''')

    # Manifest
    (pkg / "warden.manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "my_test_frame",
                "version": "1.0.0",
                "description": "Test frame for E2E install testing",
                "runtime": {"module": "frame.py", "class": "TestFrame"},
            }
        )
    )

    # Bundled rules
    rules_dir = pkg / "rules"
    rules_dir.mkdir()
    (rules_dir / "test_rule.yaml").write_text(
        yaml.dump(
            {
                "rules": [
                    {
                        "id": "test-no-debug",
                        "name": "No debug statements",
                        "severity": "info",
                        "pattern": "breakpoint\\(\\)",
                        "language": "python",
                        "enabled": True,
                    }
                ]
            }
        )
    )

    return pkg


@pytest.fixture
def second_frame_package(tmp_path):
    """Create a second minimal frame package for multi-dependency testing."""
    pkg = tmp_path / "another_test_frame"
    pkg.mkdir()

    (pkg / "__init__.py").write_text('"""Second test frame package."""\n')
    (pkg / "frame.py").write_text('''"""Another test validation frame."""

class AnotherFrame:
    """A second minimal test frame."""

    name = "another_frame"
    priority = "medium"

    def validate(self, code):
        return []
''')

    (pkg / "warden.manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "another_test_frame",
                "version": "1.0.0",
                "description": "Second test frame",
                "runtime": {"module": "frame.py", "class": "AnotherFrame"},
            }
        )
    )

    return pkg


@pytest.fixture
def install_project(tmp_path, frame_package):
    """Create a project with local path dependencies for install testing."""
    project = tmp_path / "install_test_project"
    project.mkdir()

    warden_dir = project / ".warden"
    warden_dir.mkdir()

    # Config with local path dependency
    config = {
        "version": "2.0",
        "project": {"name": "install-test", "type": "backend", "language": "python"},
        "dependencies": {"my_test_frame": {"path": str(frame_package)}},
        "frames": {"enabled": ["security"]},
        "llm": {"provider": "ollama", "model": "qwen2.5-coder:3b"},
    }
    (warden_dir / "config.yaml").write_text(yaml.dump(config, default_flow_style=False))

    return project


@pytest.fixture
def multi_dep_project(tmp_path, frame_package, second_frame_package):
    """Create a project with multiple local path dependencies."""
    project = tmp_path / "multi_dep_project"
    project.mkdir()

    warden_dir = project / ".warden"
    warden_dir.mkdir()

    config = {
        "version": "2.0",
        "project": {"name": "multi-dep-test", "type": "backend", "language": "python"},
        "dependencies": {
            "my_test_frame": {"path": str(frame_package)},
            "another_test_frame": {"path": str(second_frame_package)},
        },
        "frames": {"enabled": ["security"]},
        "llm": {"provider": "ollama", "model": "qwen2.5-coder:3b"},
    }
    (warden_dir / "config.yaml").write_text(yaml.dump(config, default_flow_style=False))

    return project


# ============================================================================
# TestInstallFromLocalPath - Core happy path
# ============================================================================
@pytest.mark.e2e
class TestInstallFromLocalPath:
    """Test install command with local path dependencies."""

    def test_install_help(self, runner):
        """Install command shows help."""
        result = runner.invoke(app, ["install", "--help"])
        assert result.exit_code == 0
        assert "install" in result.stdout.lower()
        assert "--force-update" in result.stdout.lower()

    def test_install_all_from_config(self, runner, install_project, monkeypatch):
        """warden install reads config and installs local frame."""
        monkeypatch.chdir(install_project)

        result = runner.invoke(app, ["install"])

        # Should succeed
        assert result.exit_code == 0

        # Check output for success indicators
        stdout = result.stdout.lower()
        assert "installing" in stdout or "done" in stdout or "success" in stdout

    def test_install_creates_frame_directory(self, runner, install_project, monkeypatch):
        """Install creates .warden/frames/my_test_frame/ directory."""
        monkeypatch.chdir(install_project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        # Verify frame directory exists
        frame_dir = install_project / ".warden" / "frames" / "my_test_frame"
        assert frame_dir.exists(), f"Frame directory not created at {frame_dir}"
        assert frame_dir.is_dir()

        # Verify essential files copied
        assert (frame_dir / "frame.py").exists()
        assert (frame_dir / "__init__.py").exists()
        assert (frame_dir / "warden.manifest.yaml").exists()

    def test_install_creates_lockfile(self, runner, install_project, monkeypatch):
        """Install creates warden.lock with content hash."""
        monkeypatch.chdir(install_project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        # Verify lockfile exists
        lockfile = install_project / "warden.lock"
        assert lockfile.exists(), "warden.lock not created"

        # Load and verify lockfile structure
        with open(lockfile) as f:
            lock_data = yaml.safe_load(f)

        assert "packages" in lock_data
        assert "my_test_frame" in lock_data["packages"]

        pkg_entry = lock_data["packages"]["my_test_frame"]
        assert "content_hash" in pkg_entry
        assert pkg_entry["content_hash"].startswith("sha256:")
        assert "path" in pkg_entry

    def test_install_copies_bundled_rules(self, runner, install_project, monkeypatch):
        """Install copies rules from frame's rules/ directory to .warden/rules/."""
        monkeypatch.chdir(install_project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        # Verify bundled rule copied
        rules_dir = install_project / ".warden" / "rules"
        assert rules_dir.exists()

        rule_file = rules_dir / "test_rule.yaml"
        assert rule_file.exists(), f"Bundled rule not copied to {rule_file}"

        # Verify rule content
        with open(rule_file) as f:
            rules = yaml.safe_load(f)

        assert "rules" in rules
        assert len(rules["rules"]) == 1
        assert rules["rules"][0]["id"] == "test-no-debug"

    def test_install_manifest_preserved(self, runner, install_project, monkeypatch):
        """Install preserves manifest.yaml in installed frame."""
        monkeypatch.chdir(install_project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        manifest = install_project / ".warden" / "frames" / "my_test_frame" / "warden.manifest.yaml"
        assert manifest.exists(), "Manifest not preserved after install"

        with open(manifest) as f:
            data = yaml.safe_load(f)

        assert data["name"] == "my_test_frame"
        assert data["version"] == "1.0.0"

    def test_install_shows_success_output(self, runner, install_project, monkeypatch):
        """Install command shows success summary with installed package names."""
        monkeypatch.chdir(install_project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        stdout = result.stdout.lower()
        # Should contain success indicators
        assert "done" in stdout or "success" in stdout or "installed" in stdout

        # Should mention the frame name
        assert "my_test_frame" in stdout


# ============================================================================
# TestInstallSpecificFrame - Specific frame by ID
# ============================================================================
@pytest.mark.e2e
class TestInstallSpecificFrame:
    """Test installing a specific frame by ID."""

    def test_install_specific_frame_from_hub(self, runner, tmp_path, monkeypatch):
        """Install specific frame by ID goes to registry/hub (requires network).

        This test verifies that the command structure works, not actual registry fetch.
        We expect it to fail gracefully since we don't have a real hub connection.
        """
        project = tmp_path / "project"
        project.mkdir()
        warden_dir = project / ".warden"
        warden_dir.mkdir()

        # Minimal config (no dependencies)
        config = {
            "version": "2.0",
            "project": {"name": "test", "type": "backend", "language": "python"},
            "llm": {"provider": "ollama", "model": "qwen2.5-coder:3b"},
        }
        (warden_dir / "config.yaml").write_text(yaml.dump(config))

        monkeypatch.chdir(project)

        # Try to install from hub (will fail due to no registry.json, but tests CLI path)
        result = runner.invoke(app, ["install", "some_frame_id"])

        # Should exit with error (no hub available)
        # CLI structure is correct if it attempts to fetch
        stdout_lower = result.stdout.lower()

        # Either shows "installing from hub" or fails with registry error
        # This tests that the specific frame code path works
        assert (
            "installing" in stdout_lower
            or "warden hub" in stdout_lower
            or "registry" in stdout_lower
            or "failed" in stdout_lower
            or result.exit_code != 0
        ), f"Expected hub-related message or error, got: {result.stdout}"


# ============================================================================
# TestInstallLockfile - Integrity and lockfile behavior
# ============================================================================
@pytest.mark.e2e
class TestInstallLockfile:
    """Test lockfile integrity verification and behavior."""

    def test_install_lockfile_has_content_hash(self, runner, install_project, monkeypatch):
        """Lockfile contains sha256 hash for integrity verification."""
        monkeypatch.chdir(install_project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        lockfile = install_project / "warden.lock"
        with open(lockfile) as f:
            lock_data = yaml.safe_load(f)

        pkg = lock_data["packages"]["my_test_frame"]
        assert "content_hash" in pkg
        assert pkg["content_hash"].startswith("sha256:")
        assert len(pkg["content_hash"]) > 10  # Real hash value

    def test_install_idempotent(self, runner, install_project, monkeypatch):
        """Running install twice produces same result (idempotent)."""
        monkeypatch.chdir(install_project)

        # First install
        result1 = runner.invoke(app, ["install"])
        assert result1.exit_code == 0

        lockfile = install_project / "warden.lock"
        with open(lockfile) as f:
            lock1 = yaml.safe_load(f)

        # Second install
        result2 = runner.invoke(app, ["install"])
        assert result2.exit_code == 0

        with open(lockfile) as f:
            lock2 = yaml.safe_load(f)

        # Lockfile should be identical
        assert lock1 == lock2, "Lockfile changed on second install (not idempotent)"

    def test_install_force_update_reinstalls(self, runner, install_project, monkeypatch):
        """--force-update re-fetches even if locked."""
        monkeypatch.chdir(install_project)

        # First install
        result1 = runner.invoke(app, ["install"])
        assert result1.exit_code == 0

        # Modify installed frame to simulate drift
        frame_dir = install_project / ".warden" / "frames" / "my_test_frame"
        (frame_dir / "extra_file.txt").write_text("extra content")

        # Normal install should skip (steady state verification)
        result2 = runner.invoke(app, ["install"])
        assert result2.exit_code == 0

        # Force update should reinstall
        result3 = runner.invoke(app, ["install", "--force-update"])
        assert result3.exit_code == 0

        # Extra file should be gone (reinstalled from source)
        assert not (frame_dir / "extra_file.txt").exists(), "Force update did not reinstall from scratch"

    def test_install_detects_drift(self, runner, install_project, monkeypatch):
        """Install detects drift and reinstalls to restore steady state."""
        monkeypatch.chdir(install_project)

        # First install
        result1 = runner.invoke(app, ["install"])
        assert result1.exit_code == 0

        # Corrupt installed frame (simulate drift)
        frame_dir = install_project / ".warden" / "frames" / "my_test_frame"
        frame_file = frame_dir / "frame.py"
        original_content = frame_file.read_text()
        frame_file.write_text("# CORRUPTED\n" + original_content)

        # Next install should detect drift and reinstall
        result2 = runner.invoke(app, ["install"])
        assert result2.exit_code == 0

        # File should be restored to original
        restored_content = frame_file.read_text()
        assert "# CORRUPTED" not in restored_content, "Drift not detected or file not restored"


# ============================================================================
# TestInstallEdgeCases - Edge cases and error conditions
# ============================================================================
@pytest.mark.e2e
class TestInstallEdgeCases:
    """Test edge cases, error conditions, and validation."""

    def test_install_no_config_shows_error(self, runner, tmp_path, monkeypatch):
        """Install with no warden.yaml shows error."""
        project = tmp_path / "empty_project"
        project.mkdir()
        monkeypatch.chdir(project)

        result = runner.invoke(app, ["install"])

        # Should fail with error
        assert result.exit_code != 0

        stdout_lower = result.stdout.lower()
        assert "error" in stdout_lower or "not found" in stdout_lower or "init" in stdout_lower

    def test_install_empty_dependencies(self, runner, tmp_path, monkeypatch):
        """Install with empty dependencies section succeeds with nothing installed."""
        project = tmp_path / "no_deps_project"
        project.mkdir()

        warden_dir = project / ".warden"
        warden_dir.mkdir()

        config = {
            "version": "2.0",
            "project": {"name": "no-deps", "type": "backend", "language": "python"},
            "dependencies": {},  # Empty
            "llm": {"provider": "ollama", "model": "qwen2.5-coder:3b"},
        }
        (warden_dir / "config.yaml").write_text(yaml.dump(config))

        monkeypatch.chdir(project)

        result = runner.invoke(app, ["install"])

        # Should succeed (nothing to install is not an error)
        assert result.exit_code == 0

        stdout_lower = result.stdout.lower()
        assert "0 dependencies" in stdout_lower or "done" in stdout_lower

    def test_install_nonexistent_local_path(self, runner, tmp_path, monkeypatch):
        """Install with non-existent local path shows error."""
        project = tmp_path / "bad_path_project"
        project.mkdir()

        warden_dir = project / ".warden"
        warden_dir.mkdir()

        config = {
            "version": "2.0",
            "project": {"name": "bad-path", "type": "backend", "language": "python"},
            "dependencies": {"fake_frame": {"path": "/nonexistent/path/to/frame"}},
            "llm": {"provider": "ollama", "model": "qwen2.5-coder:3b"},
        }
        (warden_dir / "config.yaml").write_text(yaml.dump(config))

        monkeypatch.chdir(project)

        result = runner.invoke(app, ["install"])

        # Should fail
        assert result.exit_code != 0

        stdout_lower = result.stdout.lower()
        assert "failed" in stdout_lower or "error" in stdout_lower

    def test_install_multiple_dependencies(self, runner, multi_dep_project, monkeypatch):
        """Install with multiple local path dependencies installs all."""
        monkeypatch.chdir(multi_dep_project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        # Verify both frames installed
        frames_dir = multi_dep_project / ".warden" / "frames"
        assert (frames_dir / "my_test_frame").exists()
        assert (frames_dir / "another_test_frame").exists()

        # Verify lockfile has both
        lockfile = multi_dep_project / "warden.lock"
        with open(lockfile) as f:
            lock_data = yaml.safe_load(f)

        assert "my_test_frame" in lock_data["packages"]
        assert "another_test_frame" in lock_data["packages"]

        # Both should have content hashes
        assert lock_data["packages"]["my_test_frame"]["content_hash"].startswith("sha256:")
        assert lock_data["packages"]["another_test_frame"]["content_hash"].startswith("sha256:")


# ============================================================================
# TestInstallWithManifest - Manifest-driven install behavior
# ============================================================================
@pytest.mark.e2e
class TestInstallWithManifest:
    """Test manifest-driven install file placement."""

    def test_install_with_manifest_copies_correct_files(self, runner, install_project, monkeypatch):
        """Manifest-driven install places all files in correct locations."""
        monkeypatch.chdir(install_project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        # With manifest, entire directory should be copied to frames/name/
        frame_dir = install_project / ".warden" / "frames" / "my_test_frame"

        # Verify structure
        assert (frame_dir / "frame.py").exists()
        assert (frame_dir / "__init__.py").exists()
        assert (frame_dir / "warden.manifest.yaml").exists()
        assert (frame_dir / "rules").is_dir()
        assert (frame_dir / "rules" / "test_rule.yaml").exists()

        # Rules also copied to .warden/rules/
        rules_dir = install_project / ".warden" / "rules"
        assert (rules_dir / "test_rule.yaml").exists()

    def test_install_without_manifest_uses_simple_install(self, runner, tmp_path, monkeypatch):
        """No manifest triggers simple install (fallback behavior)."""
        # Create frame package WITHOUT manifest
        pkg = tmp_path / "no_manifest_frame"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('"""No manifest frame."""\n')
        (pkg / "frame.py").write_text('"""Frame code."""\n\nclass SimpleFrame:\n    pass\n')

        # Create project
        project = tmp_path / "project"
        project.mkdir()
        warden_dir = project / ".warden"
        warden_dir.mkdir()

        config = {
            "version": "2.0",
            "project": {"name": "test", "type": "backend", "language": "python"},
            "dependencies": {"no_manifest_frame": {"path": str(pkg)}},
            "llm": {"provider": "ollama", "model": "qwen2.5-coder:3b"},
        }
        (warden_dir / "config.yaml").write_text(yaml.dump(config))

        monkeypatch.chdir(project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        # Should still install (simple copy)
        frame_dir = warden_dir / "frames" / "no_manifest_frame"
        assert frame_dir.exists()
        assert (frame_dir / "frame.py").exists()

        # Should have hash in lockfile
        lockfile = project / "warden.lock"
        with open(lockfile) as f:
            lock_data = yaml.safe_load(f)

        assert "no_manifest_frame" in lock_data["packages"]
        assert "content_hash" in lock_data["packages"]["no_manifest_frame"]


# ============================================================================
# TestInstallStagingCleanup - Verify staging directory behavior
# ============================================================================
@pytest.mark.e2e
class TestInstallStagingCleanup:
    """Test that staging directory is used correctly."""

    def test_install_uses_staging_directory(self, runner, install_project, monkeypatch):
        """Install uses .warden/staging/ for temporary operations."""
        monkeypatch.chdir(install_project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        # Staging directory should exist
        staging_dir = install_project / ".warden" / "staging"
        assert staging_dir.exists(), "Staging directory not created"

        # Staging should contain the frame during install
        # (After install, staging may be cleaned or left with copied data)
        # The key is that .warden/frames/ has the final installation
        frame_dir = install_project / ".warden" / "frames" / "my_test_frame"
        assert frame_dir.exists()


# ============================================================================
# TestInstallOutput - Verify CLI output formatting
# ============================================================================
@pytest.mark.e2e
class TestInstallOutput:
    """Test install command output formatting and messages."""

    def test_install_shows_progress_messages(self, runner, install_project, monkeypatch):
        """Install shows progress indicators."""
        monkeypatch.chdir(install_project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        stdout_lower = result.stdout.lower()
        # Should show some progress/status
        assert any(word in stdout_lower for word in ["installing", "fetching", "done", "success"])

    def test_install_shows_package_count(self, runner, install_project, monkeypatch):
        """Install shows count of dependencies being installed."""
        monkeypatch.chdir(install_project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        # Should mention dependency count
        stdout = result.stdout.lower()
        assert "1 dependencies" in stdout or "1 packages" in stdout or "my_test_frame" in stdout

    def test_install_multiple_shows_summary(self, runner, multi_dep_project, monkeypatch):
        """Install with multiple packages shows summary table."""
        monkeypatch.chdir(multi_dep_project)

        result = runner.invoke(app, ["install"])
        assert result.exit_code == 0

        stdout = result.stdout.lower()
        # Should show both frame names
        assert "my_test_frame" in stdout
        assert "another_test_frame" in stdout

        # Should indicate success
        assert "success" in stdout or "done" in stdout
