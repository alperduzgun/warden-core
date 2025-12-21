"""
CI Integration module.

Provides templates and configuration generators for various CI/CD platforms.
"""

from warden.infrastructure.ci.github_actions import GitHubActionsTemplate
from warden.infrastructure.ci.gitlab_ci import GitLabCITemplate
from warden.infrastructure.ci.azure_pipelines import AzurePipelinesTemplate

__all__ = [
    "GitHubActionsTemplate",
    "GitLabCITemplate",
    "AzurePipelinesTemplate",
]
