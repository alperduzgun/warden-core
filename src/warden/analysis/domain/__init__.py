"""
Analysis Domain Models.

Core domain models for project analysis and intelligence.
"""

from warden.analysis.domain.file_context import (
    FileContext,
    PreAnalysisResult,
)
from warden.analysis.domain.intelligence import (
    FileException,
    ModuleInfo,
    ProjectIntelligence,
    RiskLevel,
    SecurityPosture,
)
from warden.analysis.domain.project_context import (
    Architecture,
    BuildTool,
    Framework,
    ProjectContext,
    ProjectConventions,
    ProjectStatistics,
    ProjectType,
    TestFramework,
)

__all__ = [
    # Project Context
    "ProjectContext",
    "ProjectType",
    "Framework",
    "Architecture",
    "TestFramework",
    "BuildTool",
    "ProjectStatistics",
    "ProjectConventions",
    # Intelligence
    "RiskLevel",
    "SecurityPosture",
    "ModuleInfo",
    "FileException",
    "ProjectIntelligence",
    # File Context
    "FileContext",
    "PreAnalysisResult",
]
