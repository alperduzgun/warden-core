"""
Result Analysis Adapter

MCP adapter for pipeline result analysis and trends.
Maps to gRPC ResultAnalysisMixin functionality.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory


class AnalysisAdapter(BaseWardenAdapter):
    """
    Adapter for result analysis tools.

    Tools:
        - warden_analyze_results: Analyze for trends
        - warden_get_trends: Get trend data
        - warden_get_frame_stats: Per-frame statistics
        - warden_get_severity_stats: Severity distribution
        - warden_get_quality_score: Quality score
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_analyze_results",
        "warden_get_trends",
        "warden_get_frame_stats",
        "warden_get_severity_stats",
        "warden_get_quality_score",
    })
    TOOL_CATEGORY = ToolCategory.ANALYSIS

    def __init__(self, project_root: Path, bridge: Any = None) -> None:
        """Initialize analysis adapter with history tracking."""
        super().__init__(project_root, bridge)
        # Historical data for trends
        self._history: List[Dict[str, Any]] = []
        self._last_result: Dict[str, Any] = {}

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """Get analysis tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_analyze_results",
                description="Analyze pipeline results for trends and quality changes",
                properties={
                    "run_id": {
                        "type": "string",
                        "description": "Pipeline run ID to analyze",
                    },
                },
            ),
            self._create_tool_definition(
                name="warden_get_trends",
                description="Get historical trend data over time",
                properties={
                    "limit": {
                        "type": "integer",
                        "description": "Number of historical points",
                        "default": 10,
                    },
                },
            ),
            self._create_tool_definition(
                name="warden_get_frame_stats",
                description="Get statistics per validation frame",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_get_severity_stats",
                description="Get issue distribution by severity",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_get_quality_score",
                description="Get overall code quality score with breakdown",
                properties={},
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """Execute analysis tool."""
        handlers = {
            "warden_analyze_results": self._analyze_results,
            "warden_get_trends": self._get_trends,
            "warden_get_frame_stats": self._get_frame_stats,
            "warden_get_severity_stats": self._get_severity_stats,
            "warden_get_quality_score": self._get_quality_score,
        }

        handler = handlers.get(tool_name)
        if handler:
            return await handler(arguments)
        return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _analyze_results(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Analyze pipeline results."""
        run_id = arguments.get("run_id")

        # Calculate trend based on history
        if len(self._history) >= 2:
            prev = self._history[-2]
            curr = self._history[-1] if self._history else self._last_result

            prev_issues = prev.get("total_issues", 0)
            curr_issues = curr.get("total_issues", 0)

            if curr_issues < prev_issues:
                trend = "IMPROVING"
            elif curr_issues > prev_issues:
                trend = "DEGRADING"
            else:
                trend = "STABLE"
        else:
            trend = "STABLE"

        # Calculate quality score
        quality_score = self._calculate_quality_score(self._last_result)

        return MCPToolResult.json_result({
            "success": True,
            "run_id": run_id,
            "trend": trend,
            "quality_score": quality_score,
            "new_issues": self._last_result.get("new_issues", 0),
            "resolved_issues": self._last_result.get("resolved_issues", 0),
            "persistent_issues": self._last_result.get("persistent_issues", 0),
            "analysis_timestamp": datetime.utcnow().isoformat(),
        })

    async def _get_trends(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get trend data over time."""
        limit = arguments.get("limit", 10)

        points = self._history[-limit:] if self._history else []

        # Calculate overall trend
        if len(points) >= 2:
            first_score = points[0].get("quality_score", 50)
            last_score = points[-1].get("quality_score", 50)

            if last_score > first_score + 5:
                overall_trend = "IMPROVING"
            elif last_score < first_score - 5:
                overall_trend = "DEGRADING"
            else:
                overall_trend = "STABLE"
        else:
            overall_trend = "STABLE"

        return MCPToolResult.json_result({
            "points": points,
            "overall_trend": overall_trend,
            "total_points": len(points),
        })

    async def _get_frame_stats(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get per-frame statistics."""
        stats: Dict[str, Dict[str, Any]] = {}

        # Get from last result
        frame_results = self._last_result.get("frame_results", [])
        for fr in frame_results:
            frame_id = fr.get("frame_id", "unknown")
            stats[frame_id] = {
                "frame_id": frame_id,
                "frame_name": fr.get("frame_name", frame_id),
                "total_findings": fr.get("issues_found", 0),
                "critical": fr.get("critical", 0),
                "high": fr.get("high", 0),
                "medium": fr.get("medium", 0),
                "low": fr.get("low", 0),
            }

        return MCPToolResult.json_result({"stats": stats})

    async def _get_severity_stats(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get severity distribution."""
        critical = self._last_result.get("critical_findings", 0)
        high = self._last_result.get("high_findings", 0)
        medium = self._last_result.get("medium_findings", 0)
        low = self._last_result.get("low_findings", 0)
        info = self._last_result.get("info_findings", 0)

        # Calculate weighted score
        weighted = critical * 10 + high * 5 + medium * 2 + low * 1

        return MCPToolResult.json_result({
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": low,
            "info": info,
            "weighted_score": weighted,
        })

    async def _get_quality_score(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get overall quality score."""
        score = self._calculate_quality_score(self._last_result)

        # Calculate grade
        if score >= 90:
            grade = "A"
        elif score >= 80:
            grade = "B"
        elif score >= 70:
            grade = "C"
        elif score >= 60:
            grade = "D"
        else:
            grade = "F"

        # Breakdown by category
        breakdown = {
            "security": max(0, 100 - self._last_result.get("critical_findings", 0) * 20),
            "code_quality": max(0, 100 - self._last_result.get("medium_findings", 0) * 5),
            "maintainability": max(0, 100 - self._last_result.get("low_findings", 0) * 2),
        }

        return MCPToolResult.json_result({
            "score": score,
            "grade": grade,
            "breakdown": breakdown,
        })

    def _calculate_quality_score(self, result: Dict[str, Any]) -> float:
        """Calculate quality score from result."""
        critical = result.get("critical_findings", 0)
        high = result.get("high_findings", 0)
        medium = result.get("medium_findings", 0)
        low = result.get("low_findings", 0)

        weighted = critical * 10 + high * 5 + medium * 2 + low * 1
        score = max(0, 100 - weighted)

        return round(score, 1)

    def record_result(self, result: Dict[str, Any]) -> None:
        """Record a pipeline result for trend tracking."""
        self._last_result = result
        self._history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "total_issues": result.get("total_findings", 0),
            "quality_score": self._calculate_quality_score(result),
            **result,
        })
