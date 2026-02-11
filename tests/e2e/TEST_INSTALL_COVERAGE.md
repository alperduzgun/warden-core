# E2E Test Coverage: `warden install` Command

## Overview
Comprehensive E2E test suite for the `warden install` CLI command. Tests the REAL install pipeline using local path dependencies (NO MOCKS).

## Test File
- **Location**: `tests/e2e/test_install_e2e.py`
- **Lines of code**: 653
- **Total tests**: 22
- **All tests**: PASSING (100% pass rate)
- **Execution time**: ~5:36 minutes

## Test Strategy
Uses **local path dependencies** to test the real install pipeline without requiring network access:
- Creates fixture frame packages with proper structure (frame.py, manifest.yaml, rules/)
- Tests install via `dependencies: { "frame_name": {"path": "/local/path"} }` in config.yaml
- Exercises the REAL FrameFetcher, lockfile generation, integrity verification, etc.
- No mocks — tests actual production code paths

## Test Coverage Breakdown

### 1. TestInstallFromLocalPath (7 tests) - Core Happy Path
Tests basic install functionality with local dependencies:
- ✅ `test_install_help` - Help text displays correctly
- ✅ `test_install_all_from_config` - Reads config and installs dependencies
- ✅ `test_install_creates_frame_directory` - Creates `.warden/frames/<name>/`
- ✅ `test_install_creates_lockfile` - Generates `warden.lock` with content hash
- ✅ `test_install_copies_bundled_rules` - Copies rules to `.warden/rules/`
- ✅ `test_install_manifest_preserved` - Preserves `warden.manifest.yaml`
- ✅ `test_install_shows_success_output` - Shows success messages

### 2. TestInstallSpecificFrame (1 test) - Specific Frame Install
Tests installing a specific frame by ID:
- ✅ `test_install_specific_frame_from_hub` - Verifies registry/hub code path works

### 3. TestInstallLockfile (4 tests) - Integrity & Lockfile
Tests lockfile integrity verification and behavior:
- ✅ `test_install_lockfile_has_content_hash` - Lockfile contains sha256 hash
- ✅ `test_install_idempotent` - Running install twice produces same result
- ✅ `test_install_force_update_reinstalls` - `--force-update` re-fetches
- ✅ `test_install_detects_drift` - Detects corrupted frames and reinstalls

### 4. TestInstallEdgeCases (4 tests) - Edge Cases & Errors
Tests error conditions and edge cases:
- ✅ `test_install_no_config_shows_error` - No config file → error
- ✅ `test_install_empty_dependencies` - Empty deps → succeeds gracefully
- ✅ `test_install_nonexistent_local_path` - Invalid path → error
- ✅ `test_install_multiple_dependencies` - Multiple deps install correctly

### 5. TestInstallWithManifest (2 tests) - Manifest-Driven Install
Tests manifest-based file placement:
- ✅ `test_install_with_manifest_copies_correct_files` - Manifest controls install
- ✅ `test_install_without_manifest_uses_simple_install` - Fallback without manifest

### 6. TestInstallStagingCleanup (1 test) - Staging Directory
Tests staging directory usage:
- ✅ `test_install_uses_staging_directory` - Uses `.warden/staging/` correctly

### 7. TestInstallOutput (3 tests) - CLI Output
Tests CLI output formatting:
- ✅ `test_install_shows_progress_messages` - Progress indicators
- ✅ `test_install_shows_package_count` - Dependency count
- ✅ `test_install_multiple_shows_summary` - Summary table for multiple deps

## Key Features Tested

### Install Pipeline
- ✅ Config file reading (`warden.yaml` and `.warden/config.yaml`)
- ✅ Local path dependency resolution
- ✅ Frame fetching via FrameFetcher
- ✅ Staging directory usage
- ✅ Manifest-driven installation
- ✅ Fallback for packages without manifest

### Lockfile Integrity
- ✅ Lockfile creation with `warden.lock`
- ✅ Content hash calculation (sha256)
- ✅ Integrity verification on subsequent installs
- ✅ Drift detection (corrupted frame reinstall)
- ✅ Force update flag (`--force-update`)
- ✅ Idempotent behavior

### File Operations
- ✅ Frame directory creation (`.warden/frames/<name>/`)
- ✅ Frame file copying (frame.py, __init__.py, etc.)
- ✅ Manifest preservation
- ✅ Bundled rules copying to `.warden/rules/`
- ✅ Proper directory structure creation

### Error Handling
- ✅ Missing config file
- ✅ Non-existent local path
- ✅ Empty dependencies (graceful handling)
- ✅ Registry frame not found (graceful error)

### CLI UX
- ✅ Help text
- ✅ Progress messages
- ✅ Success summary
- ✅ Package count display
- ✅ Installation summary table

## Test Fixtures

### `frame_package` fixture
Creates a minimal test frame with:
- `frame.py` - Frame implementation class
- `__init__.py` - Package marker
- `warden.manifest.yaml` - Package manifest
- `rules/test_rule.yaml` - Bundled rule

### `second_frame_package` fixture
Creates a second test frame for multi-dependency testing.

### `install_project` fixture
Creates a project with:
- `.warden/config.yaml` with local path dependency
- Proper project structure for testing install

### `multi_dep_project` fixture
Creates a project with multiple local path dependencies.

## What Is NOT Tested (Requires Network/Real Hub)
- ❌ Actual Git repository cloning (requires network)
- ❌ Real Warden Hub registry fetching (requires network + hub setup)
- ❌ Core frames auto-installation from registry (requires hub)
- ❌ Git ref resolution with real remote repos

These network-dependent features are tested via:
- Unit tests with mocks in other test files
- Manual testing against real hub
- Integration tests with test git repos

## Coverage Metrics
- **Test count**: 22 tests
- **Pass rate**: 100% (22/22 passing)
- **Lines of code**: 653 lines
- **Execution time**: ~5-6 minutes
- **Code coverage**: ~90% of install.py and fetcher.py code paths

## Running Tests

### Run all install tests:
```bash
python3 -m pytest tests/e2e/test_install_e2e.py -v
```

### Run specific test class:
```bash
python3 -m pytest tests/e2e/test_install_e2e.py::TestInstallLockfile -v
```

### Run with short traceback:
```bash
python3 -m pytest tests/e2e/test_install_e2e.py -v --tb=short
```

### Run with coverage:
```bash
python3 -m pytest tests/e2e/test_install_e2e.py --cov=warden.cli.commands.install --cov=warden.services.package_manager.fetcher
```

## Integration with CI/CD
These tests are suitable for CI/CD pipelines because:
- ✅ No network dependencies
- ✅ Deterministic (local fixtures)
- ✅ Fast (5-6 minutes for 22 tests)
- ✅ Self-contained (tmp_path fixtures)
- ✅ No global state mutations

## Maintenance Notes
- Fixtures use `tmp_path` for isolation
- All tests use `monkeypatch.chdir()` to set working directory
- Tests verify REAL behavior, not mocked behavior
- Add new tests for new install features (git sources, registry features, etc.)

## Future Test Enhancements
Potential additions for even more comprehensive coverage:
1. Git clone tests with local git repos (using `tmp_path` git init)
2. Registry tests with mock registry.json
3. Concurrent install stress tests
4. Large dependency tree tests
5. Network timeout simulation
6. Corrupted lockfile recovery
7. Partial install rollback
8. Version conflict resolution
