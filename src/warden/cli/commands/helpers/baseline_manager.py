"""
Baseline Manager for Warden.

Handles fetching, loading, and validating the baseline artifact.
Supports vendor-agnostic fetching via configured commands.
Now supports module-based baseline structure for CI optimization.
"""

import hashlib
import json
import shlex
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger
from warden.shared.utils.finding_utils import get_finding_attribute

logger = get_logger(__name__)


def _compute_finding_fingerprint(finding: dict[str, Any]) -> str:
    """Canonical fingerprint for a finding: sha256(rule_id:file_path:message).

    Deliberately excludes code_snippet so the fingerprint is stable across
    minor refactors that change the snippet but not the finding itself (#151).
    Both call-sites in BaselineManager must use this function to ensure a
    finding always maps to the same hash regardless of which code path ran.
    """
    rule = finding.get("id") or finding.get("rule_id") or finding.get("ruleId", "unknown")
    # Prefer explicit path fields; fall back to "file" part of "file:line" location
    path = finding.get("file_path") or finding.get("path") or finding.get("file")
    if not path:
        location = finding.get("location", "")
        path = location.split(":")[0] if location else ""
    path = path or "unknown"
    msg = finding.get("message", "")
    return hashlib.sha256(f"{rule}:{path}:{msg}".encode()).hexdigest()


class ModuleBaseline:
    """Represents a per-module baseline with debt tracking."""

    def __init__(self, module_name: str, data: dict[str, Any] | None = None):
        self.module_name = module_name
        self.data = data or {}
        self.findings: list[dict[str, Any]] = self.data.get("findings", [])
        self.created_at = self.data.get("created_at")
        self.updated_at = self.data.get("updated_at")
        self.debt_items: list[dict[str, Any]] = self.data.get("debt_items", [])

    @property
    def fingerprints(self) -> set[str]:
        """Get all fingerprints for findings in this module."""
        fps = set()
        for f in self.findings:
            fp = f.get("fingerprint")
            if fp:
                fps.add(fp)
        return fps

    @property
    def debt_count(self) -> int:
        """Number of unresolved debt items."""
        return len(self.debt_items)

    def get_oldest_debt_age_days(self) -> int:
        """Returns the age of the oldest debt item in days."""
        if not self.debt_items:
            return 0

        oldest = None
        for item in self.debt_items:
            first_seen = item.get("first_seen")
            if first_seen:
                try:
                    dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
                    if oldest is None or dt < oldest:
                        oldest = dt
                except (ValueError, TypeError):
                    pass

        if oldest:
            age = datetime.now(timezone.utc) - oldest
            return age.days
        return 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "module": self.module_name,
            "findings": self.findings,
            "debt_items": self.debt_items,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "debt_count": self.debt_count,
            "oldest_debt_age_days": self.get_oldest_debt_age_days(),
        }


class BaselineMeta:
    """Metadata for the baseline directory."""

    def __init__(self, data: dict[str, Any] | None = None):
        self.data = data or {}
        self.version = self.data.get("version", "2.0")
        self.created_at = self.data.get("created_at")
        self.updated_at = self.data.get("updated_at")
        self.modules = self.data.get("modules", [])
        self.total_findings = self.data.get("total_findings", 0)
        self.total_debt = self.data.get("total_debt", 0)
        self.migrated_from_legacy = self.data.get("migrated_from_legacy", False)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "modules": self.modules,
            "total_findings": self.total_findings,
            "total_debt": self.total_debt,
            "migrated_from_legacy": self.migrated_from_legacy,
        }


