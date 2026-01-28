"""
Analysis Domain Models.

Core domain models for project analysis and intelligence.
"""

from warden.analysis.domain.project_context import (
    ProjectContext,
    ProjectType,
    Framework,
    Architecture,
    TestFramework,
    BuildTool,
    ProjectStatistics,
    ProjectConventions,
)

from warden.analysis.domain.intelligence import (
    RiskLevel,
    SecurityPosture,
    ModuleInfo,
    FileException,
    ProjectIntelligence,
)

from warden.analysis.domain.file_context import (
    FileContext,
    PreAnalysisResult,
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
