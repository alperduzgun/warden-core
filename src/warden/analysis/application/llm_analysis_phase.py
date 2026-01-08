"""
LLM-Enhanced Analysis Phase.

Context-aware quality scoring with AI assistance.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from warden.analysis.application.llm_phase_base import (
    LLMPhaseBase,
    LLMPhaseConfig,
    PromptTemplates,
)
from warden.analysis.domain.file_context import FileContext
from warden.analysis.domain.quality_metrics import QualityMetrics
from warden.shared.infrastructure.logging import get_logger
from warden.shared.utils.language_utils import get_language_from_path

logger = get_logger(__name__)


class LLMAnalysisPhase(LLMPhaseBase):
    """
    LLM-enhanced quality analysis phase.

    Uses AI to provide more accurate quality scoring and insights.
    """

    @property
    def phase_name(self) -> str:
        """Get phase name."""
        return "ANALYSIS"

    def get_system_prompt(self) -> str:
        """Get analysis system prompt."""
        return PromptTemplates.QUALITY_ANALYSIS + """

Scoring Guidelines:
- 0-3: Poor quality, significant issues
- 4-6: Average quality, some improvements needed
- 7-8: Good quality, minor improvements
- 9-10: Excellent quality, production-ready

Consider these factors:
1. Code Complexity (cyclomatic, cognitive)
2. Duplication (DRY principle)
3. Maintainability (readability, structure)
4. Naming (clarity, consistency)
5. Documentation (comments, docstrings)
6. Testability (modularity, dependencies)

Adjust scores based on file context:
- Production code: Strict standards
- Test code: Allow higher complexity, some duplication
- Example code: Prioritize clarity and documentation
- Generated code: Focus on correctness

Return a JSON object with scores for each metric."""

    def format_user_prompt(self, context: Dict[str, Any]) -> str:
        """Format user prompt for quality analysis."""
        code = context.get("code", "")
        file_path = context.get("file_path", "unknown")
        file_context = context.get("file_context", FileContext.PRODUCTION.value)
        language = context.get("language", "python")
        metrics = context.get("initial_metrics", {})
        is_impacted = context.get("is_impacted", False)

        prompt = f"""Analyze the following {language} code for quality:

FILE: {file_path}
CONTEXT: {file_context}
LANGUAGE: {language}
IMPACTED_BY_DEPENDENCY: {is_impacted}

CODE:
```{language}
{code[:1500]}  # Truncate for token limit
```

INITIAL METRICS (rule-based):
{json.dumps(metrics, indent=2)}

Please analyze and provide quality scores (0-10) for:
1. complexity_score
2. duplication_score
3. maintainability_score
4. naming_score
5. documentation_score
6. testability_score
7. overall_score (weighted average)

Also identify:
- Top 3 hotspots (areas needing immediate attention)
- Top 3 quick wins (easy improvements with high impact)
- Estimated technical debt hours

