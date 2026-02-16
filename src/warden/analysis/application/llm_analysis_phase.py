"""
LLM-Enhanced Analysis Phase.

Context-aware quality scoring with AI assistance.
"""

import json
from pathlib import Path
from typing import Any

from warden.analysis.application.llm_phase_base import (
    LLMPhaseBase,
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
        return (
            PromptTemplates.QUALITY_ANALYSIS
            + """

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
        )

    def format_user_prompt(self, context: dict[str, Any]) -> str:
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

        related_context = context.get("related_context")
        if related_context:
            prompt += f"\n\nRELEVANT CODE CONTEXT (from Vector DB):\n{related_context}\n\nUse this context to check for consistency with existing project patterns."

        if is_impacted:
            prompt += "\n\nCRITICAL HINT: This file is being re-analyzed because its dependencies have changed. Focus heavily on integration consistency, interface alignment, and potential breaking changes from upstream services."

        return prompt

    def parse_llm_response(self, response: str) -> dict[str, Any]:
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
                    logger.warning("missing_field_in_llm_response", field=field, phase=self.phase_name)
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
            logger.error("llm_response_parsing_failed", phase=self.phase_name, error=str(e))
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

    async def analyze_code_quality_async(
        self,
        code: str,
        file_path: Path,
        file_context: FileContext,
        initial_metrics: dict[str, float] | None = None,
        is_impacted: bool = False,
    ) -> tuple[QualityMetrics, float]:
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

        # --- Active Context Retrieval Integration ---
        if (
            hasattr(self, "semantic_search_service")
            and self.semantic_search_service
            and self.semantic_search_service.is_available()
        ):
            try:
                formatted_context = await self._retrieve_and_format_context(file_path, code)
                if formatted_context:
                    context["related_context"] = formatted_context
                    logger.debug("active_context_retrieved", file=str(file_path))
            except Exception as e:
                logger.warning("active_context_retrieval_failed", error=str(e))
        # ---------------------------------------------

        # Try LLM analysis
        llm_result = await self.analyze_with_llm_async(context)

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

    async def analyze_batch_async(
        self,
        files: list[tuple[str, Path, FileContext, bool]],
        initial_metrics: dict[Path, dict[str, float]] | None = None,
    ) -> dict[Path, tuple[QualityMetrics, float]]:
        """
        Analyze multiple files in batch using True LLM Batching.
        """
        results = {}
        if not files:
            return results

        if not self.config.enabled or not self.llm:
            # Fallback to rules for all
            for _, path, file_context, _ in files:
                initial = initial_metrics.get(path, {}) if initial_metrics else {}
                results[path] = (self._create_metrics_from_rules(initial, file_context), 0.6)
            return results

        # Initial requested batch size
        requested_batch_size = 5

        i = 0
        while i < len(files):
            # Dynamically adjust batch size based on system resources
            batch_size = self._get_realtime_safe_batch_size(requested_batch_size)
            batch_items = files[i : i + batch_size]

            try:
                # Prepare Batch Prompt
                prompt = self._format_batch_user_prompt(batch_items, initial_metrics)

                # Call LLM
                response = await self.llm.complete_async(
                    prompt,
                    self.get_system_prompt(),
                    use_fast_tier=True,  # Use Qwen for cost optimization (Phase 1 migration)
                )

                # Parse Batch Results
                batch_results = self._parse_batch_llm_response(response.content, len(batch_items))

                # Map back to paths
                for idx, item in enumerate(batch_items):
                    _, path, file_context, _ = item
                    llm_data = batch_results[idx] if idx < len(batch_results) else None

                    if llm_data:
                        metrics = QualityMetrics(
                            complexity_score=llm_data.get("complexity_score", 5.0),
                            duplication_score=llm_data.get("duplication_score", 5.0),
                            maintainability_score=llm_data.get("maintainability_score", 5.0),
                            naming_score=llm_data.get("naming_score", 5.0),
                            documentation_score=llm_data.get("documentation_score", 5.0),
                            testability_score=llm_data.get("testability_score", 5.0),
                            overall_score=llm_data.get("overall_score", 5.0),
                            technical_debt_hours=llm_data.get("technical_debt_hours", 0.0),
                        )
                        results[path] = (metrics, 0.9)
                    else:
                        # Fallback for this specific item in batch
                        initial = initial_metrics.get(path, {}) if initial_metrics else {}
                        results[path] = (self._create_metrics_from_rules(initial, file_context), 0.5)

            except Exception as e:
                logger.error("batch_quality_analysis_failed", error=str(e))
                # Fallback for the whole batch
                for _, path, file_context, _ in batch_items:
                    initial = initial_metrics.get(path, {}) if initial_metrics else {}
                    results[path] = (self._create_metrics_from_rules(initial, file_context), 0.5)
            # Increment by the actual size of the batch we just processed
            i += len(batch_items)

        return results

    def _format_batch_user_prompt(
        self, batch_items: list[tuple[str, Path, FileContext, bool]], initial_metrics: Any
    ) -> str:
        batch_summary = ""
        for i, (code, path, ctx, impacted) in enumerate(batch_items):
            metrics = initial_metrics.get(path, {}) if initial_metrics else {}
            batch_summary += f"""
FILE #{i}: {path.name}
Path: {path}
Context: {ctx.value}
Impacted: {impacted}
Initial Metrics: {json.dumps(metrics)}
Code Snippet:
```{self._detect_language(path)}
{code[:1000]}
```
---
"""
        return f"""Analyze the quality of {len(batch_items)} files.
Return a JSON array of objects with the following schema for EACH file:
{{
  "idx": int,
  "complexity_score": float,
  "duplication_score": float,
  "maintainability_score": float,
  "naming_score": float,
  "documentation_score": float,
  "testability_score": float,
  "overall_score": float,
  "technical_debt_hours": float
}}

FILES TO ANALYZE:
{batch_summary}
"""

    def _parse_batch_llm_response(self, response: str, count: int) -> list[dict[str, Any]]:
        try:
            # Extract JSON array
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "[" in response and "]" in response:
                start = response.index("[")
                end = response.rindex("]") + 1
                json_str = response[start:end]
            else:
                return []

            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError, IndexError, KeyError):
            # JSON parsing failed - return empty list for graceful degradation
            return []

    def _detect_language(self, file_path: Path) -> str:
        """Detect programming language from file path."""
        return get_language_from_path(file_path).value

    def _get_context_weights(self, file_context: FileContext) -> dict[str, float]:
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
        rule_metrics: dict[str, float],
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
        self._get_context_weights(file_context)

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

    async def execute_async(
        self, code_files: list[Any], pipeline_context: Any | None = None, impacted_files: list[str] = None
    ) -> QualityMetrics:
        """
        Execute LLM-enhanced analysis phase with True Batching.
        """
        if not code_files:
            return self._create_default_metrics(FileContext.PRODUCTION)

        logger.info("llm_analysis_phase_starting_batch", file_count=len(code_files), has_llm=self.llm is not None)

        # Prepare items for batch analysis
        batch_items = []
        for code_file in code_files:
            file_path = Path(code_file.path) if hasattr(code_file, "path") else Path("unknown")
            code = code_file.content if hasattr(code_file, "content") else ""

            # Use FileContext from context if available, else default to PRODUCTION
            # In a real scenario, we'd get this from the PreAnalysis phase
            file_context = FileContext.PRODUCTION
            if pipeline_context and hasattr(pipeline_context, "file_contexts"):
                ctx_info = pipeline_context.file_contexts.get(str(file_path))
                if ctx_info:
                    file_context = ctx_info.context

            is_impacted = impacted_files and str(file_path) in impacted_files
            batch_items.append((code, file_path, file_context, is_impacted))

        # Perform Batch Analysis
        batch_results = await self.analyze_batch_async(batch_items)

        if not batch_results:
            return self._create_default_metrics(FileContext.PRODUCTION)

        # Aggregate results (for the whole project score)
        all_metrics = [m for m, _ in batch_results.values()]

        avg_metrics = QualityMetrics(
            complexity_score=sum(m.complexity_score for m in all_metrics) / len(all_metrics),
            duplication_score=sum(m.duplication_score for m in all_metrics) / len(all_metrics),
            maintainability_score=sum(m.maintainability_score for m in all_metrics) / len(all_metrics),
            naming_score=sum(m.naming_score for m in all_metrics) / len(all_metrics),
            documentation_score=sum(m.documentation_score for m in all_metrics) / len(all_metrics),
            testability_score=sum(m.testability_score for m in all_metrics) / len(all_metrics),
            overall_score=sum(m.overall_score for m in all_metrics) / len(all_metrics),
            technical_debt_hours=sum(m.technical_debt_hours for m in all_metrics),
            summary=f"Analyzed {len(all_metrics)} files in batch mode.",
        )

        logger.info("llm_batch_analysis_complete", avg_score=avg_metrics.overall_score, total_files=len(all_metrics))

        return avg_metrics

    async def _retrieve_and_format_context(self, file_path: Path, code: str) -> str | None:
        """
        Retrieve and format related code context from semantic search.

        Args:
            file_path: Path of the file being analyzed
            code: Content of the file

        Returns:
            Formatted context string or None
        """
        # Use a summary of the code and filename as query
        query = f"Code quality analysis for {file_path.name}: {code[:300]}"
        # Detect language for filtering if possible
        lang_str = self._detect_language(file_path)

        retrieval = await self.semantic_search_service.get_context(query, language=lang_str)

        if not retrieval or not retrieval.relevant_chunks:
            return None

        formatted_context = ""
        relevant_count = 0

        for chunk in retrieval.relevant_chunks:
            # Skip self if matched (using robust path comparison)
            # Assuming chunk.relative_path is relative to project root
            # We can't easily do Path comparison without project root here easily unless stored,
            # but usually relative_path is unique enough.
            # Safe check: if filename and some content matches
            if chunk.relative_path.endswith(file_path.name):
                # Potential self-match, check content overlap or skip to be safe
                continue

            formatted_context += (
                f"\n--- Related File: {chunk.relative_path} (Lines {chunk.start_line}-{chunk.end_line}) ---\n"
            )
            formatted_context += f"{chunk.content}\n"
            relevant_count += 1

        if relevant_count > 0:
            return formatted_context

        return None
