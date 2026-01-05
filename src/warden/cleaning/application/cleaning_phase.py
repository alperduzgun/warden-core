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
from warden.cleaning.domain.models import Cleaning
from warden.shared.infrastructure.ignore_matcher import IgnoreMatcher
from pathlib import Path

# Try to import LLMService, use None if not available
try:
    from warden.shared.services import LLMService
except ImportError:
    LLMService = None

logger = get_logger(__name__)


@dataclass
class CleaningPhaseResult:
    """Result from cleaning phase execution."""

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
        semantic_search_service: Optional[Any] = None,
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
        self.semantic_search_service = semantic_search_service
        self.use_llm = self.config.get("use_llm", True) and llm_service is not None
        
        # Initialize IgnoreMatcher
        project_root = getattr(self.context, 'project_root', None) or Path.cwd()
        if isinstance(self.context, dict):
            project_root = self.context.get('project_root') or project_root
            use_gitignore = self.context.get('use_gitignore', True)
        else:
            use_gitignore = getattr(self.context, 'use_gitignore', True)
        
        self.ignore_matcher = IgnoreMatcher(Path(project_root), use_gitignore=use_gitignore)

        # Initialize analyzers
        self.pattern_analyzer = PatternAnalyzer()

        if self.use_llm:
            self.llm_generator = LLMSuggestionGenerator(
                llm_service=llm_service,
                context=context,
                semantic_search_service=semantic_search_service,
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
    ) -> CleaningPhaseResult:
        """
        Execute cleaning phase.
        """
        logger.info(
            "cleaning_phase_started",
            file_count=len(code_files),
            use_llm=self.use_llm,
        )

        # Filter files based on ignore matcher
        original_count = len(code_files)
        code_files = [
            cf for cf in code_files 
            if not self.ignore_matcher.should_ignore_for_frame(Path(cf.path), "cleaning")
        ]
        
        if len(code_files) < original_count:
             logger.info(
                "cleaning_phase_files_ignored",
                ignored=original_count - len(code_files),
                remaining=len(code_files)
            )

        from warden.cleaning.application.orchestrator import CleaningOrchestrator
        orchestrator = CleaningOrchestrator()

        all_cleanings = []
        all_refactorings = []
        all_suggestions = []

        # Analyze each file for improvements
        for code_file in code_files:
            # Skip non-production files based on context
            file_context = self.context.get("file_contexts", {}).get(code_file.path)
            if file_context:
                if hasattr(file_context, 'context'):
                    context_type = file_context.context.value if hasattr(file_context.context, 'value') else str(file_context.context)
                elif isinstance(file_context, dict):
                    context_type = file_context.get("context", "PRODUCTION")
                else:
                    context_type = "PRODUCTION"

                if context_type in ["TEST", "EXAMPLE", "DOCUMENTATION"]:
                    continue

            # Run specialized cleaning orchestrator
            res = await orchestrator.analyze_async(code_file)
            all_suggestions.extend(res.suggestions)
            
            # Map suggestions to cleanings for Panel
            for sug in res.suggestions:
                all_cleanings.append(Cleaning(
                    id=f"clean-{len(all_cleanings)}",
                    title=sug.issue.issue_type.value.replace("_", " ").title(),
                    detail=sug.suggestion
                ))

            # Legacy rule-based/llm suggestions
            if self.use_llm:
                suggestions = await self._generate_llm_suggestions_async(code_file)
            else:
                suggestions = await self._generate_rule_based_suggestions_async(code_file)

            for sug in suggestions.get("cleanings", []):
                all_cleanings.append(Cleaning(
                    id=f"leg-clean-{len(all_cleanings)}",
                    title=sug.get("title", "Cleaning Suggestion"),
                    detail=sug.get("detail", "")
                ))
            
            for ref in suggestions.get("refactorings", []):
                all_refactorings.append(Cleaning(
                    id=f"ref-{len(all_refactorings)}",
                    title=ref.get("title", "Refactoring"),
                    detail=ref.get("detail", "")
                ))

        # Calculate results
        quality_score_before = self.context.get("quality_score_before", 0.0)
        quality_score_after = self._calculate_improved_score(
            quality_score_before,
            all_cleanings,
            all_refactorings,
        )

        code_improvements = self._summarize_improvements(
            all_cleanings,
            all_refactorings,
        )

        result = CleaningPhaseResult(
            cleaning_suggestions=[c.to_json() if hasattr(c, 'to_json') else c for c in all_cleanings],
            refactorings=[r.to_json() if hasattr(r, 'to_json') else r for r in all_refactorings],
            quality_score_after=quality_score_after,
            code_improvements=code_improvements,
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

    def _safe_get(self, obj: Any, key: str, default: Any = None) -> Any:
        """Safely get attribute from dict or object."""
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

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
            impact = self._safe_get(cleaning, "impact", "medium")
            if impact == "high":
                improvement += 0.3
            elif impact == "medium":
                improvement += 0.2
            else:
                improvement += 0.1

        # Each refactoring adds larger improvement
        for refactoring in refactorings:
            impact = self._safe_get(refactoring, "impact", "high")
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
            sug_type = self._safe_get(suggestion, "type", "other")
            type_counts[sug_type] = type_counts.get(sug_type, 0) + 1

        # Count by impact
        impact_counts = {"high": 0, "medium": 0, "low": 0}
        for suggestion in cleaning_suggestions + refactorings:
            impact = self._safe_get(suggestion, "impact", "medium")
            impact_counts[impact] = impact_counts.get(impact, 0) + 1

        # Count by effort
        effort_counts = {"high": 0, "medium": 0, "low": 0}
        for suggestion in cleaning_suggestions + refactorings:
            effort = self._safe_get(suggestion, "effort", "medium")
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
                if self._safe_get(s, "impact") in ["high", "medium"] and self._safe_get(s, "effort") == "low"
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