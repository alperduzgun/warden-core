import os
import shutil
import subprocess
import yaml
import hashlib
import fcntl
from pathlib import Path
from typing import Dict, Any, Optional, List
from warden.shared.infrastructure.logging import get_logger
from warden.services.package_manager.exceptions import (
    LockfileCorruptionError,
    GitRefResolutionError,
    PartialInstallError,
)

logger = get_logger(__name__)

class FrameFetcher:
    """
    Service responsible for fetching frames and rules from remote or local sources.
    Supports Git repositories and local folder mapping.
    Includes Chaos Engineering principles: Integrity verification and Drift Detection.
    """

    def __init__(self, target_dir: Path, force_update: bool = False):
        self.target_dir = target_dir
        self.staging_dir = target_dir / "staging"
        self.frames_dir = target_dir / "frames"
        self.rules_dir = target_dir / "rules"
        self.force_update = force_update

        # Ensure directories exist
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.rules_dir.mkdir(parents=True, exist_ok=True)

        self.lock_path = self.target_dir.parent / "warden.lock"
        self.lock_data = self._load_lockfile()
        self.pending_lock_updates: Dict[str, Dict[str, Any]] = {}  # Transaction staging

    def _calculate_dir_hash(self, path: Path) -> str:
        """Calculate a deterministic SHA-256 hash for all files in a directory."""
        hasher = hashlib.sha256()
        
        # Sort files to ensure deterministic hashing
        files = []
        for root, _, filenames in os.walk(path):
            for filename in filenames:
                files.append(Path(root) / filename)
        
        for file_path in sorted(files, key=lambda p: str(p.relative_to(path))):
            rel_path = file_path.relative_to(path)
            # Skip hidden files and pycache within the package
            if any(part.startswith('.') or part == "__pycache__" for part in rel_path.parts):
                continue
                
            # Add relative path to hash to detect renames/moves
            hasher.update(str(rel_path).encode())
            
            # Add file content
            try:
                with open(file_path, "rb") as f:
                    while chunk := f.read(8192):
                        hasher.update(chunk)
            except Exception as e:
                logger.warning("hash_calculation_read_error", path=str(file_path), error=str(e))
                
        return f"sha256:{hasher.hexdigest()}"

    def verify_integrity(self, name: str) -> bool:
        """
        Verify the local integrity of an installed package against the lockfile.
        Returns True if integrity is intact (Steady State).
        """
        locked = self.lock_data.get("packages", {}).get(name)
        if not locked or "content_hash" not in locked:
            logger.warning("integrity_check_skipped_no_lock", name=name)
            return True # Assume OK if no hash exists yet
            
        frame_path = self.frames_dir / name
        if not frame_path.exists():
            logger.error("integrity_check_failed_path_missing", name=name)
            return False
            
        current_hash = self._calculate_dir_hash(frame_path)
        locked_hash = locked["content_hash"]
        
        if current_hash != locked_hash:
            logger.error("drift_detected", name=name, expected=locked_hash, actual=current_hash)
            return False
            
        logger.info("steady_state_verified", name=name)
        return True

    def _load_lockfile(self) -> Dict[str, Any]:
        """Load and validate the lockfile if it exists."""
        if not self.lock_path.exists():
            return {"packages": {}}
        
        try:
            with open(self.lock_path, "r") as f:
                data = yaml.safe_load(f) or {}
            
            # Fail-fast validation
            if "packages" not in data:
                raise LockfileCorruptionError("Missing 'packages' key in lockfile")
            
            if not isinstance(data["packages"], dict):
                raise LockfileCorruptionError("'packages' key must be a dictionary")
            
            # Validate each package entry
            for name, entry in data["packages"].items():
                if not isinstance(entry, dict):
                    raise LockfileCorruptionError(f"Invalid entry for package '{name}'")
                if "content_hash" in entry and not entry["content_hash"].startswith("sha256:"):
                    raise LockfileCorruptionError(f"Invalid hash format for package '{name}'")
            
            logger.info("lockfile_loaded", packages=len(data["packages"]))
            return data
            
        except yaml.YAMLError as e:
            logger.error("lockfile_yaml_corrupt", error=str(e))
            raise LockfileCorruptionError(f"Corrupt YAML in lockfile: {e}")
        except Exception as e:
            logger.error("lockfile_load_failed", error=str(e), error_type=type(e).__name__)
            raise

    def _save_lockfile(self):
        """Thread-safe atomic write of lockfile."""
        temp_path = self.lock_path.with_suffix(".lock.tmp")
        
        try:
            # Write to temp file with exclusive lock
            with open(temp_path, "w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                yaml.safe_dump(self.lock_data, f, default_flow_style=False, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())  # Ensure disk write
            
            # Atomic rename (POSIX guarantee)
            temp_path.replace(self.lock_path)
            logger.info("lockfile_saved", packages=len(self.lock_data.get("packages", {})))
            
        except Exception as e:
            logger.error("lockfile_save_failed", error=str(e), error_type=type(e).__name__)
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _resolve_git_ref(self, url: str, ref: Optional[str] = None) -> str:
        """Resolve Git ref to exact commit hash using ls-remote (no cloning)."""
        try:
            cmd = ["git", "ls-remote", url, ref or "HEAD"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                raise GitRefResolutionError(f"Failed to resolve ref '{ref}' for {url}: {result.stderr}")
            
            if not result.stdout.strip():
                raise GitRefResolutionError(f"Ref '{ref}' not found in {url}")
            
            commit_hash = result.stdout.split()[0]
            logger.info("git_ref_resolved", url=url, ref=ref or "HEAD", commit=commit_hash)
            return commit_hash
            
        except subprocess.TimeoutExpired:
            raise GitRefResolutionError(f"Timeout resolving ref '{ref}' for {url}")
        except Exception as e:
            if isinstance(e, GitRefResolutionError):
                raise
            logger.error("git_ref_resolution_failed", url=url, ref=ref, error=str(e))
            raise GitRefResolutionError(f"Unexpected error resolving ref: {e}")

    def _commit_lock_updates(self):
        """Commit pending lock updates atomically (transaction commit)."""
        if not self.pending_lock_updates:
            return
        
        if "packages" not in self.lock_data:
            self.lock_data["packages"] = {}
        
        self.lock_data["packages"].update(self.pending_lock_updates)
        self._save_lockfile()
        self.pending_lock_updates.clear()
        logger.info("lock_transaction_committed", updated_packages=len(self.pending_lock_updates))

    def fetch_all(self, dependencies: Dict[str, Any]) -> bool:
        """
        Fetch all dependencies with atomic lock update (transaction pattern).
        Automatically includes 'Core' frames from the registry.
        Returns True if all succeed, False on any failure (fail-fast).
        """
        from warden.services.package_manager.registry import RegistryClient
        registry = RegistryClient()
        
        logger.info("fetch_all_started", dependency_count=len(dependencies))
        
        # 1. Get all Core frames from registry
        core_frames = registry.get_core_frames()
        all_to_install = dependencies.copy()
        
        # 2. Add core frames if not already in dependencies (user can override version/source)
        for core in core_frames:
            if core["id"] not in all_to_install:
                logger.info("auto_adding_core_frame", name=core["id"])
                all_to_install[core["id"]] = "latest" # Registry will resolve this
        
        # 3. Process the merged list
        for name, source in all_to_install.items():
            try:
                if not self.fetch(name, source):
                    logger.error("fetch_all_aborted", failed_package=name)
                    return False
            except Exception as e:
                logger.error("fetch_all_exception", package=name, error=str(e), error_type=type(e).__name__)
                return False
        
        # All succeeded → commit atomically
        self._commit_lock_updates()
        logger.info("fetch_all_completed", total_packages=len(all_to_install))
        return True

    def fetch(self, name: str, source: Any) -> bool:
        """
        Fetch a single frame/package from source.
        Updates pending_lock_updates (transaction staging), not lock_data directly.
        """
        logger.info("fetching_package", name=name, source=source)

        # Check if we have a locked version (unless force_update)
        locked = self.lock_data.get("packages", {}).get(name)
        if locked and not self.force_update:
            # INTEGRITY CHECK: Verify local steady state
            if self.verify_integrity(name):
                logger.info("steady_state_verified_skipping_fetch", name=name)
                return True
            else:
                logger.warning("drift_detected_reinstalling", name=name)
                # If drift detected, we continue to fetch and reinstall to restore steady state

            # If source is a dict and has specific overrides, we might need to prioritize them
            # but usually lockfile is the source of truth for 'install'.
            # For now, if it's git, use the ref from lock.
            if "git" in locked:
                return self._fetch_from_git(name, locked["git"], locked.get("ref"))
            if "path" in locked:
                return self._fetch_from_local(name, Path(locked["path"]))

        try:
            if isinstance(source, str):
                # Shorthand for official registry
                return self._fetch_from_registry(name, source)
            
            if "git" in source:
                return self._fetch_from_git(name, source["git"], source.get("ref"))
            
            if "path" in source:
                return self._fetch_from_local(name, Path(source["path"]))

            logger.error("unsupported_source_type", name=name, source=source)
            return False

        except Exception as e:
            logger.error("fetch_failed", name=name, error=str(e), error_type=type(e).__name__)
            return False

    def _fetch_from_git(self, name: str, url: str, ref: Optional[str] = None, subpath: Optional[str] = None) -> bool:
        """Clone from git repo with precise ref resolution and retry logic."""
        pkg_staging = self.staging_dir / name
        
        # Resolve ref to exact commit BEFORE cloning (fail-fast)
        try:
            exact_commit = self._resolve_git_ref(url, ref)
        except GitRefResolutionError as e:
            logger.error("git_ref_resolution_failed_aborting", name=name, url=url, ref=ref, error=str(e))
            return False
        
        max_retries = 3
        for attempt in range(max_retries):
            if pkg_staging.exists():
                shutil.rmtree(pkg_staging)

            cmd = ["git", "clone", "--depth", "1", url, str(pkg_staging)]
            if ref:
                cmd.extend(["-b", ref])

            logger.info("executing_git_clone", url=url, ref=ref, attempt=attempt+1)
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                break
            
            logger.warning("git_clone_attempt_failed", attempt=attempt+1, error=result.stderr)
            if attempt == max_retries - 1:
                logger.error("git_clone_final_failure", error=result.stderr)
                return False
        
        # Stage lock update (transaction pattern)
        self._update_lock(name, {"git": url, "ref": exact_commit, "path": subpath} if subpath else {"git": url, "ref": exact_commit})
        
        source_path = pkg_staging / subpath if subpath else pkg_staging
        return self._install_from_staging(name, source_path)

    def _update_lock(self, name: str, data: Dict[str, Any]):
        """Stage lock update for later commit (transaction pattern)."""
        if name not in self.pending_lock_updates:
            self.pending_lock_updates[name] = {}
            
        self.pending_lock_updates[name].update(data)

    def _fetch_from_local(self, name: str, path: Path) -> bool:
        """Copy from local filesystem."""
        if not path.exists():
            logger.error("local_path_not_found", path=str(path))
            return False

        self._update_lock(name, {"path": str(path.absolute())})
        pkg_staging = self.staging_dir / name
        if pkg_staging.exists():
            shutil.rmtree(pkg_staging)
        
        shutil.copytree(path, pkg_staging)
        return self._install_from_staging(name, pkg_staging)

    def _fetch_from_registry(self, name: str, version: str) -> bool:
        """Fetch from Warden Hub using RegistryClient resolution."""
        from warden.services.package_manager.registry import RegistryClient
        registry = RegistryClient()
        
        details = registry.get_details(name)
        if not details:
            logger.error("frame_not_found_in_registry", name=name)
            return False
            
        git_url = details.get("git")
        subpath = details.get("path")
        
        if not git_url:
            logger.error("frame_missing_git_url_in_registry", name=name)
            return False
            
        logger.info("resolved_registry_frame", name=name, url=git_url, subpath=subpath)
        return self._fetch_from_git(name, git_url, subpath=subpath)

    def _install_from_staging(self, name: str, staging_path: Path) -> bool:
        """Move files from staging to final locations based on manifest."""
        manifest_path = staging_path / "warden.manifest.yaml"
        if not manifest_path.exists():
            # Fallback if no manifest: assume it's a simple frame folder
            logger.warning("missing_manifest_falling_back", name=name)
            success = self._simple_install(name, staging_path)
            if success:
                # Calculate and update hash
                new_hash = self._calculate_dir_hash(self.frames_dir / name)
                self._update_lock(name, {"content_hash": new_hash})
            return success

        with open(manifest_path, "r") as f:
            manifest = yaml.safe_load(f)

        # 1. Install Frame code
        runtime = manifest.get("runtime", {})
        module_name = runtime.get("module", "frame.py")
        
        frame_dest = self.frames_dir / name
        if frame_dest.exists():
            shutil.rmtree(frame_dest)
        
        # Copy entire folder to frames/name
        shutil.copytree(staging_path, frame_dest)
        
        # 2. Install Rules if present in a 'rules' subfolder
        rules_src = staging_path / "rules"
        if rules_src.exists() and rules_src.is_dir():
            for rule_file in rules_src.glob("*.yaml"):
                shutil.copy2(rule_file, self.rules_dir / rule_file.name)
                logger.info("installed_rule", rule=rule_file.name)

        # Calculate and update hash for Chaos Resilience
        new_hash = self._calculate_dir_hash(frame_dest)
        self._update_lock(name, {"content_hash": new_hash})

        logger.info("installation_complete", name=name)
        return True

    def _simple_install(self, name: str, staging_path: Path) -> bool:
        """Legacy install for standard folder structure."""
        dest = self.frames_dir / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(staging_path, dest)
        
        # Update hash
        new_hash = self._calculate_dir_hash(dest)
        self._update_lock(name, {"content_hash": new_hash})
        return True
