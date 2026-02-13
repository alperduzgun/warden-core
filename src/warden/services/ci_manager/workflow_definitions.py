"""
Workflow Definitions Module

Workflow templates and data classes for CI providers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Final

from .exceptions import SecurityError, ValidationError
from .provider_detection import CIProvider
from .template_operations import ALLOWED_TEMPLATES, CURRENT_TEMPLATE_VERSION


class WorkflowType(Enum):
    """Types of CI workflows."""
    PR = "pr"
    NIGHTLY = "nightly"
    RELEASE = "release"
    MAIN = "main"


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
    version: str | None = None
    is_outdated: bool = False
    has_custom_sections: bool = False
    custom_sections: list[str] = field(default_factory=list)
    last_modified: datetime | None = None
    checksum: str | None = None
    error: str | None = None  # Capture any read errors


@dataclass
class CIStatus:
    """Overall CI configuration status."""
    provider: CIProvider | None = None
    workflows: dict[str, WorkflowStatus] = field(default_factory=dict)
    is_configured: bool = False
    needs_update: bool = False
    template_version: str = CURRENT_TEMPLATE_VERSION


# Workflow Definitions
GITHUB_WORKFLOWS: Final[tuple[WorkflowTemplate, ...]] = (
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

GITLAB_WORKFLOWS: Final[tuple[WorkflowTemplate, ...]] = (
    WorkflowTemplate(
        provider=CIProvider.GITLAB,
        workflow_type=WorkflowType.MAIN,
        template_name="gitlab.yml",
        target_path=".gitlab-ci.yml",
        description="GitLab CI pipeline with all stages",
    ),
)

# Provider to workflows mapping
PROVIDER_WORKFLOWS: Final[dict[CIProvider, tuple[WorkflowTemplate, ...]]] = {
    CIProvider.GITHUB: GITHUB_WORKFLOWS,
    CIProvider.GITLAB: GITLAB_WORKFLOWS,
}


def get_workflows_for_provider(provider: CIProvider) -> tuple[WorkflowTemplate, ...]:
    """Get workflow templates for a provider."""
    return PROVIDER_WORKFLOWS.get(provider, ())
