"""
Auto-Fix Application Service.

Applies fortification fixes to source files with safety guarantees:
- Git checkpoint before changes
- Syntax validation after each fix
- Automatic rollback on failure
- Dry-run mode for preview
"""

import tempfile
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class AutoFixResult:
    """Result of auto-fix operation."""

    def __init__(self):
        self.applied: list[dict[str, Any]] = []
        self.skipped: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []
        self.dry_run: bool = False

    @property
    def summary(self) -> str:
        return (
            f"{len(self.applied)} applied / "
            f"{len(self.skipped)} skipped / "
            f"{len(self.failed)} failed"
        )


class AutoFixer:
    """
    Applies fortification fixes with git safety net.

    Usage:
        fixer = AutoFixer(project_root, dry_run=False)
        result = await fixer.apply_fixes(fortifications)
    """

    def __init__(self, project_root: Path, dry_run: bool = False):
        self.project_root = project_root
        self.dry_run = dry_run
        self._checkpoint_manager = None

    async def apply_fixes(self, fortifications: list[dict[str, Any]]) -> AutoFixResult:
        """
        Apply fortification fixes to source files.

        Args:
            fortifications: List of fortification dicts with suggested_code, file_path, etc.

        Returns:
            AutoFixResult with counts of applied/skipped/failed.
        """
        from warden.fortification.infrastructure.git_checkpoint import (
            GitCheckpointManager, GitCheckpointError
        )

        result = AutoFixResult()
        result.dry_run = self.dry_run

        # Filter to auto-fixable only
        fixable = [f for f in fortifications if f.get("auto_fixable", False)]

        if not fixable:
            logger.info("auto_fix_no_fixable_items", total=len(fortifications))
            return result

        # Create checkpoint (skip in dry-run)
        if not self.dry_run:
            try:
                self._checkpoint_manager = GitCheckpointManager(self.project_root)
                self._checkpoint_manager.create_checkpoint()
            except GitCheckpointError as e:
                logger.warning("auto_fix_checkpoint_failed", error=str(e))
                # Continue without checkpoint - user was warned

        for fix in fixable:
            file_path_str = fix.get("file_path")
            suggested_code = fix.get("suggested_code") or fix.get("code")
            original_code = fix.get("original_code")
            line_number = fix.get("line_number", 0)

            if not file_path_str or not suggested_code:
                result.skipped.append({**fix, "reason": "missing file_path or suggested_code"})
                continue

            file_path = self.project_root / file_path_str
            if not file_path.exists():
                result.skipped.append({**fix, "reason": f"file not found: {file_path_str}"})
                continue

            if self.dry_run:
                logger.info("auto_fix_dry_run", file=file_path_str, line=line_number)
                result.applied.append({**fix, "dry_run": True})
                continue

            # Apply fix
            success = self._apply_single_fix(file_path, original_code, suggested_code, fix)

            if success:
                result.applied.append(fix)
                if self._checkpoint_manager:
                    self._checkpoint_manager.record_modification(file_path_str)
            else:
                result.failed.append(fix)

        logger.info(
            "auto_fix_complete",
            applied=len(result.applied),
            skipped=len(result.skipped),
            failed=len(result.failed),
            dry_run=self.dry_run
        )

        return result

    def _apply_single_fix(
        self,
        file_path: Path,
        original_code: str | None,
        suggested_code: str,
        fix: dict[str, Any]
    ) -> bool:
        """
        Apply a single fix with syntax validation and rollback.

        Returns:
            True if fix was applied successfully.
        """
        rel_path = str(file_path.relative_to(self.project_root))

        try:
            content = file_path.read_text(encoding="utf-8")

            if original_code and original_code in content:
                new_content = content.replace(original_code, suggested_code, 1)
            else:
                # Can't find original code - skip
                logger.warning("auto_fix_original_not_found", file=rel_path)
                return False

            # Atomic write: write to temp, then replace
            import os
            tmp_fd = None
            tmp_path = None
            try:
                tmp_fd, tmp_path = tempfile.mkstemp(
                    suffix=file_path.suffix,
                    dir=file_path.parent,
                    prefix=".warden_fix_"
                )
                with os.fdopen(tmp_fd, 'w') as f:
                    f.write(new_content)
                    tmp_fd = None  # fd is now owned by fdopen

                # Validate syntax before committing
                if self._checkpoint_manager and not self._checkpoint_manager.validate_syntax(Path(tmp_path)):
                    logger.warning("auto_fix_syntax_error", file=rel_path)
                    os.unlink(tmp_path)
                    return False

                # Commit the fix
                os.replace(tmp_path, file_path)
                logger.info("auto_fix_applied", file=rel_path)
                return True

            except Exception:
                # Clean up temp file
                if tmp_fd is not None:
                    os.close(tmp_fd)
                if tmp_path is not None:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
                raise

        except Exception as e:
            logger.error("auto_fix_apply_failed", file=rel_path, error=str(e))

            # Rollback on failure
            if self._checkpoint_manager:
                self._checkpoint_manager.rollback_file(rel_path)

            return False
