"""
CI Manager Service

Central service for managing CI/CD workflow files.
Provides init, update, sync, and status operations for CI workflows.

Chaos Engineering Principles Applied:
- Fail Fast: Early validation, strict input checks
- Idempotent: Same operation = same result
- Defensive: Path traversal protection, input sanitization
- Observable: Structured logging for every failure mode
- Resilient: Graceful degradation, atomic operations
"""

from __future__ import annotations

import re
import hashlib
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Final, FrozenSet, Generator, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import importlib.resources
import yaml

try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


# =============================================================================
# Constants (Immutable)
# =============================================================================

CURRENT_TEMPLATE_VERSION: Final[str] = "1.0.0"
CUSTOM_SECTION_START: Final[str] = "# WARDEN-CUSTOM-START"
CUSTOM_SECTION_END: Final[str] = "# WARDEN-CUSTOM-END"
VERSION_HEADER_PATTERN: Final[str] = r"^# Warden CI v(\d+\.\d+\.\d+)"

# Security: Allowed characters in branch names
SAFE_BRANCH_PATTERN: Final[re.Pattern] = re.compile(r'^[\w\-./]+$')
MAX_BRANCH_LENGTH: Final[int] = 256
MAX_FILE_SIZE: Final[int] = 1024 * 1024  # 1MB max workflow file

# Allowed template names (whitelist)
ALLOWED_TEMPLATES: Final[FrozenSet[str]] = frozenset({
    "github.yml", "gitlab.yml", "warden-pr.yml",
    "warden-nightly.yml", "warden-release.yml"
})


# =============================================================================
# Custom Exceptions (Fail Fast)
# =============================================================================

class CIManagerError(Exception):
    """Base exception for CI Manager errors."""
    pass


class ValidationError(CIManagerError):
    """Input validation failed."""
    pass


class SecurityError(CIManagerError):
    """Security violation detected."""
    pass


class TemplateError(CIManagerError):
    """Template loading or processing failed."""
    pass


class FileOperationError(CIManagerError):
    """File system operation failed."""
    pass


# =============================================================================
# Enums (Strict Types)
# =============================================================================

class CIProvider(Enum):
    """Supported CI providers."""
    GITHUB = "github"
    GITLAB = "gitlab"

    @classmethod
    def from_string(cls, value: str) -> "CIProvider":
        """
        Safe conversion from string with fail-fast validation.

        Raises:
            ValidationError: If value is not a valid provider
        """
        if not value or not isinstance(value, str):
            raise ValidationError("Provider must be a non-empty string")

        normalized = value.lower().strip()
        try:
            return cls(normalized)
        except ValueError:
            valid = ", ".join(p.value for p in cls)
            raise ValidationError(f"Invalid provider: '{value}'. Valid: {valid}")


class WorkflowType(Enum):
    """Types of CI workflows."""
    PR = "pr"
    NIGHTLY = "nightly"
    RELEASE = "release"
    MAIN = "main"


# =============================================================================
# Data Classes (Immutable where possible)
# =============================================================================

@dataclass(frozen=True)
class WorkflowTemplate:
    """Immutable workflow template definition."""
    provider: CIProvider
    workflow_type: WorkflowType
    template_name: str
    target_path: str
    version: str = CURRENT_TEMPLATE_VERSION
    description: str = ""

    def __post_init__(self) -> None:
        """Validate template on creation (fail fast)."""
        if self.template_name not in ALLOWED_TEMPLATES:
            raise ValidationError(f"Template not in whitelist: {self.template_name}")
        if ".." in self.target_path or self.target_path.startswith("/"):
            raise SecurityError(f"Invalid target path: {self.target_path}")


@dataclass
class WorkflowStatus:
    """Status of a CI workflow file."""
    exists: bool
    path: str
    version: Optional[str] = None
    is_outdated: bool = False
    has_custom_sections: bool = False
    custom_sections: List[str] = field(default_factory=list)
    last_modified: Optional[datetime] = None
    checksum: Optional[str] = None
    error: Optional[str] = None  # Capture any read errors


