"""
CI Manager Service

Central service for managing CI/CD workflow files.
Provides init, update, sync, and status operations for CI workflows.
"""

import re
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
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


class CIProvider(Enum):
    """Supported CI providers."""
    GITHUB = "github"
    GITLAB = "gitlab"


class WorkflowType(Enum):
    """Types of CI workflows."""
    PR = "pr"
    NIGHTLY = "nightly"
    RELEASE = "release"
    MAIN = "main"


@dataclass
class WorkflowTemplate:
    """Represents a CI workflow template."""
    provider: CIProvider
    workflow_type: WorkflowType
    template_name: str
    target_path: str
    version: str = "1.0.0"
    description: str = ""


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


@dataclass
class CIStatus:
    """Overall CI configuration status."""
    provider: Optional[CIProvider] = None
    workflows: Dict[str, WorkflowStatus] = field(default_factory=dict)
    is_configured: bool = False
    needs_update: bool = False
    template_version: str = "1.0.0"


# Workflow definitions
GITHUB_WORKFLOWS = [
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
]

GITLAB_WORKFLOWS = [
    WorkflowTemplate(
        provider=CIProvider.GITLAB,
        workflow_type=WorkflowType.MAIN,
        template_name="gitlab.yml",
        target_path=".gitlab-ci.yml",
        description="GitLab CI pipeline with all stages",
    ),
]

CURRENT_TEMPLATE_VERSION = "1.0.0"

# Custom section markers
CUSTOM_SECTION_START = "# WARDEN-CUSTOM-START"
CUSTOM_SECTION_END = "# WARDEN-CUSTOM-END"
VERSION_HEADER_PATTERN = r"^# Warden CI v(\d+\.\d+\.\d+)"


