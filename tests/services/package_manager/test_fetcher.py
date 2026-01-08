import pytest
import shutil
import yaml
from pathlib import Path
from warden.services.package_manager.fetcher import FrameFetcher
from warden.services.package_manager.exceptions import LockfileCorruptionError

@pytest.fixture
def test_env(tmp_path):
    warden_dir = tmp_path / ".warden"
    warden_dir.mkdir()
    (warden_dir / "frames").mkdir()
    (warden_dir / "rules").mkdir()
    
    # Create simple local package
    pkg_src = tmp_path / "local-pkg"
    pkg_src.mkdir()
    (pkg_src / "frame.py").write_text("print('hello')")
    
    return tmp_path, warden_dir, pkg_src

def test_fetch_from_local_and_verify(test_env):
    root, warden_dir, pkg_src = test_env
    fetcher = FrameFetcher(warden_dir)
    
    # Fetch
    success = fetcher.fetch("my-pkg", {"path": str(pkg_src)})
    assert success is True
    
    # Check if installed
    assert (warden_dir / "frames" / "my-pkg" / "frame.py").exists()
    
    # Verify Integrity (Steady State)
    fetcher._commit_lock_updates()
    assert fetcher.verify_integrity("my-pkg") is True

def test_drift_detection(test_env):
    root, warden_dir, pkg_src = test_env
    fetcher = FrameFetcher(warden_dir)
    
    fetcher.fetch("my-pkg", {"path": str(pkg_src)})
    fetcher._commit_lock_updates()
    
    # Simulate Drift (Modifying installed file)
    installed_file = warden_dir / "frames" / "my-pkg" / "frame.py"
    installed_file.write_text("print('hacked')")
    
    assert fetcher.verify_integrity("my-pkg") is False

def test_corrupt_lock_handling(test_env):
    root, warden_dir, _ = test_env
    lock_path = root / "warden.lock"
    
    # Write invalid lock
    with open(lock_path, "w") as f:
        f.write("packages: not-a-dict")
    
    with pytest.raises(LockfileCorruptionError):
        FrameFetcher(warden_dir)

def test_atomic_transaction(test_env):
    root, warden_dir, pkg_src = test_env
    fetcher = FrameFetcher(warden_dir)
    
    # Fetch without committing
    fetcher.fetch("pkg-1", {"path": str(pkg_src)})
    
    # Lockfile should NOT have pkg-1 yet
    lock_path = root / "warden.lock"
    if lock_path.exists():
        with open(lock_path) as f:
            data = yaml.safe_load(f)
            assert "pkg-1" not in data.get("packages", {})
    
    # Commit
    fetcher._commit_lock_updates()
    with open(lock_path) as f:
        data = yaml.safe_load(f)
        assert "pkg-1" in data.get("packages", {})
