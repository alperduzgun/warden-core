"""
Cleaning Phase with LLM Enhancement.

Generates code quality improvements and refactoring suggestions.
Uses LLM to provide intelligent code cleaning recommendations.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from warden.validation.domain.frame import CodeFile
from warden.shared.infrastructure.logging import get_logger
from warden.cleaning.application.pattern_analyzer import PatternAnalyzer
from warden.cleaning.application.llm_suggestion_generator import LLMSuggestionGenerator

# Try to import LLMService, use None if not available
try:
    from warden.shared.services import LLMService
except ImportError:
    LLMService = None

logger = get_logger(__name__)


@dataclass
class CleaningResult:
    """Result from cleaning phase."""

    cleaning_suggestions: List[Dict[str, Any]]
    refactorings: List[Dict[str, Any]]
    quality_score_after: float
    code_improvements: Dict[str, Any]
    confidence: float = 0.0


class CleaningPhase:
    """
    Phase 5: CLEANING - Generate code quality improvements.

    Responsibilities:
    - Analyze code for quality issues
    - Suggest refactorings
    - Remove dead code
    - Improve naming and structure
    - Optimize performance
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        llm_service: Optional[LLMService] = None,
    ):
        """
        Initialize cleaning phase.

        Args:
            config: Phase configuration
            context: Pipeline context from previous phases
            llm_service: Optional LLM service for enhanced suggestions
        """
        self.config = config or {}
        self.context = context or {}
        self.llm_service = llm_service
        self.use_llm = self.config.get("use_llm", True) and llm_service is not None

        # Initialize analyzers
        self.pattern_analyzer = PatternAnalyzer()

        if self.use_llm:
            self.llm_generator = LLMSuggestionGenerator(
                llm_service=llm_service,
                context=context,
            )
        else:
            self.llm_generator = None

        logger.info(
            "cleaning_phase_initialized",
            use_llm=self.use_llm,
            context_keys=list(context.keys()) if context else [],
        )

    async def execute_async(
        self,
        code_files: List[CodeFile],
    ) -> CleaningResult:
        """
        Execute cleaning phase on code files.

        Args:
            code_files: List of code files to analyze

        Returns:
            CleaningResult with improvement suggestions
        """
        logger.info(
            "cleaning_phase_started",
            file_count=len(code_files),
            use_llm=self.use_llm,
        )

        cleaning_suggestions = []
        refactorings = []

        # Analyze each file for improvements
        for code_file in code_files:
            # Skip non-production files based on context
            file_context = self.context.get("file_contexts", {}).get(code_file.path)
            if file_context and file_context.get("context") in ["TEST", "EXAMPLE", "DOCUMENTATION"]:
                logger.info(
                    "skipping_non_production_file",
                    file=code_file.path,
                    context=file_context.get("context"),
                )
                continue

            # Generate cleaning suggestions
            if self.use_llm:
                suggestions = await self._generate_llm_suggestions_async(code_file)
            else:
                suggestions = await self._generate_rule_based_suggestions_async(code_file)

            cleaning_suggestions.extend(suggestions.get("cleanings", []))
            refactorings.extend(suggestions.get("refactorings", []))

        # Calculate quality improvements
        quality_score_before = self.context.get("quality_score_before", 0.0)
        quality_score_after = self._calculate_improved_score(
            quality_score_before,
            cleaning_suggestions,
            refactorings,
        )

        code_improvements = self._summarize_improvements(
            cleaning_suggestions,
            refactorings,
        )

        result = CleaningResult(
            cleaning_suggestions=cleaning_suggestions,
            refactorings=refactorings,
            quality_score_after=quality_score_after,
            code_improvements=code_improvements,
            confidence=0.85 if self.use_llm else 0.7,
        )

        logger.info(
            "cleaning_phase_completed",
            suggestions_count=len(cleaning_suggestions),
            refactorings_count=len(refactorings),
            quality_improvement=quality_score_after - quality_score_before,
        )

        return result

    async def _generate_llm_suggestions_async(
        self,
        code_file: CodeFile,
    ) -> Dict[str, Any]:
        """
        Generate cleaning suggestions using LLM.

        Args:
            code_file: Code file to analyze

        Returns:
            Dictionary with cleanings and refactorings
        """
        if not self.llm_generator:
            return await self._generate_rule_based_suggestions_async(code_file)

        try:
            # Delegate to LLM generator
            suggestions = await self.llm_generator.generate_suggestions_async(code_file)
            return suggestions

        except Exception as e:
            logger.error(
                "llm_suggestion_generation_failed",
                file=code_file.path,
                error=str(e),
            )
            # Fall back to rule-based suggestions
            return await self._generate_rule_based_suggestions_async(code_file)

    async def _generate_rule_based_suggestions_async(
        self,
        code_file: CodeFile,
    ) -> Dict[str, Any]:
        """
        Generate cleaning suggestions using rules.

        Args:
            code_file: Code file to analyze

        Returns:
            Dictionary with cleanings and refactorings
        """
        cleanings = []
        refactorings = []

        # Analyze code patterns using pattern analyzer
        analysis = self.pattern_analyzer.analyze_code_patterns(code_file)

        # Generate suggestions based on patterns
        if analysis.get("duplicate_code"):
            cleanings.append(
                self.pattern_analyzer.create_duplication_suggestion(analysis["duplicate_code"])
            )

        if analysis.get("complex_functions"):
            refactorings.append(
                self.pattern_analyzer.create_complexity_suggestion(analysis["complex_functions"])
            )

        if analysis.get("naming_issues"):
            cleanings.append(
                self.pattern_analyzer.create_naming_suggestion(analysis["naming_issues"])
            )

        if analysis.get("dead_code"):
            cleanings.append(
                self.pattern_analyzer.create_dead_code_suggestion(analysis["dead_code"])
            )

        if analysis.get("import_issues"):
            cleanings.append(
                self.pattern_analyzer.create_import_suggestion(analysis["import_issues"])
            )

        return {
            "cleanings": cleanings,
            "refactorings": refactorings,
        }


    def _calculate_improved_score(
        self,
        quality_score_before: float,
        cleaning_suggestions: List,
        refactorings: List,
    ) -> float:
        """
        Calculate improved quality score.

        Args:
            quality_score_before: Original quality score
            cleaning_suggestions: List of cleaning suggestions
            refactorings: List of refactoring suggestions

        Returns:
            Estimated quality score after improvements
        """
        # Estimate improvement based on suggestions
        improvement = 0.0

        # Each cleaning suggestion adds small improvement
        for cleaning in cleaning_suggestions:
            impact = cleaning.get("impact", "medium")
            if impact == "high":
                improvement += 0.3
            elif impact == "medium":
                improvement += 0.2
            else:
                improvement += 0.1

        # Each refactoring adds larger improvement
        for refactoring in refactorings:
            impact = refactoring.get("impact", "high")
            if impact == "high":
                improvement += 0.5
            elif impact == "medium":
                improvement += 0.3
            else:
                improvement += 0.2

        # Cap improvement at realistic level
        improvement = min(improvement, 3.0)

        # Calculate new score
        quality_score_after = min(quality_score_before + improvement, 10.0)

        return round(quality_score_after, 1)

    def _summarize_improvements(
        self,
        cleaning_suggestions: List,
        refactorings: List,
    ) -> Dict[str, Any]:
        """
        Summarize all improvements.

        Args:
            cleaning_suggestions: List of cleaning suggestions
            refactorings: List of refactoring suggestions

        Returns:
            Summary dictionary
        """
        # Count by type
        type_counts = {}
        for suggestion in cleaning_suggestions + refactorings:
            sug_type = suggestion.get("type", "other")
            type_counts[sug_type] = type_counts.get(sug_type, 0) + 1

        # Count by impact
        impact_counts = {"high": 0, "medium": 0, "low": 0}
        for suggestion in cleaning_suggestions + refactorings:
            impact = suggestion.get("impact", "medium")
            impact_counts[impact] = impact_counts.get(impact, 0) + 1

        # Count by effort
        effort_counts = {"high": 0, "medium": 0, "low": 0}
        for suggestion in cleaning_suggestions + refactorings:
            effort = suggestion.get("effort", "medium")
            effort_counts[effort] = effort_counts.get(effort, 0) + 1

        return {
            "total_suggestions": len(cleaning_suggestions) + len(refactorings),
            "cleanings": len(cleaning_suggestions),
            "refactorings": len(refactorings),
            "by_type": type_counts,
            "by_impact": impact_counts,
            "by_effort": effort_counts,
            "quick_wins": [
                s for s in cleaning_suggestions + refactorings
                if s.get("impact") in ["high", "medium"] and s.get("effort") == "low"
            ][:5],  # Top 5 quick wins
        }

    def _format_findings(
        self,
        findings: List[Dict[str, Any]],
    ) -> str:
        """Format findings for prompt."""
        if not findings:
            return "No security issues in this file"

        formatted = []
        for finding in findings:
            formatted.append(
                f"- {finding.get('type', 'issue')}: "
                f"{finding.get('message', 'Security issue')} "
                f"(line {finding.get('line_number', 'unknown')})"
            )

        return "\n".join(formatted)