class CIManager:
    """
    Manages CI/CD workflow files.

    Features:
        - Initialize CI workflows from templates
        - Update workflows while preserving customizations
        - Sync workflows with current configuration
        - Check workflow status and version
    """

    def __init__(
        self,
        project_root: Path,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize CI Manager.

        Args:
            project_root: Project root directory
            config: Optional Warden configuration dict
        """
        self.project_root = project_root
        self.config = config or {}
        self._load_config()

    def _load_config(self) -> None:
        """Load Warden configuration if not provided."""
        if self.config:
            return

        config_path = self.project_root / ".warden" / "config.yaml"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    self.config = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning("ci_manager_config_load_failed", error=str(e))

    def _get_llm_config(self) -> Dict[str, Any]:
        """Get LLM configuration from config."""
        return self.config.get("llm", {"provider": "ollama"})

    def _detect_provider(self) -> Optional[CIProvider]:
        """Detect CI provider from existing files."""
        github_dir = self.project_root / ".github" / "workflows"
        gitlab_file = self.project_root / ".gitlab-ci.yml"

        if github_dir.exists():
            return CIProvider.GITHUB
        elif gitlab_file.exists():
            return CIProvider.GITLAB
        return None

    def _get_workflows_for_provider(
        self, provider: CIProvider
    ) -> List[WorkflowTemplate]:
        """Get workflow templates for a provider."""
        if provider == CIProvider.GITHUB:
            return GITHUB_WORKFLOWS
        elif provider == CIProvider.GITLAB:
            return GITLAB_WORKFLOWS
        return []

    def _load_template(self, template_name: str) -> Optional[str]:
        """Load template content from package resources."""
        try:
            content = importlib.resources.read_text(
                "warden.templates.workflows",
                template_name
            )
            return content
        except Exception as e:
            logger.error("ci_template_load_failed", template=template_name, error=str(e))
            return None

    def _add_version_header(self, content: str) -> str:
        """Add version header to workflow content."""
        version_header = f"# Warden CI v{CURRENT_TEMPLATE_VERSION}\n"
        version_header += f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        version_header += "# Do not edit sections marked WARDEN-MANAGED\n\n"
        return version_header + content

    def _extract_version(self, content: str) -> Optional[str]:
        """Extract version from workflow file."""
        match = re.search(VERSION_HEADER_PATTERN, content, re.MULTILINE)
        if match:
            return match.group(1)
        return None

    def _extract_custom_sections(self, content: str) -> List[Tuple[str, str]]:
        """
        Extract custom sections from workflow file.

        Returns:
            List of (section_name, section_content) tuples
        """
        custom_sections = []
        pattern = rf"{CUSTOM_SECTION_START}\s*(\w+)?\n(.*?){CUSTOM_SECTION_END}"

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
        """Compute checksum of content (excluding version header)."""
        # Remove version header for checksum
        lines = content.split("\n")
        content_lines = []
        for line in lines:
            if not line.startswith("# Warden CI v") and not line.startswith("# Generated:"):
                content_lines.append(line)
        return hashlib.md5("\n".join(content_lines).encode()).hexdigest()[:8]

    def _prepare_template_variables(self, branch: str = "main") -> Dict[str, str]:
        """Prepare template variables for substitution."""
        llm_config = self._get_llm_config()
        provider_id = llm_config.get("provider", "ollama")

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
            key_var_map = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "groq": "GROQ_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
                "azure": "AZURE_OPENAI_API_KEY",
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

    def get_status(self) -> CIStatus:
        """
        Get current CI configuration status.

        Returns:
            CIStatus with all workflow statuses
        """
        status = CIStatus()

        # Detect provider
        status.provider = self._detect_provider()

        if not status.provider:
            return status

        status.is_configured = True
        status.template_version = CURRENT_TEMPLATE_VERSION

        # Check each workflow
        workflows = self._get_workflows_for_provider(status.provider)

        for wf in workflows:
            wf_path = self.project_root / wf.target_path
            wf_status = WorkflowStatus(
                exists=wf_path.exists(),
                path=wf.target_path,
            )

            if wf_status.exists:
                content = wf_path.read_text()
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
                stat = wf_path.stat()
                wf_status.last_modified = datetime.fromtimestamp(stat.st_mtime)

                if wf_status.is_outdated:
                    status.needs_update = True

            status.workflows[wf.workflow_type.value] = wf_status

        return status

    def init(
        self,
        provider: CIProvider,
        branch: str = "main",
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Initialize CI workflows for a provider.

        Args:
            provider: CI provider to use
            branch: Default branch name
            force: Overwrite existing files

        Returns:
            Dict with created file paths and status
        """
        result = {
            "success": True,
            "provider": provider.value,
            "created": [],
            "skipped": [],
            "errors": [],
        }

        workflows = self._get_workflows_for_provider(provider)
        template_vars = self._prepare_template_variables(branch)

        for wf in workflows:
            target_path = self.project_root / wf.target_path

            # Skip if exists and not forced
            if target_path.exists() and not force:
                result["skipped"].append(wf.target_path)
                continue

            # Load template
            template_content = self._load_template(wf.template_name)
            if not template_content:
                result["errors"].append(f"Template not found: {wf.template_name}")
                continue

            try:
                # Apply template variables
                content = template_content.format(**template_vars)

                # Add version header
                content = self._add_version_header(content)

                # Create directory if needed
                target_path.parent.mkdir(parents=True, exist_ok=True)

                # Write file
                with open(target_path, "w") as f:
                    f.write(content)

                result["created"].append(wf.target_path)
                logger.info("ci_workflow_created", path=wf.target_path)

            except Exception as e:
                result["errors"].append(f"Failed to create {wf.target_path}: {e}")
                logger.error("ci_workflow_create_failed", path=wf.target_path, error=str(e))

        result["success"] = len(result["errors"]) == 0
        return result

    def update(
        self,
        preserve_custom: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Update CI workflows from templates.

        Args:
            preserve_custom: Preserve custom sections marked with WARDEN-CUSTOM
            dry_run: Show what would be updated without making changes

        Returns:
            Dict with update results
        """
        status = self.get_status()

        if not status.provider:
            return {
                "success": False,
                "error": "No CI provider detected. Run 'warden ci init' first.",
            }

        result = {
            "success": True,
            "provider": status.provider.value,
            "updated": [],
            "unchanged": [],
            "errors": [],
            "dry_run": dry_run,
        }

        workflows = self._get_workflows_for_provider(status.provider)

        # Detect branch from existing config or git
        branch = self._detect_branch()
        template_vars = self._prepare_template_variables(branch)

        for wf in workflows:
            target_path = self.project_root / wf.target_path
            wf_status = status.workflows.get(wf.workflow_type.value)

            if not wf_status or not wf_status.exists:
                continue

            if not wf_status.is_outdated:
                result["unchanged"].append(wf.target_path)
                continue

            # Load template
            template_content = self._load_template(wf.template_name)
            if not template_content:
                result["errors"].append(f"Template not found: {wf.template_name}")
                continue

            try:
                # Apply template variables
                new_content = template_content.format(**template_vars)

                # Preserve custom sections if requested
                if preserve_custom and wf_status.has_custom_sections:
                    existing_content = target_path.read_text()
                    custom_sections = self._extract_custom_sections(existing_content)
                    new_content = self._merge_custom_sections(new_content, custom_sections)

                # Add version header
                new_content = self._add_version_header(new_content)

                if not dry_run:
                    with open(target_path, "w") as f:
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
                    dry_run=dry_run,
                )

            except Exception as e:
                result["errors"].append(f"Failed to update {wf.target_path}: {e}")
                logger.error("ci_workflow_update_failed", path=wf.target_path, error=str(e))

        result["success"] = len(result["errors"]) == 0
        return result

    def sync(self) -> Dict[str, Any]:
        """
        Sync CI workflows with current Warden configuration.

        Updates LLM provider settings and environment variables
        without changing workflow structure.

        Returns:
            Dict with sync results
        """
        status = self.get_status()

        if not status.provider:
            return {
                "success": False,
                "error": "No CI provider detected. Run 'warden ci init' first.",
            }

        result = {
            "success": True,
            "provider": status.provider.value,
            "synced": [],
            "errors": [],
        }

        workflows = self._get_workflows_for_provider(status.provider)

        # Get current LLM config
        llm_config = self._get_llm_config()
        provider_id = llm_config.get("provider", "ollama")

        for wf in workflows:
            target_path = self.project_root / wf.target_path

            if not target_path.exists():
                continue

            try:
                content = target_path.read_text()

                # Update CI_LLM_PROVIDER
                content = re.sub(
                    r'CI_LLM_PROVIDER:\s*\w+',
                    f'CI_LLM_PROVIDER: {provider_id}',
                    content
                )

                # Update version timestamp
                content = re.sub(
                    r'# Generated:.*',
                    f'# Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} (synced)',
                    content
                )

                with open(target_path, "w") as f:
                    f.write(content)

                result["synced"].append(wf.target_path)

            except Exception as e:
                result["errors"].append(f"Failed to sync {wf.target_path}: {e}")

        result["success"] = len(result["errors"]) == 0
        return result

    def _detect_branch(self) -> str:
        """Detect default branch from git or config."""
        import subprocess

        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
                if branch:
                    return branch
        except Exception:
            pass

        return "main"

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
                }
                for name, wf in status.workflows.items()
            },
        }
