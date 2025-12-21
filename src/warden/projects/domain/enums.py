"""
Project domain enums.

Panel Source: /warden-panel/src/lib/types/project.ts

TypeScript:
    export type ProjectStatus = 'success' | 'running' | 'failed' | 'idle';
    export type QualityTrend = 'improving' | 'stable' | 'degrading';
"""

from enum import Enum


class ProjectStatus(str, Enum):
    """
    Project run status.

    Matches Panel TypeScript ProjectStatus type.
    """

    SUCCESS = "success"
    RUNNING = "running"
    FAILED = "failed"
    IDLE = "idle"


class QualityTrend(str, Enum):
    """
    Quality score trend indicator.

    Matches Panel TypeScript QualityTrend type.
    """

    IMPROVING = "improving"
    STABLE = "stable"
    DEGRADING = "degrading"


class GitProviderType(str, Enum):
    """
    Git provider type.

    Identifies the Git hosting platform for a project.
    """

    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    LOCAL = "local"  # For local projects without remote