@dataclass
class CIStatus:
    """Overall CI configuration status."""
    provider: Optional[CIProvider] = None
    workflows: Dict[str, WorkflowStatus] = field(default_factory=dict)
    is_configured: bool = False
    needs_update: bool = False
    template_version: str = CURRENT_TEMPLATE_VERSION


# =============================================================================
# Workflow Definitions (Immutable)
# =============================================================================

GITHUB_WORKFLOWS: Final[Tuple[WorkflowTemplate, ...]] = (
    WorkflowTemplate(
        provider=CIProvider.GITHUB,
        workflow_type=WorkflowType.PR,
        template_name="warden-pr.yml",
        target_path=".github/workflows/warden-pr.yml",
        description="PR scans with diff analysis",
    ),
    WorkflowTemplate(
        provider=CIProvider.GITHUB,
        workflow_type=WorkflowType.NIGHTLY,
        template_name="warden-nightly.yml",
        target_path=".github/workflows/warden-nightly.yml",
        description="Nightly full scans with baseline updates",
    ),
    WorkflowTemplate(
        provider=CIProvider.GITHUB,
        workflow_type=WorkflowType.RELEASE,
        template_name="warden-release.yml",
        target_path=".github/workflows/warden-release.yml",
        description="Release security audits",
    ),
    WorkflowTemplate(
        provider=CIProvider.GITHUB,
        workflow_type=WorkflowType.MAIN,
        template_name="github.yml",
        target_path=".github/workflows/warden.yml",
        description="Main push/PR workflow",
    ),
)

GITLAB_WORKFLOWS: Final[Tuple[WorkflowTemplate, ...]] = (
    WorkflowTemplate(
        provider=CIProvider.GITLAB,
        workflow_type=WorkflowType.MAIN,
        template_name="gitlab.yml",
        target_path=".gitlab-ci.yml",
        description="GitLab CI pipeline with all stages",
    ),
)

# Provider to workflows mapping
PROVIDER_WORKFLOWS: Final[Dict[CIProvider, Tuple[WorkflowTemplate, ...]]] = {
    CIProvider.GITHUB: GITHUB_WORKFLOWS,
    CIProvider.GITLAB: GITLAB_WORKFLOWS,
}


