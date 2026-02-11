"""
CI Manager - Main orchestrator class.

Manages CI/CD workflow files with resilience and observability.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .exceptions import FileOperationError, SecurityError, TemplateError, ValidationError
from .file_operations import atomic_write, compute_checksum, safe_read_file
from .provider_detection import CIProvider, detect_branch, detect_provider
from .template_operations import (
    CURRENT_TEMPLATE_VERSION,
    add_version_header,
    extract_custom_sections,
    extract_version,
    load_template,
    merge_custom_sections,
    prepare_template_variables,
)
from .validation import validate_branch
from .workflow_definitions import (
    CIStatus,
    WorkflowStatus,
    get_workflows_for_provider,
)

try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


MAX_FILE_SIZE = 1024 * 1024  # 1MB


class CIManager:
    """
    Manages CI/CD workflow files with resilience and observability.

    Design Principles:
        - Fail Fast: Validate inputs immediately
        - Idempotent: Same inputs produce same outputs
        - Atomic: Use temp files + rename for writes
        - Observable: Log every significant operation
        - Secure: Sanitize all paths and inputs
    """

    __slots__ = ("_project_root", "_config", "_config_loaded")

    def __init__(
        self,
        project_root: Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize CI Manager with validation.

        Args:
            project_root: Project root directory (must exist)
            config: Optional Warden configuration dict

        Raises:
            ValidationError: If project_root is invalid
        """
        # Fail Fast: Validate project root
        if not isinstance(project_root, Path):
            project_root = Path(project_root)

        resolved = project_root.resolve()
        if not resolved.exists():
            raise ValidationError(f"Project root does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValidationError(f"Project root is not a directory: {resolved}")

        self._project_root: Path = resolved
        self._config: dict[str, Any] = config or {}
        self._config_loaded: bool = bool(config)

        logger.info(
            "ci_manager_initialized",
            project_root=str(self._project_root),
            config_provided=bool(config),
        )

    @property
    def project_root(self) -> Path:
        """Immutable access to project root."""
        return self._project_root

    @property
    def config(self) -> dict[str, Any]:
        """Lazy-loaded configuration."""
        if not self._config_loaded:
            self._load_config()
        return self._config

    def _load_config(self) -> None:
        """Load Warden configuration with error handling."""
        if self._config_loaded:
            return

        config_path = self._project_root / ".warden" / "config.yaml"

        if not config_path.exists():
            logger.debug("ci_manager_config_not_found", path=str(config_path))
            self._config_loaded = True
            return

        try:
            # Security: Check file size before reading
            if config_path.stat().st_size > MAX_FILE_SIZE:
                logger.warning(
                    "ci_manager_config_too_large",
                    path=str(config_path),
                    max_size=MAX_FILE_SIZE,
                )
                self._config_loaded = True
                return

            with open(config_path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                self._config = loaded if isinstance(loaded, dict) else {}

            logger.debug("ci_manager_config_loaded", path=str(config_path))

        except yaml.YAMLError as e:
            logger.error("ci_manager_config_yaml_error", path=str(config_path), error=str(e))
        except PermissionError as e:
            logger.error("ci_manager_config_permission_error", path=str(config_path), error=str(e))
        except Exception as e:
            logger.error("ci_manager_config_load_failed", path=str(config_path), error=str(e))
        finally:
            self._config_loaded = True

    def _get_llm_config(self) -> dict[str, Any]:
        """Get LLM configuration with safe defaults."""
        return self.config.get("llm", {"provider": "ollama"})

    def get_status(self) -> CIStatus:
        """
        Get current CI configuration status.

        This operation is idempotent and read-only.

        Returns:
            CIStatus with all workflow statuses
        """
        status = CIStatus()

        # Detect provider
        status.provider = detect_provider(self._project_root)

        if not status.provider:
            logger.debug("ci_status_no_provider")
            return status

        status.is_configured = True
        status.template_version = CURRENT_TEMPLATE_VERSION

        # Check each workflow
        workflows = get_workflows_for_provider(status.provider)

        for wf in workflows:
            wf_path = self._project_root / wf.target_path
            wf_status = WorkflowStatus(
                exists=wf_path.exists(),
                path=wf.target_path,
            )

            if wf_status.exists:
                content = safe_read_file(wf_path)

                if content is None:
                    wf_status.error = "Failed to read file"
                else:
                    wf_status.version = extract_version(content)
                    wf_status.checksum = compute_checksum(content)

                    # Check if outdated
                    if wf_status.version:
                        wf_status.is_outdated = wf_status.version != CURRENT_TEMPLATE_VERSION
                    else:
                        wf_status.is_outdated = True

                    # Check for custom sections
                    custom_sections = extract_custom_sections(content)
                    if custom_sections:
                        wf_status.has_custom_sections = True
                        wf_status.custom_sections = [s[0] for s in custom_sections]

                    # Get last modified
                    try:
                        stat = wf_path.stat()
                        wf_status.last_modified = datetime.fromtimestamp(stat.st_mtime)
                    except (OSError, ValueError):  # CI operation best-effort
                        pass

                    if wf_status.is_outdated:
                        status.needs_update = True

            status.workflows[wf.workflow_type.value] = wf_status

        logger.info(
            "ci_status_checked",
            provider=status.provider.value if status.provider else None,
            is_configured=status.is_configured,
            needs_update=status.needs_update,
            workflow_count=len(status.workflows),
        )

        return status

    def init(
        self,
        provider: CIProvider,
        branch: str = "main",
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Initialize CI workflows for a provider.

        Idempotent: With force=False, existing files are skipped.
        Atomic: Uses temp file + rename for each write.

        Args:
            provider: CI provider to use
            branch: Default branch name
            force: Overwrite existing files

        Returns:
            Dict with created file paths and status
        """
        logger.info(
            "ci_init_started",
            provider=provider.value,
            branch=branch,
            force=force,
        )

        result: dict[str, Any] = {
            "success": True,
            "provider": provider.value,
            "created": [],
            "skipped": [],
            "errors": [],
        }

        # Validate branch (fail fast)
        try:
            branch = validate_branch(branch)
        except ValidationError as e:
            result["errors"].append(str(e))
            result["success"] = False
            return result

        workflows = get_workflows_for_provider(provider)

        if not workflows:
            result["errors"].append(f"No workflows defined for provider: {provider.value}")
            result["success"] = False
            return result

        template_vars = prepare_template_variables(branch, self._get_llm_config())

        for wf in workflows:
            target_path = self._project_root / wf.target_path

            # Idempotent: Skip if exists and not forced
            if target_path.exists() and not force:
                result["skipped"].append(wf.target_path)
                logger.debug("ci_workflow_skipped", path=wf.target_path, reason="exists")
                continue

            try:
                # Load and process template
                template_content = load_template(wf.template_name)
                content = template_content.format(**template_vars)
                content = add_version_header(content)

                # Atomic write
                with atomic_write(target_path, self._project_root) as f:
                    f.write(content)

                result["created"].append(wf.target_path)
                logger.info("ci_workflow_created", path=wf.target_path)

            except (TemplateError, FileOperationError, SecurityError) as e:
                result["errors"].append(f"{wf.target_path}: {e}")
                logger.error("ci_workflow_create_failed", path=wf.target_path, error=str(e))
            except KeyError as e:
                result["errors"].append(f"{wf.target_path}: Missing template variable: {e}")
                logger.error("ci_workflow_template_error", path=wf.target_path, missing_var=str(e))
            except Exception as e:
                result["errors"].append(f"{wf.target_path}: Unexpected error: {e}")
                logger.error("ci_workflow_unexpected_error", path=wf.target_path, error=str(e))

        result["success"] = len(result["errors"]) == 0

        logger.info(
            "ci_init_completed",
            success=result["success"],
            created=len(result["created"]),
            skipped=len(result["skipped"]),
            errors=len(result["errors"]),
        )

        return result

    def update(
        self,
        preserve_custom: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Update CI workflows from templates.

        Preserves custom sections marked with WARDEN-CUSTOM.
        Atomic: Uses temp file + rename for each write.

        Args:
            preserve_custom: Preserve custom sections
            dry_run: Show what would be updated without making changes

        Returns:
            Dict with update results
        """
        logger.info(
            "ci_update_started",
            preserve_custom=preserve_custom,
            dry_run=dry_run,
        )

        status = self.get_status()

        if not status.provider:
            return {
                "success": False,
                "error": "No CI provider detected. Run 'warden ci init' first.",
            }

        result: dict[str, Any] = {
            "success": True,
            "provider": status.provider.value,
            "updated": [],
            "unchanged": [],
            "errors": [],
            "dry_run": dry_run,
        }

        workflows = get_workflows_for_provider(status.provider)
        branch = detect_branch(self._project_root)
        template_vars = prepare_template_variables(branch, self._get_llm_config())

        for wf in workflows:
            target_path = self._project_root / wf.target_path
            wf_status = status.workflows.get(wf.workflow_type.value)

            if not wf_status or not wf_status.exists:
                continue

            if not wf_status.is_outdated:
                result["unchanged"].append(wf.target_path)
                continue

            try:
                # Load and process template
                template_content = load_template(wf.template_name)
                new_content = template_content.format(**template_vars)

                # Preserve custom sections if requested
                if preserve_custom and wf_status.has_custom_sections:
                    existing_content = safe_read_file(target_path)
                    if existing_content:
                        custom_sections = extract_custom_sections(existing_content)
                        new_content = merge_custom_sections(new_content, custom_sections)

                new_content = add_version_header(new_content)

                if not dry_run:
                    with atomic_write(target_path, self._project_root) as f:
                        f.write(new_content)

                result["updated"].append({
                    "path": wf.target_path,
                    "old_version": wf_status.version,
                    "new_version": CURRENT_TEMPLATE_VERSION,
                    "preserved_custom": wf_status.has_custom_sections and preserve_custom,
                })

                logger.info(
                    "ci_workflow_updated",
                    path=wf.target_path,
                    old_version=wf_status.version,
                    new_version=CURRENT_TEMPLATE_VERSION,
                    dry_run=dry_run,
                )

            except (TemplateError, FileOperationError, SecurityError) as e:
                result["errors"].append(f"{wf.target_path}: {e}")
                logger.error("ci_workflow_update_failed", path=wf.target_path, error=str(e))
            except Exception as e:
                result["errors"].append(f"{wf.target_path}: Unexpected error: {e}")
                logger.error("ci_workflow_update_unexpected", path=wf.target_path, error=str(e))

        result["success"] = len(result["errors"]) == 0

        logger.info(
            "ci_update_completed",
            success=result["success"],
            updated=len(result["updated"]),
            unchanged=len(result["unchanged"]),
            errors=len(result["errors"]),
            dry_run=dry_run,
        )

        return result

    def sync(self) -> dict[str, Any]:
        """
        Sync CI workflows with current Warden configuration.

        Updates LLM provider settings and environment variables
        without changing workflow structure.

        Returns:
            Dict with sync results
        """
        logger.info("ci_sync_started")

        status = self.get_status()

        if not status.provider:
            return {
                "success": False,
                "error": "No CI provider detected. Run 'warden ci init' first.",
            }

        result: dict[str, Any] = {
            "success": True,
            "provider": status.provider.value,
            "synced": [],
            "errors": [],
        }

        workflows = get_workflows_for_provider(status.provider)
        llm_config = self._get_llm_config()
        provider_id = str(llm_config.get("provider", "ollama"))

        for wf in workflows:
            target_path = self._project_root / wf.target_path

            if not target_path.exists():
                continue

            try:
                content = safe_read_file(target_path)
                if content is None:
                    result["errors"].append(f"{wf.target_path}: Failed to read file")
                    continue

                # Update CI_LLM_PROVIDER
                content = re.sub(
                    r'CI_LLM_PROVIDER:\s*\w+',
                    f'CI_LLM_PROVIDER: {provider_id}',
                    content
                )

                # Update version timestamp
                timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                content = re.sub(
                    r'# Generated:.*',
                    f'# Generated: {timestamp} (synced)',
                    content
                )

                with atomic_write(target_path, self._project_root) as f:
                    f.write(content)

                result["synced"].append(wf.target_path)
                logger.info("ci_workflow_synced", path=wf.target_path, provider=provider_id)

            except (FileOperationError, SecurityError) as e:
                result["errors"].append(f"{wf.target_path}: {e}")
                logger.error("ci_workflow_sync_failed", path=wf.target_path, error=str(e))
            except Exception as e:
                result["errors"].append(f"{wf.target_path}: Unexpected error: {e}")
                logger.error("ci_workflow_sync_unexpected", path=wf.target_path, error=str(e))

        result["success"] = len(result["errors"]) == 0

        logger.info(
            "ci_sync_completed",
            success=result["success"],
            synced=len(result["synced"]),
            errors=len(result["errors"]),
        )

        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert CI status to dictionary for JSON serialization."""
        status = self.get_status()

        return {
            "provider": status.provider.value if status.provider else None,
            "is_configured": status.is_configured,
            "needs_update": status.needs_update,
            "template_version": status.template_version,
            "workflows": {
                name: {
                    "exists": wf.exists,
                    "path": wf.path,
                    "version": wf.version,
                    "is_outdated": wf.is_outdated,
                    "has_custom_sections": wf.has_custom_sections,
                    "custom_sections": wf.custom_sections,
                    "last_modified": wf.last_modified.isoformat() if wf.last_modified else None,
                    "error": wf.error,
                }
                for name, wf in status.workflows.items()
            },
        }
