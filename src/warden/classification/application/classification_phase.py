"""
Classification Phase - Frame selection and suppression rules.

This phase determines which validation frames should run based on:
- Project context (from PRE-ANALYSIS)
- Code quality metrics (from ANALYSIS)
- Historical patterns and learned suppressions
"""

from dataclasses import dataclass, field
from typing import Any

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile, ValidationFrame

logger = get_logger(__name__)


@dataclass
class ClassificationResult:
    """Result from classification phase."""

    selected_frames: list[str] = field(default_factory=list)
    suppression_rules: list[dict[str, Any]] = field(default_factory=list)
    frame_priorities: dict[str, int] = field(default_factory=dict)
    reasoning: str = ""
    learned_patterns: list[dict[str, Any]] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)  # AI Strategic Advice / Warnings
    confidence: float = 0.0
    duration: float = 0.0


class ClassificationPhase:
    """
    Classification phase implementation.

    Determines which frames to run and which issues to suppress.
    """

    def __init__(
        self,
        config: dict[str, Any] = None,
        context: dict[str, Any] = None,
        available_frames: list[ValidationFrame] = None,
        semantic_search_service: Any = None,
    ):
        """
        Initialize classification phase.

        Args:
            config: Phase configuration
            context: Context from previous phases
            available_frames: List of validation frames to choose from
            semantic_search_service: Optional semantic search service
        """
        self.config = config or {}
        self.context = context or {}
        self.available_frames = available_frames or []
        self.semantic_search_service = semantic_search_service

        logger.info("classification_phase_initialized", config_keys=list(self.config.keys()), has_context=bool(context))

    async def execute_async(self, code_files: list[CodeFile]) -> ClassificationResult:
        """
        Execute classification phase.

        Args:
            code_files: Files to classify

        Returns:
            ClassificationResult with selected frames and suppression rules
        """
        import time

        start_time = time.time()

        logger.info("classification_phase_started", file_count=len(code_files))

        result = ClassificationResult()

        try:
            # Get project context from PRE-ANALYSIS
            project_type = self.context.get("project_type", "unknown")
            framework = self.context.get("framework", "unknown")

            # Get quality metrics from ANALYSIS
            quality_score = self.context.get("quality_score", 0.0)
            hotspots = self.context.get("hotspots", [])

            # Default frame selection based on project type
            result.selected_frames = await self._select_frames_for_project_async(project_type, framework, quality_score)

            # Set frame priorities
            result.frame_priorities = self._calculate_frame_priorities(result.selected_frames, hotspots)

            # Generate suppression rules based on patterns
            result.suppression_rules = self._generate_suppression_rules(project_type, framework)

            # Build reasoning
            result.reasoning = (
                f"Selected {len(result.selected_frames)} frames for "
                f"{project_type}/{framework} project with quality score {quality_score:.2f}"
            )

            result.confidence = 0.75  # Default confidence
            result.duration = time.time() - start_time

            logger.info(
                "classification_phase_completed",
                selected_frames=result.selected_frames,
                suppression_count=len(result.suppression_rules),
                duration=result.duration,
            )

        except Exception as e:
            logger.error("classification_phase_failed", error=str(e))
            # Return default result on error
            result.selected_frames = ["security", "orphan", "chaos"]
            result.reasoning = f"Failed to classify, using defaults: {e!s}"

        return result

    async def _select_frames_for_project_async(
        self, project_type: str, framework: str, quality_score: float
    ) -> list[str]:
        """Select appropriate frames based on project context and semantic search."""

        frames = []

        # Always include security
        frames.append("security")

        # Add orphan detection for low quality code
        if quality_score < 7.0:
            frames.append("orphan")

        # Add chaos for backend/API projects
        if project_type in ["api", "backend", "service"]:
            frames.append("chaos")

        # Add architectural for large projects
        if project_type in ["application", "monorepo"]:
            frames.append("architecture")

        # Add stress for performance-critical projects
        if framework in ["fastapi", "django", "flask"]:
            frames.append("stress")

        # SEMANTIC SEARCH ENHANCEMENT
        if self.semantic_search_service and self.semantic_search_service.is_available():
            # Check for specific patterns that might trigger frames
            try:
                # 1. Check for distributed system patterns (Triggers chaos/resilience)
                resilience_matches = await self.semantic_search_service.search(
                    query="circuit breaker retry logic timeout handling distributed system", limit=3
                )
                if any(m.score > 0.7 for m in resilience_matches) and "resilience" not in frames:
                    frames.append("resilience")
                    logger.info("semantic_trigger_resilience", reason="Detected resilience patterns")

                # 2. Check for security sensitive patterns
                security_matches = await self.semantic_search_service.search(
                    query="sql injection authentication authorization encryption jwt", limit=3
                )
                if any(m.score > 0.8 for m in security_matches):
                    # Security is always there, but we might increase priority later
                    pass
            except Exception as e:
                logger.warning("semantic_frame_selection_failed", error=str(e))

        logger.debug("frames_selected", project_type=project_type, framework=framework, selected_frames=frames)

        return list(set(frames))  # Ensure uniqueness

    def _calculate_frame_priorities(self, frames: list[str], hotspots: list[dict[str, Any]]) -> dict[str, int]:
        """Calculate priority for each frame."""

        priorities = {}

        # Default priorities
        default_priorities = {
            "security": 1,
            "chaos": 2,
            "orphan": 3,
            "architecture": 4,
            "stress": 5,
            "property": 6,
            "fuzz": 7,
        }

        for frame in frames:
            priorities[frame] = default_priorities.get(frame, 99)

        # Adjust based on hotspots
        if len(hotspots) > 5:
            # Many hotspots, prioritize architectural
            if "architecture" in priorities:
                priorities["architecture"] = 1

        return priorities

    def _generate_suppression_rules(self, project_type: str, framework: str) -> list[dict[str, Any]]:
        """Generate suppression rules based on context."""

        rules = []

        # Suppress test-related issues in test files
        rules.append(
            {
                "pattern": "test_*.py",
                "suppress": ["orphan", "documentation"],
                "reason": "Test files have different standards",
            }
        )

        # Suppress framework-specific patterns
        if framework == "django":
            rules.append(
                {
                    "pattern": "migrations/*.py",
                    "suppress": ["orphan", "complexity"],
                    "reason": "Django migrations are auto-generated",
                }
            )

        if framework == "fastapi":
            rules.append(
                {
                    "pattern": "schemas/*.py",
                    "suppress": ["orphan"],
                    "reason": "Pydantic schemas may not be directly called",
                }
            )

        return rules