# =============================================================================
# CI Manager Class
# =============================================================================

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
        config: Optional[Dict[str, Any]] = None,
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
        self._config: Dict[str, Any] = config or {}
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
    def config(self) -> Dict[str, Any]:
        """Lazy-loaded configuration."""
        if not self._config_loaded:
            self._load_config()
        return self._config

    # =========================================================================
    # Private: Configuration
    # =========================================================================

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

            with open(config_path, "r", encoding="utf-8") as f:
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

    def _get_llm_config(self) -> Dict[str, Any]:
        """Get LLM configuration with safe defaults."""
        return self.config.get("llm", {"provider": "ollama"})

    # =========================================================================
    # Private: Validation & Security
    # =========================================================================

    def _validate_branch(self, branch: str) -> str:
        """
        Validate and sanitize branch name.

        Raises:
            ValidationError: If branch name is invalid
        """
        if not branch or not isinstance(branch, str):
            raise ValidationError("Branch must be a non-empty string")

        branch = branch.strip()

        if len(branch) > MAX_BRANCH_LENGTH:
            raise ValidationError(f"Branch name too long: max {MAX_BRANCH_LENGTH} chars")

        if not SAFE_BRANCH_PATTERN.match(branch):
            raise ValidationError(f"Invalid branch name: '{branch}'. Use alphanumeric, dash, dot, slash only.")

        return branch

    def _validate_path_within_project(self, path: Path) -> Path:
        """
        Ensure path is within project root (prevent traversal).

        Raises:
            SecurityError: If path escapes project root
        """
        resolved = (self._project_root / path).resolve()

        try:
            resolved.relative_to(self._project_root)
        except ValueError:
            raise SecurityError(f"Path traversal detected: {path}")

        return resolved

    # =========================================================================
    # Private: Template Operations
    # =========================================================================

    def _load_template(self, template_name: str) -> str:
        """
        Load template content with validation.

        Raises:
            TemplateError: If template cannot be loaded
        """
        # Whitelist check (fail fast)
        if template_name not in ALLOWED_TEMPLATES:
            raise TemplateError(f"Template not allowed: {template_name}")

        try:
            content = importlib.resources.read_text(
                "warden.templates.workflows",
                template_name
            )

            if not content or not content.strip():
                raise TemplateError(f"Template is empty: {template_name}")

            logger.debug("ci_template_loaded", template=template_name, size=len(content))
            return content

        except FileNotFoundError:
            raise TemplateError(f"Template not found: {template_name}")
        except Exception as e:
            raise TemplateError(f"Failed to load template '{template_name}': {e}")

    def _add_version_header(self, content: str) -> str:
        """Add version header to workflow content."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        header = (
            f"# Warden CI v{CURRENT_TEMPLATE_VERSION}\n"
            f"# Generated: {timestamp}\n"
            f"# Do not edit sections marked WARDEN-MANAGED\n\n"
        )
        return header + content

    def _extract_version(self, content: str) -> Optional[str]:
        """Extract version from workflow file content."""
        if not content:
            return None
        match = re.search(VERSION_HEADER_PATTERN, content, re.MULTILINE)
        return match.group(1) if match else None

    def _extract_custom_sections(self, content: str) -> List[Tuple[str, str]]:
        """Extract custom sections from workflow file."""
        if not content:
            return []

        custom_sections: List[Tuple[str, str]] = []
        pattern = rf"{re.escape(CUSTOM_SECTION_START)}\s*(\w+)?\n(.*?){re.escape(CUSTOM_SECTION_END)}"

        for match in re.finditer(pattern, content, re.DOTALL):
            section_name = match.group(1) or "unnamed"
            section_content = match.group(2)
            custom_sections.append((section_name, section_content))

        return custom_sections

    def _merge_custom_sections(
        self,
        new_content: str,
        custom_sections: List[Tuple[str, str]],
    ) -> str:
        """Merge custom sections into new content."""
        if not custom_sections:
            return new_content

        # Find insertion point (before jobs section or at end)
        insertion_point = new_content.find("\njobs:")
        if insertion_point == -1:
            insertion_point = len(new_content)

        custom_block = "\n"
        for name, content in custom_sections:
            custom_block += f"{CUSTOM_SECTION_START} {name}\n"
            custom_block += content
            if not content.endswith("\n"):
                custom_block += "\n"
            custom_block += f"{CUSTOM_SECTION_END}\n"

        return (
            new_content[:insertion_point] +
            custom_block +
            new_content[insertion_point:]
        )

    def _compute_checksum(self, content: str) -> str:
        """Compute checksum of content (excluding dynamic header)."""
        lines = content.split("\n")
        content_lines = [
            line for line in lines
            if not line.startswith("# Warden CI v")
            and not line.startswith("# Generated:")
        ]
        return hashlib.sha256("\n".join(content_lines).encode()).hexdigest()[:12]

    def _prepare_template_variables(self, branch: str) -> Dict[str, str]:
        """Prepare template variables for substitution."""
        branch = self._validate_branch(branch)
        llm_config = self._get_llm_config()
        provider_id = str(llm_config.get("provider", "ollama"))

        # Build environment variables section
        ci_env_vars = ""
        ollama_setup = ""

        if provider_id == "ollama":
            ci_env_vars = "      OLLAMA_HOST: http://localhost:11434"
            ollama_setup = """      - name: Setup Ollama
        run: |
          curl -fsSL https://ollama.com/install.sh | sh
          ollama serve &
          echo "Waiting for Ollama to be ready..."
          for i in {1..30}; do
            if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
              echo "Ollama is ready!"
              break
            fi
            echo "Attempt $i/30: Ollama not ready yet..."
            sleep 1
          done
          ollama pull qwen2.5-coder:0.5b

