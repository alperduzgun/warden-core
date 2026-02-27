"""E2E tests for Tier 2+3 edge cases not covered elsewhere.

Addresses remaining gaps from GitHub issue #45:
- Concurrent scans (parallel E2E test)
- Disk full during report write (ENOSPC mock)
- Baseline migration atomicity (interruption test)
- Config concurrent modification (race condition test)

NOTE: Several items from issue #45 were already added in test_acceptance.py
(sections 42-43): symlink cycle, 1MB+ file, negative config, untested
commands (serve, chat, index, status --fetch, serve mcp start).
This file covers only the REMAINING gaps.

Markers:
- @pytest.mark.acceptance  -- subprocess-based tests (need ``warden`` on PATH)
- @pytest.mark.e2e         -- in-process tests (import warden directly)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_PROJECT = FIXTURES_DIR / "sample_project"

# ───────────────────────────────────────────────────────────────────────────
# Module-level skip for acceptance tests that need the binary
# ───────────────────────────────────────────────────────────────────────────

_WARDEN_BINARY = shutil.which("warden") is not None


def run_warden(
    *args: str,
    cwd: str | Path | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``warden`` as a subprocess and return the result."""
    merged_env = {**os.environ, **(env or {})}
    merged_env.setdefault("SECRET_KEY", "test-acceptance-key-do-not-use")
    return subprocess.run(
        ["warden", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=merged_env,
    )


def _assert_no_crash(
    r: subprocess.CompletedProcess[str],
    *,
    allowed: tuple[int, ...] = (0, 1, 2),
    context: str = "",
) -> None:
    """Assert process didn't crash (no traceback, exit code in allowed set)."""
    assert r.returncode in allowed, (
        f"{context + ': ' if context else ''}"
        f"Expected exit code in {allowed}, got {r.returncode}\n"
        f"stdout: {r.stdout[-500:]}\nstderr: {r.stderr[-500:]}"
    )
    combined = r.stdout + r.stderr
    assert "Traceback" not in combined, (
        f"{context + ': ' if context else ''}Traceback found in output:\n{combined[-1000:]}"
    )


# ───────────────────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────────────────


@pytest.fixture
def initialized_project(tmp_path):
    """A temp directory with ``warden init --force --skip-mcp`` already run."""
    if not _WARDEN_BINARY:
        pytest.skip("warden binary not found on PATH")
    result = run_warden(
        "init", "--force", "--skip-mcp",
        cwd=str(tmp_path), timeout=30,
    )
    assert result.returncode == 0, f"init failed: {result.stderr}"
    return tmp_path


@pytest.fixture
def isolated_sample(tmp_path):
    """Copy of the sample_project fixture for mutation-safe tests."""
    dest = tmp_path / "project"
    shutil.copytree(SAMPLE_PROJECT, dest)
    return dest


# =========================================================================
# 1. Concurrent Scans — no parallel E2E test
# =========================================================================


@pytest.mark.acceptance
@pytest.mark.skipif(not _WARDEN_BINARY, reason="warden binary not found on PATH")
class TestConcurrentScans:
    """Verify multiple parallel warden scan processes don't crash or corrupt."""

    def test_parallel_scans_no_crash(self, initialized_project):
        """Run 3 concurrent scan processes on the same project directory.

        All should finish without crashing, even if they race on the same
        lock files or report outputs.
        """
        # Create a small Python file to scan
        (initialized_project / "app.py").write_text(
            "import os\ndef run(cmd):\n    os.system(cmd)\n"
        )

        def _scan() -> subprocess.CompletedProcess[str]:
            return run_warden(
                "scan", "--level", "basic",
                str(initialized_project / "app.py"),
                cwd=str(initialized_project),
                timeout=90,
            )

        results: list[subprocess.CompletedProcess[str]] = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(_scan) for _ in range(3)]
            for future in as_completed(futures):
                results.append(future.result())

        # Every run must finish without traceback
        for i, r in enumerate(results):
            _assert_no_crash(r, context=f"parallel scan #{i}")

    def test_parallel_scans_different_files(self, initialized_project):
        """Run concurrent scans on different files in the same project."""
        files = []
        for i in range(3):
            f = initialized_project / f"module_{i}.py"
            f.write_text(f"x_{i} = {i}\n")
            files.append(f)

        def _scan(path: Path) -> subprocess.CompletedProcess[str]:
            return run_warden(
                "scan", "--level", "basic", str(path),
                cwd=str(initialized_project),
                timeout=90,
            )

        results: list[subprocess.CompletedProcess[str]] = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(_scan, f) for f in files]
            for future in as_completed(futures):
                results.append(future.result())

        for i, r in enumerate(results):
            _assert_no_crash(r, context=f"parallel file scan #{i}")

    def test_parallel_scan_and_config_read(self, initialized_project):
        """A scan and a config read running in parallel should not deadlock."""
        (initialized_project / "code.py").write_text("y = 2\n")

        def _scan() -> subprocess.CompletedProcess[str]:
            return run_warden(
                "scan", "--level", "basic",
                str(initialized_project / "code.py"),
                cwd=str(initialized_project),
                timeout=90,
            )

        def _config_list() -> subprocess.CompletedProcess[str]:
            return run_warden(
                "config", "list",
                cwd=str(initialized_project),
                timeout=30,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_scan = pool.submit(_scan)
            f_config = pool.submit(_config_list)

            r_scan = f_scan.result()
            r_config = f_config.result()

        _assert_no_crash(r_scan, context="scan during parallel config read")
        _assert_no_crash(r_config, context="config list during parallel scan")


# =========================================================================
# 2. Disk Full During Report Write — ENOSPC mock
# =========================================================================


@pytest.mark.e2e
class TestDiskFullReportWrite:
    """Verify the report generator handles ENOSPC gracefully."""

    def test_json_report_enospc_raises(self, tmp_path):
        """ReportGenerator.generate_json_report should propagate OSError on ENOSPC."""
        from warden.reports.generator import ReportGenerator

        gen = ReportGenerator()
        output_path = tmp_path / "report.json"
        scan_results = {
            "version": "1.0",
            "findings": [{"id": "test", "severity": "low"}],
        }

        # Patch os.fdopen to simulate ENOSPC when writing
        original_fdopen = os.fdopen

        def _enospc_fdopen(fd, mode="r", *args, **kwargs):
            f = original_fdopen(fd, mode, *args, **kwargs)
            if "w" in mode:
                original_write = f.write

                def _failing_write(data):
                    raise OSError(28, "No space left on device")

                f.write = _failing_write
            return f

        with patch("warden.reports.generator.os.fdopen", side_effect=_enospc_fdopen):
            with pytest.raises(OSError, match="No space left on device"):
                gen.generate_json_report(scan_results, output_path)

        # Temp file should be cleaned up after failure
        tmp_files = list(tmp_path.glob(".tmp_*"))
        assert len(tmp_files) == 0, f"Temp files not cleaned up: {tmp_files}"

    def test_json_report_enospc_no_partial_output(self, tmp_path):
        """On ENOSPC the output file should not be created (atomic write)."""
        from warden.reports.generator import ReportGenerator

        gen = ReportGenerator()
        output_path = tmp_path / "report.json"
        scan_results = {"version": "1.0", "findings": []}

        # Pre-create the output file to verify it stays untouched
        output_path.write_text('{"old": "data"}')
        original_content = output_path.read_text()

        original_fdopen = os.fdopen

        def _enospc_fdopen(fd, mode="r", *args, **kwargs):
            f = original_fdopen(fd, mode, *args, **kwargs)
            if "w" in mode:
                original_write = f.write

                def _failing_write(data):
                    raise OSError(28, "No space left on device")

                f.write = _failing_write
            return f

        with patch("warden.reports.generator.os.fdopen", side_effect=_enospc_fdopen):
            with pytest.raises(OSError):
                gen.generate_json_report(scan_results, output_path)

        # Original file should be untouched (atomic write means no partial replace)
        assert output_path.read_text() == original_content

    def test_sarif_report_enospc_raises(self, tmp_path):
        """ReportGenerator.generate_sarif_report should propagate OSError on ENOSPC."""
        from warden.reports.generator import ReportGenerator

        gen = ReportGenerator()
        output_path = tmp_path / "report.sarif"
        scan_results = {
            "version": "1.0",
            "findings": [],
            "frameResults": [],
        }

        original_fdopen = os.fdopen

        def _enospc_fdopen(fd, mode="r", *args, **kwargs):
            f = original_fdopen(fd, mode, *args, **kwargs)
            if "w" in mode:
                def _failing_write(data):
                    raise OSError(28, "No space left on device")
                f.write = _failing_write
            return f

        with patch("warden.reports.generator.os.fdopen", side_effect=_enospc_fdopen):
            with pytest.raises(OSError, match="No space left on device"):
                gen.generate_sarif_report(scan_results, output_path)


# =========================================================================
# 3. Baseline Migration Atomicity — interruption test
# =========================================================================


@pytest.mark.e2e
class TestBaselineMigrationAtomicity:
    """Verify baseline migration handles interruption gracefully."""

    def _make_legacy_baseline(self, warden_dir: Path) -> Path:
        """Create a legacy single-file baseline for migration testing."""
        baseline_path = warden_dir / "baseline.json"
        legacy_data = {
            "version": "1.0",
            "created_at": "2025-01-01T00:00:00Z",
            "frameResults": [
                {
                    "frame": "security",
                    "findings": [
                        {
                            "id": "SEC-001",
                            "file_path": "src/auth.py",
                            "severity": "high",
                            "message": "Hardcoded credential",
                        },
                        {
                            "id": "SEC-002",
                            "file_path": "src/api.py",
                            "severity": "medium",
                            "message": "Missing input validation",
                        },
                    ],
                }
            ],
        }
        baseline_path.write_text(json.dumps(legacy_data, indent=2))
        return baseline_path

    def test_migration_creates_module_baselines(self, tmp_path):
        """Basic migration should create per-module baseline files."""
        from warden.cli.commands.helpers.baseline_manager import BaselineManager

        # BaselineManager expects project_root (parent of .warden)
        project_root = tmp_path
        warden_dir = project_root / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        self._make_legacy_baseline(warden_dir)

        manager = BaselineManager(project_root)
        result = manager.migrate_from_legacy()

        assert result is True
        # Module baselines should exist
        baseline_dir = warden_dir / "baseline"
        assert baseline_dir.exists()
        module_files = list(baseline_dir.glob("*.json"))
        # At least one module baseline + _meta.json
        assert len(module_files) >= 1, "No module baselines created"

    def test_migration_interrupted_by_write_failure(self, tmp_path):
        """If saving a module baseline fails mid-migration, partial state
        should not corrupt the legacy baseline."""
        from warden.cli.commands.helpers.baseline_manager import BaselineManager

        project_root = tmp_path
        warden_dir = project_root / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        legacy_path = self._make_legacy_baseline(warden_dir)
        original_legacy = legacy_path.read_text()

        manager = BaselineManager(project_root)

        # Patch save_module_baseline to fail on the second call
        call_count = 0
        original_save = manager.save_module_baseline

        def _failing_save(module_baseline):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise OSError(28, "No space left on device")
            return original_save(module_baseline)

        with patch.object(manager, "save_module_baseline", side_effect=_failing_save):
            # Migration should either raise or return False
            try:
                result = manager.migrate_from_legacy()
            except OSError:
                result = False

        # Legacy baseline should still be intact
        assert legacy_path.exists(), "Legacy baseline was deleted despite failed migration"
        assert legacy_path.read_text() == original_legacy

    def test_migration_empty_legacy_baseline(self, tmp_path):
        """Migration of an empty legacy baseline should not crash."""
        from warden.cli.commands.helpers.baseline_manager import BaselineManager

        project_root = tmp_path
        warden_dir = project_root / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        # Create empty legacy baseline
        baseline_path = warden_dir / "baseline.json"
        baseline_path.write_text(json.dumps({"version": "1.0", "findings": []}))

        manager = BaselineManager(project_root)
        # Should not crash, may return True (nothing to migrate) or False
        result = manager.migrate_from_legacy()
        assert isinstance(result, bool)


# =========================================================================
# 4. Config Concurrent Modification — race condition test
# =========================================================================


@pytest.mark.acceptance
@pytest.mark.skipif(not _WARDEN_BINARY, reason="warden binary not found on PATH")
class TestConfigConcurrentModification:
    """Verify concurrent config writes don't corrupt the YAML file."""

    def test_concurrent_config_sets_no_corruption(self, initialized_project):
        """Two parallel config set commands should not produce broken YAML."""
        def _set_config(key: str, value: str) -> subprocess.CompletedProcess[str]:
            return run_warden(
                "config", "set", key, value,
                cwd=str(initialized_project),
                timeout=30,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_set_config, "settings.fail_fast", "true")
            f2 = pool.submit(_set_config, "llm.timeout", "120")

            r1 = f1.result()
            r2 = f2.result()

        # Both should succeed or one may fail due to locking, but neither should crash
        for r in (r1, r2):
            assert r.returncode in (0, 1), (
                f"Config set crashed: rc={r.returncode}\n"
                f"stdout: {r.stdout[-300:]}\nstderr: {r.stderr[-300:]}"
            )
            combined = r.stdout + r.stderr
            assert "Traceback" not in combined

        # Config file should still be valid YAML
        config_path = initialized_project / ".warden" / "config.yaml"
        content = config_path.read_text()
        try:
            config = yaml.safe_load(content)
        except yaml.YAMLError as e:
            pytest.fail(f"Config YAML corrupted after concurrent writes: {e}\nContent:\n{content[:500]}")

        assert isinstance(config, dict), f"Config is not a dict: {type(config)}"

    def test_concurrent_config_set_and_list(self, initialized_project):
        """A config set and config list running simultaneously should not crash."""
        def _set_config() -> subprocess.CompletedProcess[str]:
            return run_warden(
                "config", "set", "settings.fail_fast", "false",
                cwd=str(initialized_project),
                timeout=30,
            )

        def _list_config() -> subprocess.CompletedProcess[str]:
            return run_warden(
                "config", "list",
                cwd=str(initialized_project),
                timeout=30,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_set = pool.submit(_set_config)
            f_list = pool.submit(_list_config)

            r_set = f_set.result()
            r_list = f_list.result()

        _assert_no_crash(r_set, context="config set during parallel list")
        _assert_no_crash(r_list, context="config list during parallel set")

    def test_rapid_sequential_config_writes(self, initialized_project):
        """Rapid sequential config writes should not corrupt the file."""
        for i in range(5):
            r = run_warden(
                "config", "set", "llm.timeout", str(30 + i),
                cwd=str(initialized_project),
                timeout=15,
            )
            assert r.returncode in (0, 1), (
                f"Config set #{i} crashed: rc={r.returncode}\nstderr: {r.stderr[-300:]}"
            )
            assert "Traceback" not in r.stdout + r.stderr

        # Final config should be valid and have the last value
        config_path = initialized_project / ".warden" / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        assert isinstance(config, dict)
        # The timeout should be one of the values we set (race-safe: any is fine)
        timeout_val = config.get("llm", {}).get("timeout")
        assert timeout_val in range(30, 35), f"Unexpected timeout value: {timeout_val}"


# =========================================================================
# 5. Report Generator File Lock Contention
# =========================================================================


@pytest.mark.e2e
class TestReportFileLockContention:
    """Verify the file_lock context manager handles contention correctly."""

    def test_concurrent_json_report_writes(self, tmp_path):
        """Two threads writing JSON reports to the same path should not corrupt."""
        from warden.reports.generator import ReportGenerator

        gen = ReportGenerator()
        output_path = tmp_path / "report.json"

        results_a = {"version": "1.0", "findings": [{"id": "A"}]}
        results_b = {"version": "1.0", "findings": [{"id": "B"}]}

        errors: list[Exception] = []

        def _write(data: dict) -> None:
            try:
                gen.generate_json_report(data, output_path)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=_write, args=(results_a,))
        t2 = threading.Thread(target=_write, args=(results_b,))

        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert not errors, f"Report write raised errors: {errors}"

        # Output should be valid JSON (one of the two writes wins)
        content = output_path.read_text()
        data = json.loads(content)
        assert data["version"] == "1.0"
        assert len(data["findings"]) == 1
        assert data["findings"][0]["id"] in ("A", "B")

    def test_file_lock_timeout(self, tmp_path):
        """file_lock should raise TimeoutError when lock cannot be acquired."""
        from warden.reports.generator import file_lock

        lock_path = tmp_path / "test.lock"

        # Acquire the lock in the main thread, then try in another thread
        import fcntl

        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

        error_holder: list[Exception] = []

        def _try_lock():
            try:
                with file_lock(lock_path, timeout=1):
                    pass  # Should not reach here
            except TimeoutError as e:
                error_holder.append(e)
            except Exception as e:
                error_holder.append(e)

        t = threading.Thread(target=_try_lock)
        t.start()
        t.join(timeout=10)

        # Release our lock
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

        assert len(error_holder) == 1, f"Expected TimeoutError, got: {error_holder}"
        assert isinstance(error_holder[0], TimeoutError)


# =========================================================================
# 6. Baseline Manager Edge Cases
# =========================================================================


@pytest.mark.e2e
class TestBaselineManagerEdgeCases:
    """Additional baseline manager edge cases."""

    def test_save_module_baseline_creates_directory(self, tmp_path):
        """save_module_baseline should create the baseline directory if missing."""
        from warden.cli.commands.helpers.baseline_manager import (
            BaselineManager,
            ModuleBaseline,
        )

        # BaselineManager expects project_root (parent of .warden)
        project_root = tmp_path
        warden_dir = project_root / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        manager = BaselineManager(project_root)

        module = ModuleBaseline("test/module", {
            "findings": [{"id": "TEST-001"}],
            "debt_items": [],
        })

        result = manager.save_module_baseline(module)
        assert result is True

        baseline_dir = warden_dir / "baseline"
        assert baseline_dir.exists()
        module_files = list(baseline_dir.glob("*.json"))
        assert len(module_files) == 1

    def test_load_nonexistent_module_baseline(self, tmp_path):
        """Loading a nonexistent module baseline should return None, not crash."""
        from warden.cli.commands.helpers.baseline_manager import BaselineManager

        project_root = tmp_path
        warden_dir = project_root / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        manager = BaselineManager(project_root)
        result = manager.load_module_baseline("nonexistent/module")
        assert result is None

    def test_load_corrupted_module_baseline(self, tmp_path):
        """Loading a corrupted module baseline should return None, not crash."""
        from warden.cli.commands.helpers.baseline_manager import BaselineManager

        project_root = tmp_path
        warden_dir = project_root / ".warden"
        warden_dir.mkdir()
        (warden_dir / "config.yaml").write_text("llm:\n  provider: ollama\n")

        # Create a corrupted baseline file
        baseline_dir = warden_dir / "baseline"
        baseline_dir.mkdir()
        corrupted = baseline_dir / "src_auth.json"
        corrupted.write_text("{invalid json content")

        manager = BaselineManager(project_root)
        result = manager.load_module_baseline("src/auth")
        assert result is None