class BaselineManager:
    """
    Manages the lifecycle of the baseline.json file.
    """

    def __init__(self, project_root: Path, config: dict[str, Any] | None = None):
        self.project_root = project_root
        self.config = config or {}

        # Default Config
        self.baseline_config = self.config.get("baseline", {})
        self.enabled = self.baseline_config.get("enabled", False)

        # Resolve baseline path
        raw_path = self.baseline_config.get("path", ".warden/baseline.json")
        self.baseline_path = self.project_root / raw_path

        self.fetch_command = self.baseline_config.get("fetch_command")
        self.auto_fetch = self.baseline_config.get("auto_fetch", False)

    def fetch_latest_baseline(self) -> Path | None:
        """
        Fetches the latest baseline using the configured command.
        Returns the path if successful, None otherwise.
        """
        if not self.fetch_command:
            logger.debug("baseline_fetch_skip_no_command")
            return None

        logger.info("baseline_fetch_start", command=self.fetch_command)

        try:
            # Create parent dir if needed
            self.baseline_path.parent.mkdir(parents=True, exist_ok=True)

            # Security: Use shlex.split to avoid shell injection.
            # Complex shell commands (pipes, etc.) should be wrapped in a script.
            shell_chars = set("|><&;$`")
            if any(c in self.fetch_command for c in shell_chars):
                logger.error(
                    "fetch_command_has_shell_features",
                    command=self.fetch_command,
                    hint="Wrap complex commands (pipes, redirects) in a shell script.",
                )
                return None

            subprocess.run(
                shlex.split(self.fetch_command),
                shell=False,
                cwd=str(self.project_root),
                check=True,
                capture_output=True,
                text=True,
            )

            if self.baseline_path.exists():
                logger.info("baseline_fetch_success", path=str(self.baseline_path))
                return self.baseline_path
            else:
                logger.warning("baseline_fetch_completed_but_file_missing", path=str(self.baseline_path))
                return None

        except subprocess.CalledProcessError as e:
            logger.warning("baseline_fetch_failed", error=str(e), stderr=e.stderr)
            return None
        except Exception as e:
            logger.error("baseline_fetch_error", error=str(e))
            return None

    def load_baseline(self) -> dict[str, Any] | None:
        """
        Loads the baseline from disk.
        """
        if not self.baseline_path.exists():
            return None

        try:
            with open(self.baseline_path, encoding="utf-8") as f:
                data = json.load(f)
                return data
        except Exception as e:
            logger.error("baseline_load_failed", error=str(e))
            return None

    def is_outdated(self, max_age_hours: int = 24) -> bool:
        """
        Checks if the local baseline is outdated based on file modification time.
        """
        if not self.baseline_path.exists():
            return True

        mtime = datetime.fromtimestamp(self.baseline_path.stat().st_mtime)
        age = datetime.now() - mtime
        return age > timedelta(hours=max_age_hours)

    def get_fingerprints(self) -> set[str]:
        """
        Returns a set of fingerprints for all findings in the baseline.
        Fingerprint formation: hash(rule_id + file_path + line_context_hash + message)

        Note: File paths in baseline are relative to project root.
        """
        data = self.load_baseline()
        if not data:
            return set()

        findings = []
        # Handle structured report with frameResults
        if "frameResults" in data:
            for fr in data["frameResults"]:
                findings.extend(fr.get("findings", []))
        # Handle flat list or legacy format
        elif "findings" in data:
            findings = data["findings"]

        fingerprints = set()
        for f in findings:
            fp = f.get("fingerprint")
            if fp:
                fingerprints.add(fp)
            else:
                # Dynamic fingerprint generation if missing in baseline
                fingerprints.add(_compute_finding_fingerprint(f))

        return fingerprints

    # === Module-Based Baseline Methods (Phase 4.1) ===

    @property
    def baseline_dir(self) -> Path:
        """Directory for module-based baselines."""
        return self.project_root / ".warden" / "baseline"

    @property
    def meta_path(self) -> Path:
        """Path to _meta.json."""
        return self.baseline_dir / "_meta.json"

    def is_module_based(self) -> bool:
        """Check if using new module-based baseline structure."""
        return self.baseline_dir.exists() and self.meta_path.exists()

    def get_module_path(self, module_name: str) -> Path:
        """Get path to a module's baseline file."""
        safe_name = module_name.replace("/", "_").replace("\\", "_")
        return self.baseline_dir / f"{safe_name}.json"

    def load_meta(self) -> BaselineMeta | None:
        """Load baseline metadata."""
        if not self.meta_path.exists():
            return None

        try:
            with open(self.meta_path, encoding="utf-8") as f:
                data = json.load(f)
            return BaselineMeta(data)
        except Exception as e:
            logger.error("baseline_meta_load_failed", error=str(e))
            return None

    def save_meta(self, meta: BaselineMeta) -> bool:
        """Save baseline metadata."""
        try:
            self.baseline_dir.mkdir(parents=True, exist_ok=True)
            with open(self.meta_path, "w", encoding="utf-8") as f:
                json.dump(meta.to_dict(), f, indent=2)
            return True
        except Exception as e:
            logger.error("baseline_meta_save_failed", error=str(e))
            return False

    def load_module_baseline(self, module_name: str) -> ModuleBaseline | None:
        """Load a specific module's baseline."""
        module_path = self.get_module_path(module_name)
        if not module_path.exists():
            return None

        try:
            with open(module_path, encoding="utf-8") as f:
                data = json.load(f)
            return ModuleBaseline(module_name, data)
        except Exception as e:
            logger.error("module_baseline_load_failed", module=module_name, error=str(e))
            return None

    def save_module_baseline(self, module_baseline: ModuleBaseline) -> bool:
        """Save a module's baseline."""
        try:
            self.baseline_dir.mkdir(parents=True, exist_ok=True)
            module_path = self.get_module_path(module_baseline.module_name)

            # Update timestamps
            now = datetime.now(timezone.utc).isoformat()
            if not module_baseline.created_at:
                module_baseline.created_at = now
            module_baseline.updated_at = now

            with open(module_path, "w", encoding="utf-8") as f:
                json.dump(module_baseline.to_dict(), f, indent=2)
            return True
        except Exception as e:
            logger.error("module_baseline_save_failed", module=module_baseline.module_name, error=str(e))
            return False

    def list_modules(self) -> list[str]:
        """List all modules with baselines."""
        if not self.baseline_dir.exists():
            return []

        modules = []
        for f in self.baseline_dir.glob("*.json"):
            if f.name != "_meta.json":
                # Convert filename back to module name
                module_name = f.stem.replace("_", "/")
                modules.append(module_name)
        return modules

    def get_module_fingerprints(self, module_name: str) -> set[str]:
        """Get fingerprints for a specific module."""
        module_baseline = self.load_module_baseline(module_name)
        if module_baseline:
            return module_baseline.fingerprints
        return set()

    def get_all_fingerprints_by_module(self) -> dict[str, set[str]]:
        """Get fingerprints organized by module."""
        result = {}
        for module_name in self.list_modules():
            result[module_name] = self.get_module_fingerprints(module_name)
        return result

    def migrate_from_legacy(self, module_map: dict[str, Any] | None = None) -> bool:
        """
        Migrate from legacy single-file baseline to module-based structure.

        Args:
            module_map: Optional module mapping from intelligence to categorize findings.

        Returns:
            True if migration successful.
        """
        legacy_data = self.load_baseline()
        if not legacy_data:
            logger.info("no_legacy_baseline_to_migrate")
            return False

        logger.info("baseline_migration_start")

        # Extract all findings
        all_findings = []
        if "frameResults" in legacy_data:
            for fr in legacy_data["frameResults"]:
                all_findings.extend(fr.get("findings", []))
        elif "findings" in legacy_data:
            all_findings = legacy_data["findings"]

        # Categorize findings by module
        module_findings: dict[str, list[dict[str, Any]]] = {}

        for finding in all_findings:
            # Determine module from file path
            file_path = finding.get("file_path") or finding.get("path") or finding.get("file")
            if not file_path:
                location = finding.get("location", "")
                file_path = location.split(":")[0] if location else "unknown"

            module_name = self._determine_module(file_path, module_map)

            if module_name not in module_findings:
                module_findings[module_name] = []
            module_findings[module_name].append(finding)

        # Create module baselines
        now = datetime.now(timezone.utc).isoformat()
        total_findings = 0

        for module_name, findings in module_findings.items():
            module_baseline = ModuleBaseline(
                module_name,
                {
                    "findings": findings,
                    "debt_items": [],  # Fresh start for debt tracking
                    "created_at": now,
                    "updated_at": now,
                },
            )
            self.save_module_baseline(module_baseline)
            total_findings += len(findings)

        # Create meta
        meta = BaselineMeta(
            {
                "version": "2.0",
                "created_at": now,
                "updated_at": now,
                "modules": list(module_findings.keys()),
                "total_findings": total_findings,
                "total_debt": 0,
                "migrated_from_legacy": True,
            }
        )
        self.save_meta(meta)

        logger.info("baseline_migration_complete", modules=len(module_findings), findings=total_findings)

        return True

    def _determine_module(self, file_path: str, module_map: dict[str, Any] | None = None) -> str:
        """Determine which module a file belongs to."""
        if not file_path or file_path == "unknown":
            return "unknown"

        # Normalize path
        normalized = file_path.replace("\\", "/")

        # Try to use module_map if provided — use longest-prefix match to avoid
        # "auth" incorrectly claiming files from "auth_api/" (#152).
        if module_map:
            candidates = []
            for module_name, module_info in module_map.items():
                module_path = module_info.get("path", module_name)
                # Require a path separator after the prefix to prevent partial matches
                if normalized.startswith(module_path + "/") or normalized == module_path:
                    candidates.append((module_name, module_path))
            if candidates:
                # Pick the most specific (longest) match
                return max(candidates, key=lambda t: len(t[1]))[0]

        # Fall back to top-level directory
        parts = normalized.split("/")
        if len(parts) > 1:
            # Return first directory (e.g., "src", "auth", "lib")
            return parts[0]

        return "root"

    # === Debt Tracking Methods (Phase 4.3) ===

    def update_debt(self, module_name: str, current_findings: list[dict[str, Any]]) -> tuple[int, int, int]:
        """
        Update debt tracking for a module based on current scan findings.

        Args:
            module_name: The module being updated.
            current_findings: Findings from the current scan.

        Returns:
            Tuple of (new_debt, resolved_debt, total_debt)
        """
        module_baseline = self.load_module_baseline(module_name)
        if not module_baseline:
            # Create new baseline for this module
            module_baseline = ModuleBaseline(
                module_name, {"findings": [], "debt_items": [], "created_at": datetime.now(timezone.utc).isoformat()}
            )

        now = datetime.now(timezone.utc).isoformat()

        # Get current fingerprints
        current_fps = set()
        for f in current_findings:
            fp = f.get("fingerprint")
            if fp:
                current_fps.add(fp)
            else:
                # Generate canonical fingerprint using the shared algorithm (#151)
                fp = _compute_finding_fingerprint(f)
                f["fingerprint"] = fp
                current_fps.add(fp)

        # Get baseline fingerprints
        baseline_fps = module_baseline.fingerprints

        # Find new findings (not in baseline)
        new_fps = current_fps - baseline_fps

        # Update debt items
        existing_debt_fps = {d.get("fingerprint") for d in module_baseline.debt_items}

        # Add new debt items for findings not already tracked
        new_debt = 0
        for finding in current_findings:
            fp = finding.get("fingerprint")
            if fp in new_fps and fp not in existing_debt_fps:
                debt_item = {
                    "fingerprint": fp,
                    "first_seen": now,
                    "rule_id": get_finding_attribute(finding, "id")
                    or get_finding_attribute(finding, "rule_id")
                    or get_finding_attribute(finding, "ruleId"),
                    "file_path": get_finding_attribute(finding, "file_path")
                    or get_finding_attribute(finding, "path")
                    or get_finding_attribute(finding, "file"),
                    "message": get_finding_attribute(finding, "message"),
                    "severity": get_finding_attribute(finding, "severity"),
                }
                module_baseline.debt_items.append(debt_item)
                new_debt += 1

        # Remove resolved debt items (debt whose fingerprint is no longer in current findings)
        # A debt item is resolved if its fingerprint is not in current_fps
        resolved_debt_fps = existing_debt_fps - current_fps
        resolved_debt = len(resolved_debt_fps)

        # Keep only debt items that are still present in current findings
        module_baseline.debt_items = [d for d in module_baseline.debt_items if d.get("fingerprint") in current_fps]

        # Update findings
        module_baseline.findings = current_findings
        module_baseline.updated_at = now

        # Save
        self.save_module_baseline(module_baseline)

        return new_debt, resolved_debt, module_baseline.debt_count

    def get_debt_report(self) -> dict[str, Any]:
        """
        Generate a comprehensive debt report across all modules.

        Returns:
            Dict with debt information by module.
        """
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_debt": 0,
            "modules": {},
            "warnings": [],
        }

        for module_name in self.list_modules():
            module_baseline = self.load_module_baseline(module_name)
            if not module_baseline:
                continue

            oldest_age = module_baseline.get_oldest_debt_age_days()
            debt_count = module_baseline.debt_count

            module_report = {
                "debt_count": debt_count,
                "oldest_debt_age_days": oldest_age,
                "debt_items": module_baseline.debt_items,
            }

            report["modules"][module_name] = module_report
            report["total_debt"] += debt_count

            # Generate warnings based on age thresholds
            if oldest_age >= 30:
                report["warnings"].append(
                    {
                        "level": "critical",
                        "module": module_name,
                        "message": f"Module '{module_name}' has debt older than 30 days ({oldest_age} days)",
                    }
                )
            elif oldest_age >= 14:
                report["warnings"].append(
                    {
                        "level": "warning",
                        "module": module_name,
                        "message": f"Module '{module_name}' has debt older than 14 days ({oldest_age} days)",
                    }
                )
            elif oldest_age >= 7:
                report["warnings"].append(
                    {
                        "level": "info",
                        "module": module_name,
                        "message": f"Module '{module_name}' has debt older than 7 days ({oldest_age} days)",
                    }
                )

        return report

    # === Baseline Update Strategy (Phase 4.2) ===

    def update_baseline_for_modules(
        self,
        scan_results: dict[str, Any],
        modules_to_update: list[str] | None = None,
        module_map: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Update baseline for specific modules based on scan results.

        Args:
            scan_results: Results from a scan run.
            modules_to_update: Specific modules to update (None = all changed).
            module_map: Module mapping from intelligence.

        Returns:
            Dict with update statistics.
        """
        # Ensure we're using module-based structure
        if not self.is_module_based():
            # Try migration first
            self.migrate_from_legacy(module_map)

        # Extract findings from scan results
        all_findings = []
        if "frameResults" in scan_results:
            for fr in scan_results["frameResults"]:
                all_findings.extend(fr.get("findings", []))
        elif "findings" in scan_results:
            all_findings = scan_results["findings"]

        # Group findings by module
        findings_by_module: dict[str, list[dict[str, Any]]] = {}
        for finding in all_findings:
            file_path = finding.get("file_path") or finding.get("path") or finding.get("file", "unknown")
            module_name = self._determine_module(file_path, module_map)

            if modules_to_update and module_name not in modules_to_update:
                continue

            if module_name not in findings_by_module:
                findings_by_module[module_name] = []
            findings_by_module[module_name].append(finding)

        # Update each module
        stats = {"modules_updated": 0, "total_new_debt": 0, "total_resolved_debt": 0, "modules": {}}

        for module_name, findings in findings_by_module.items():
            new_debt, resolved_debt, total_debt = self.update_debt(module_name, findings)

            stats["modules"][module_name] = {
                "findings": len(findings),
                "new_debt": new_debt,
                "resolved_debt": resolved_debt,
                "total_debt": total_debt,
            }
            stats["modules_updated"] += 1
            stats["total_new_debt"] += new_debt
            stats["total_resolved_debt"] += resolved_debt

        # Update meta
        meta = self.load_meta() or BaselineMeta()
        meta.updated_at = datetime.now(timezone.utc).isoformat()
        meta.modules = self.list_modules()
        meta.total_findings = sum(len(mb.findings) if (mb := self.load_module_baseline(m)) else 0 for m in meta.modules)
        meta.total_debt = sum(mb.debt_count if (mb := self.load_module_baseline(m)) else 0 for m in meta.modules)
        self.save_meta(meta)

        logger.info("baseline_update_complete", **stats)
        return stats