"""
        else:
            key_var_map: Dict[str, str] = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "groq": "GROQ_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
                "azure": "AZURE_OPENAI_API_KEY",
                "azure_openai": "AZURE_OPENAI_API_KEY",
            }
            key_var = key_var_map.get(provider_id)
            if key_var:
                ci_env_vars = f"      {key_var}: ${{{{ secrets.{key_var} }}}}"

        return {
            "branch": branch,
            "ci_llm_provider": provider_id,
            "ci_env_vars": ci_env_vars,
            "ollama_setup": ollama_setup,
        }

    # =========================================================================
    # Private: File Operations (Atomic)
    # =========================================================================

    @contextmanager
    def _atomic_write(self, target_path: Path) -> Generator[Any, None, None]:
        """
        Context manager for atomic file writes.

        Uses temp file + rename pattern for crash safety.
        """
        # Validate path is within project
        safe_path = self._validate_path_within_project(target_path)

        # Create parent directory if needed
        safe_path.parent.mkdir(parents=True, exist_ok=True)

        # Create temp file in same directory (for atomic rename)
        temp_fd = None
        temp_path = None

        try:
            temp_fd, temp_path_str = tempfile.mkstemp(
                dir=safe_path.parent,
                prefix=".warden_",
                suffix=".tmp"
            )
            temp_path = Path(temp_path_str)

            # Yield file handle for writing
            import os
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                temp_fd = None  # fd is now owned by file object
                yield f

            # Atomic rename
            shutil.move(str(temp_path), str(safe_path))
            temp_path = None

            logger.debug("ci_atomic_write_success", path=str(safe_path))

        except Exception as e:
            logger.error("ci_atomic_write_failed", path=str(safe_path), error=str(e))
            raise FileOperationError(f"Failed to write {safe_path}: {e}")
        finally:
            # Cleanup temp file if it still exists
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except (OSError, IOError, ValueError):  # CI operation best-effort
                    pass

    def _safe_read_file(self, path: Path) -> Optional[str]:
        """Read file with size limit and error handling."""
        try:
            if not path.exists():
                return None

            # Check file size
            size = path.stat().st_size
            if size > MAX_FILE_SIZE:
                logger.warning("ci_file_too_large", path=str(path), size=size)
                return None

            return path.read_text(encoding="utf-8")

        except PermissionError:
            logger.error("ci_file_permission_error", path=str(path))
            return None
        except Exception as e:
            logger.error("ci_file_read_error", path=str(path), error=str(e))
            return None

    # =========================================================================
    # Private: Provider Detection
    # =========================================================================

    def _detect_provider(self) -> Optional[CIProvider]:
        """Detect CI provider from existing files."""
        github_dir = self._project_root / ".github" / "workflows"
        gitlab_file = self._project_root / ".gitlab-ci.yml"

        if github_dir.exists() and github_dir.is_dir():
            return CIProvider.GITHUB
        elif gitlab_file.exists() and gitlab_file.is_file():
            return CIProvider.GITLAB
        return None

    def _get_workflows_for_provider(
        self, provider: CIProvider
    ) -> Tuple[WorkflowTemplate, ...]:
        """Get workflow templates for a provider."""
        return PROVIDER_WORKFLOWS.get(provider, ())

    def _detect_branch(self) -> str:
        """Detect default branch from git or config."""
        import subprocess

        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                cwd=self._project_root,
                timeout=5,  # Fail fast
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
                if branch and SAFE_BRANCH_PATTERN.match(branch):
                    return branch
        except subprocess.TimeoutExpired:
            logger.warning("ci_git_branch_timeout")
        except Exception as e:
            logger.debug("ci_git_branch_failed", error=str(e))

        return "main"

    # =========================================================================
    # Public: Status (Idempotent, Read-Only)
    # =========================================================================

    def get_status(self) -> CIStatus:
        """
        Get current CI configuration status.

        This operation is idempotent and read-only.

        Returns:
            CIStatus with all workflow statuses
        """
        status = CIStatus()

        # Detect provider
        status.provider = self._detect_provider()

        if not status.provider:
            logger.debug("ci_status_no_provider")
            return status

        status.is_configured = True
        status.template_version = CURRENT_TEMPLATE_VERSION

        # Check each workflow
        workflows = self._get_workflows_for_provider(status.provider)

        for wf in workflows:
            wf_path = self._project_root / wf.target_path
            wf_status = WorkflowStatus(
                exists=wf_path.exists(),
                path=wf.target_path,
            )

            if wf_status.exists:
                content = self._safe_read_file(wf_path)

                if content is None:
                    wf_status.error = "Failed to read file"
                else:
                    wf_status.version = self._extract_version(content)
                    wf_status.checksum = self._compute_checksum(content)

                    # Check if outdated
                    if wf_status.version:
                        wf_status.is_outdated = wf_status.version != CURRENT_TEMPLATE_VERSION
                    else:
                        wf_status.is_outdated = True

                    # Check for custom sections
                    custom_sections = self._extract_custom_sections(content)
                    if custom_sections:
                        wf_status.has_custom_sections = True
                        wf_status.custom_sections = [s[0] for s in custom_sections]

                    # Get last modified
                    try:
                        stat = wf_path.stat()
                        wf_status.last_modified = datetime.fromtimestamp(stat.st_mtime)
                    except (OSError, IOError, ValueError):  # CI operation best-effort
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

    # =========================================================================
    # Public: Init (Idempotent with force=False)
    # =========================================================================

    def init(
        self,
        provider: CIProvider,
        branch: str = "main",
        force: bool = False,
    ) -> Dict[str, Any]:
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

        result: Dict[str, Any] = {
            "success": True,
            "provider": provider.value,
            "created": [],
            "skipped": [],
            "errors": [],
        }

        # Validate branch (fail fast)
        try:
            branch = self._validate_branch(branch)
        except ValidationError as e:
            result["errors"].append(str(e))
            result["success"] = False
            return result

        workflows = self._get_workflows_for_provider(provider)

        if not workflows:
            result["errors"].append(f"No workflows defined for provider: {provider.value}")
            result["success"] = False
            return result

        template_vars = self._prepare_template_variables(branch)

        for wf in workflows:
            target_path = self._project_root / wf.target_path

            # Idempotent: Skip if exists and not forced
            if target_path.exists() and not force:
                result["skipped"].append(wf.target_path)
                logger.debug("ci_workflow_skipped", path=wf.target_path, reason="exists")
                continue

            try:
                # Load and process template
                template_content = self._load_template(wf.template_name)
                content = template_content.format(**template_vars)
                content = self._add_version_header(content)

                # Atomic write
                with self._atomic_write(target_path) as f:
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

    # =========================================================================
    # Public: Update (Preserves Customizations)
    # =========================================================================

    def update(
        self,
        preserve_custom: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
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

        result: Dict[str, Any] = {
            "success": True,
            "provider": status.provider.value,
            "updated": [],
            "unchanged": [],
            "errors": [],
            "dry_run": dry_run,
        }

        workflows = self._get_workflows_for_provider(status.provider)
        branch = self._detect_branch()
        template_vars = self._prepare_template_variables(branch)

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
                template_content = self._load_template(wf.template_name)
                new_content = template_content.format(**template_vars)

                # Preserve custom sections if requested
                if preserve_custom and wf_status.has_custom_sections:
                    existing_content = self._safe_read_file(target_path)
                    if existing_content:
                        custom_sections = self._extract_custom_sections(existing_content)
                        new_content = self._merge_custom_sections(new_content, custom_sections)

                new_content = self._add_version_header(new_content)

                if not dry_run:
                    with self._atomic_write(target_path) as f:
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

    # =========================================================================
    # Public: Sync (Lightweight Update)
    # =========================================================================

    def sync(self) -> Dict[str, Any]:
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

        result: Dict[str, Any] = {
            "success": True,
            "provider": status.provider.value,
            "synced": [],
            "errors": [],
        }

        workflows = self._get_workflows_for_provider(status.provider)
        llm_config = self._get_llm_config()
        provider_id = str(llm_config.get("provider", "ollama"))

        for wf in workflows:
            target_path = self._project_root / wf.target_path

            if not target_path.exists():
                continue

            try:
                content = self._safe_read_file(target_path)
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

                with self._atomic_write(target_path) as f:
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

    # =========================================================================
    # Public: Serialization
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
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