Return as JSON."""

        if is_impacted:
            prompt += "\n\nCRITICAL HINT: This file is being re-analyzed because its dependencies have changed. Focus heavily on integration consistency, interface alignment, and potential breaking changes from upstream services."

        return prompt

    def parse_llm_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM quality analysis response."""
        try:
            # Extract JSON from response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "{" in response and "}" in response:
                # Find JSON object in response
                start = response.index("{")
                end = response.rindex("}") + 1
                json_str = response[start:end]
            else:
                raise ValueError("No JSON found in response")

            result = json.loads(json_str)

            # Validate required fields
            required = [
                "complexity_score",
                "duplication_score",
                "maintainability_score",
                "naming_score",
                "documentation_score",
                "testability_score",
                "overall_score",
            ]

            for field in required:
                if field not in result:
                    logger.warning(
                        "missing_field_in_llm_response", field=field, phase=self.phase_name
                    )
                    result[field] = 5.0  # Default middle score

            # Ensure scores are floats between 0-10
            for field in required:
                score = float(result[field])
                result[field] = max(0.0, min(10.0, score))

            # Add optional fields with defaults
            result.setdefault("hotspots", [])
            result.setdefault("quick_wins", [])
            result.setdefault("technical_debt_hours", 0.0)

            return result

        except Exception as e:
            logger.error(
                "llm_response_parsing_failed", phase=self.phase_name, error=str(e)
            )
            # Return default scores on parse failure
            return {
                "complexity_score": 5.0,
                "duplication_score": 5.0,
                "maintainability_score": 5.0,
                "naming_score": 5.0,
                "documentation_score": 5.0,
                "testability_score": 5.0,
                "overall_score": 5.0,
                "hotspots": [],
                "quick_wins": [],
                "technical_debt_hours": 0.0,
            }

    async def analyze_code_quality(
        self,
        code: str,
        file_path: Path,
        file_context: FileContext,
        initial_metrics: Optional[Dict[str, float]] = None,
        is_impacted: bool = False,
    ) -> Tuple[QualityMetrics, float]:
        """
        Analyze code quality with LLM enhancement.

        Args:
            code: Source code to analyze
            file_path: Path to the file
            file_context: File context (production/test/example)
            initial_metrics: Initial rule-based metrics

        Returns:
            Quality metrics and confidence score
        """
        context = {
            "code": code,
            "file_path": str(file_path),
            "file_context": file_context.value,
            "language": self._detect_language(file_path),
            "initial_metrics": initial_metrics or {},
            "is_impacted": is_impacted,
        }

        # Try LLM analysis
        llm_result = await self.analyze_with_llm(context)

        if llm_result:
            # Create QualityMetrics from LLM result
            metrics = QualityMetrics(
                complexity_score=llm_result["complexity_score"],
                duplication_score=llm_result["duplication_score"],
                maintainability_score=llm_result["maintainability_score"],
                naming_score=llm_result["naming_score"],
                documentation_score=llm_result["documentation_score"],
                testability_score=llm_result["testability_score"],
                overall_score=llm_result["overall_score"],
                technical_debt_hours=llm_result.get("technical_debt_hours", 0.0),
            )
            # Add hotspots and quick wins
            metrics.hotspots = []
            metrics.quick_wins = []

            logger.info(
                "llm_quality_analysis_complete",
                file=str(file_path),
                overall_score=metrics.overall_score,
                confidence=0.9,
            )

            return metrics, 0.9  # High confidence with LLM

        # Fallback to rule-based if LLM fails
        if initial_metrics:
            metrics = self._create_metrics_from_rules(initial_metrics, file_context)
            return metrics, 0.6  # Lower confidence without LLM

        # Default metrics if everything fails
        return self._create_default_metrics(file_context), 0.3

    async def analyze_batch(
        self,
        files: List[Tuple[str, Path, FileContext, bool]],
        initial_metrics: Optional[Dict[Path, Dict[str, float]]] = None,
    ) -> Dict[Path, Tuple[QualityMetrics, float]]:
        """
        Analyze multiple files in batch.

        Args:
            files: List of (code, path, context) tuples
            initial_metrics: Initial metrics by file path

        Returns:
            Dictionary of path to (metrics, confidence) tuples
        """
        results = {}

        # Prepare batch contexts
        contexts = []
        for code, path, file_context, is_impacted in files:
            context = {
                "code": code,
                "file_path": str(path),
                "file_context": file_context.value,
                "language": self._detect_language(path),
                "initial_metrics": (
                    initial_metrics.get(path, {}) if initial_metrics else {}
                ),
                "is_impacted": is_impacted,
            }
            contexts.append(context)

        # Batch LLM analysis
        llm_results = await self.analyze_batch_with_llm(contexts)

        # Process results
        for i, (code, path, file_context, is_impacted) in enumerate(files):
            llm_result = llm_results[i]

            if llm_result:
                # Create metrics from LLM result
                metrics = QualityMetrics(
                    complexity_score=llm_result["complexity_score"],
                    duplication_score=llm_result["duplication_score"],
                    maintainability_score=llm_result["maintainability_score"],
                    naming_score=llm_result["naming_score"],
                    documentation_score=llm_result["documentation_score"],
                    testability_score=llm_result["testability_score"],
                    overall_score=llm_result["overall_score"],
                    technical_debt_hours=llm_result.get("technical_debt_hours", 0.0),
                )
                # Add hotspots and quick wins
                metrics.hotspots = []
                metrics.quick_wins = []
                results[path] = (metrics, 0.9)
            else:
                # Fallback to rule-based
                initial = initial_metrics.get(path, {}) if initial_metrics else {}
                if initial:
                    metrics = self._create_metrics_from_rules(initial, file_context)
                    results[path] = (metrics, 0.6)
                else:
                    metrics = self._create_default_metrics(file_context)
                    results[path] = (metrics, 0.3)

        return results

    def _detect_language(self, file_path: Path) -> str:
        """Detect programming language from file path."""
        return get_language_from_path(file_path).value

    def _get_context_weights(self, file_context: FileContext) -> Dict[str, float]:
        """Get weights based on file context."""
        context_weights = {
            FileContext.PRODUCTION: {
                "complexity": 0.25,
                "duplication": 0.20,
                "maintainability": 0.20,
                "naming": 0.15,
                "documentation": 0.15,
                "testability": 0.05,
            },
            FileContext.TEST: {
                "complexity": 0.10,
                "duplication": 0.05,
                "maintainability": 0.15,
                "naming": 0.10,
                "documentation": 0.05,
                "testability": 0.55,
            },
            FileContext.EXAMPLE: {
                "complexity": 0.05,
                "duplication": 0.10,
                "maintainability": 0.10,
                "naming": 0.25,
                "documentation": 0.40,
                "testability": 0.10,
            },
        }
        return context_weights.get(
            file_context,
            context_weights[FileContext.PRODUCTION],
        )

    def _create_metrics_from_rules(
        self,
        rule_metrics: Dict[str, float],
        file_context: FileContext,
    ) -> QualityMetrics:
        """Create QualityMetrics from rule-based analysis."""
        weights = self._get_context_weights(file_context)

        # Apply context weights to scores
        complexity = rule_metrics.get("complexity", 5.0)
        duplication = rule_metrics.get("duplication", 5.0)
        maintainability = rule_metrics.get("maintainability", 5.0)
        naming = rule_metrics.get("naming", 5.0)
        documentation = rule_metrics.get("documentation", 5.0)
        testability = rule_metrics.get("testability", 5.0)

        # Calculate weighted overall score
        overall = (
            complexity * weights["complexity"]
            + duplication * weights["duplication"]
            + maintainability * weights["maintainability"]
            + naming * weights["naming"]
            + documentation * weights["documentation"]
            + testability * weights["testability"]
        )

        return QualityMetrics(
            complexity_score=complexity,
            duplication_score=duplication,
            maintainability_score=maintainability,
            naming_score=naming,
            documentation_score=documentation,
            testability_score=testability,
            overall_score=overall,
            technical_debt_hours=0.0,
        )

    def _create_default_metrics(self, file_context: FileContext) -> QualityMetrics:
        """Create default metrics when analysis fails."""
        weights = self._get_context_weights(file_context)

        return QualityMetrics(
            complexity_score=5.0,
            duplication_score=5.0,
            maintainability_score=5.0,
            naming_score=5.0,
            documentation_score=5.0,
            testability_score=5.0,
            overall_score=5.0,
            technical_debt_hours=0.0,
        )

    async def execute(self, code_files: List[Any], pipeline_context: Optional[Any] = None, impacted_files: List[str] = None) -> QualityMetrics:
        """
        Execute LLM-enhanced analysis phase.

        This is the main entry point called by the orchestrator.
        """
        logger.info(
            "llm_analysis_phase_starting",
            file_count=len(code_files) if code_files else 0,
            has_llm=self.llm is not None
        )

        # For now, analyze first file if available
        if code_files and len(code_files) > 0:
            code_file = code_files[0]
            file_path = Path(code_file.path) if hasattr(code_file, 'path') else Path("unknown")
            code = code_file.content if hasattr(code_file, 'content') else ""

            # Determine file context
            file_context = FileContext.PRODUCTION

            # Check for impact
            is_impacted = impacted_files and str(file_path) in impacted_files

            # Analyze with LLM
            metrics, confidence = await self.analyze_code_quality(
                code=code,
                file_path=file_path,
                file_context=file_context,
                initial_metrics=None,
                is_impacted=is_impacted
            )

            logger.info(
                "llm_analysis_phase_complete",
                overall_score=metrics.overall_score,
                confidence=confidence,
                used_llm=confidence > 0.7
            )

            return metrics

        # Return default metrics if no files
        return self._create_default_metrics(FileContext.PRODUCTION)