"""
LLM-Enhanced Classification Phase.

Context-aware frame selection and false positive suppression with AI.
"""

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from warden.analysis.application.llm_phase_base import (
    LLMPhaseBase,
    LLMPhaseConfig,
)
from warden.classification.application.classification_prompts import (
    get_classification_system_prompt,
    format_classification_user_prompt,
)
from warden.analysis.domain.file_context import FileContext
from warden.analysis.domain.project_context import Framework, ProjectType
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class SuppressionReason(Enum):
    """Reasons for suppressing findings."""

    TEST_CODE = "test_code"
    EXAMPLE_CODE = "example_code"
    GENERATED_CODE = "generated_code"
    DOCUMENTATION = "documentation"
    FRAMEWORK_PATTERN = "framework_pattern"
    FALSE_POSITIVE = "false_positive"
    INTENTIONAL = "intentional"


class LLMClassificationPhase(LLMPhaseBase):
    """
    LLM-enhanced classification phase.

    Intelligently selects validation frames and suppresses false positives.
    """

    def __init__(self, config: LLMPhaseConfig, llm_service: Any, available_frames: List[Any] = None, context: Dict[str, Any] = None, semantic_search_service: Any = None) -> None:
        """
        Initialize LLM classification phase.
        
        Args:
            config: Phase configuration
            llm_service: LLM service instance
            available_frames: List of validation frames to choose from
            context: Pipeline context dictionary
            semantic_search_service: Optional semantic search service
        """
        super().__init__(config, llm_service)
        self.available_frames = available_frames or []
        self.context = context or {}
        self.semantic_search_service = semantic_search_service

    @property
    def phase_name(self) -> str:
        """Get phase name."""
        return "CLASSIFICATION"

    def get_system_prompt(self) -> str:
        """Get classification system prompt."""
        return get_classification_system_prompt(self.available_frames)

    def format_user_prompt(self, context: Dict[str, Any]) -> str:
        """Format user prompt for classification."""
        return format_classification_user_prompt(context)

    def parse_llm_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM classification response."""
        try:
            from warden.shared.utils.json_parser import parse_json_from_llm
            result = parse_json_from_llm(response)
            if not result:
                raise ValueError("No valid JSON found in response")
            
            # Ensure it's a dict
            if not isinstance(result, dict):
                 raise ValueError(f"Expected dict, got {type(result)}")

            # Validate and provide defaults
            # Use explicit check for empty list instead of setdefault
            if not result.get("selected_frames"):  # Handles None, [], or missing key
                result["selected_frames"] = ["security", "chaos", "orphan"]
                logger.warning("llm_returned_empty_frames", using_defaults=True)

            result.setdefault("suppression_rules", [])
            result.setdefault("priorities", {})
            result.setdefault("reasoning", "")

            return result

        except Exception as e:
            logger.error(
                "llm_response_parsing_failed",
                phase=self.phase_name,
                error=str(e),
            )
            # Return default classification
            return {
                "selected_frames": ["security", "chaos", "orphan"],
                "suppression_rules": [],
                "priorities": {
                    "security": "CRITICAL",
                    "chaos": "HIGH",
                    "orphan": "MEDIUM",
                },
                "reasoning": "Default frame selection due to parse error",
            }

    async def classify_and_select_frames(
        self,
        project_type: ProjectType,
        framework: Framework,
        file_contexts: Dict[str, Dict[str, Any]],
        file_path: Optional[str] = None,
        previous_issues: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[str], Dict[str, Any], float]:
        """
        Classify project and select validation frames.

        Args:
            project_type: Type of project
            framework: Framework being used
            file_contexts: File context information
            file_path: Optional specific file to analyze
            previous_issues: Issues from previous runs

        Returns:
            Selected frame IDs, suppression config, and confidence
        """
        context = {
            "project_type": project_type.value,
            "framework": framework.value,
            "file_contexts": file_contexts,
            "file_path": file_path or "",
            "previous_issues": previous_issues or [],
        }

        # Retrieve semantic context if service is available
        if self.semantic_search_service and self.semantic_search_service.is_available():
            try:
                semantic_context = await self.semantic_search_service.get_context(
                    query=f"Architectural patterns and security sensitive code in {file_path}",
                    language="python" # Should be dynamic based on code_files[0].language
                )
                if semantic_context:
                    context["semantic_context"] = {
                        "relevant_chunks": [c.content[:500] for c in semantic_context.relevant_chunks[:3]],
                        "average_score": semantic_context.average_score
                    }
            except Exception as e:
                logger.warning("semantic_context_retrieval_failed", error=str(e))

        # Try LLM classification
        llm_result = await self.analyze_with_llm(context)

        if llm_result:
            selected_frames = llm_result["selected_frames"]

            # Normalize frame names (LLM might return class names like "SecurityFrame")
            normalized_frames = []
            for frame in selected_frames:
                # Convert class names to frame IDs
                # SecurityFrame -> security, ChaosFrame -> chaos, etc.
                normalized = frame.lower().replace("frame", "").replace("-", "").replace("_", "")
                normalized_frames.append(normalized)

            selected_frames = normalized_frames

            # Safety check: ensure we always have some frames
            if not selected_frames:
                logger.warning("llm_classification_empty", fallback_to_defaults=True)
                selected_frames = ["security", "chaos", "orphan"]

            suppression_config = {
                "rules": llm_result["suppression_rules"],
                "priorities": llm_result["priorities"],
                "reasoning": llm_result["reasoning"],
            }

            logger.info(
                "llm_classification_complete",
                selected_frames=selected_frames,
                suppression_count=len(llm_result["suppression_rules"]),
                confidence=0.85,
            )

            return selected_frames, suppression_config, 0.85

        # Fallback to rule-based classification
        selected_frames = self._rule_based_selection(
            project_type, framework, file_contexts
        )
        suppression_config = self._default_suppression_config(file_contexts)

        return selected_frames, suppression_config, 0.6

    async def generate_suppression_rules(
        self,
        findings: List[Dict[str, Any]],
        file_contexts: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Generate suppression rules for false positives.

        Args:
            findings: List of findings to analyze
            file_contexts: File context information

        Returns:
            List of suppression rules
        """
        if not findings:
            return []

        context = {
            "findings": findings[:50],  # Limit for token count
            "file_contexts": file_contexts,
        }

        prompt = f"""Analyze these findings and identify false positives to suppress:

FINDINGS:
{json.dumps(findings[:5], indent=2)}

FILE CONTEXTS:
{json.dumps(list(file_contexts.items())[:5], indent=2)}

For each finding that should be suppressed:
1. Provide the finding ID
2. Give suppression reason
3. Explain why it's a false positive

Return as JSON list of suppression rules."""

        llm_result = await self.analyze_with_llm(
            {"custom_prompt": prompt}
        )

        if llm_result and isinstance(llm_result, list):
            return llm_result

        # Fallback to rule-based suppression
        return self._rule_based_suppression(findings, file_contexts)

    async def learn_from_feedback(
        self,
        false_positive_ids: List[str],
        true_positive_ids: List[str],
        findings: List[Dict[str, Any]],
    ) -> None:
        """
        Learn from user feedback on findings.

        Args:
            false_positive_ids: IDs marked as false positives
            true_positive_ids: IDs confirmed as true positives
            findings: All findings for context
        """
        if not false_positive_ids and not true_positive_ids:
            return

        context = {
            "false_positives": [
                f for f in findings if f.get("id") in false_positive_ids
            ],
            "true_positives": [
                f for f in findings if f.get("id") in true_positive_ids
            ],
        }

        prompt = f"""Learn from this feedback to improve future classification:

FALSE POSITIVES (should be suppressed):
{json.dumps(context['false_positives'][:10], indent=2)}

TRUE POSITIVES (correctly identified):
{json.dumps(context['true_positives'][:10], indent=2)}

Extract patterns to:
1. Better identify false positives
2. Avoid suppressing true positives
3. Improve suppression rules

Return patterns as JSON."""

        llm_result = await self.analyze_with_llm({"custom_prompt": prompt})

        if llm_result:
            # Cache learned patterns for future use
            if self.cache:
                self.cache.set("learned_patterns", llm_result)

            logger.info(
                "classification_learning_complete",
                false_positive_count=len(false_positive_ids),
                true_positive_count=len(true_positive_ids),
            )

    def _rule_based_selection(
        self,
        project_type: ProjectType,
        framework: Framework,
        file_contexts: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """Rule-based frame selection fallback."""
        selected = []

        # Always include security for applications
        if project_type in [ProjectType.APPLICATION, ProjectType.MICROSERVICE]:
            selected.append("security")

        # Add resilience for services
        if project_type in [ProjectType.MICROSERVICE, ProjectType.APPLICATION]:
            selected.append("resilience")

        # Add orphan for all projects
        selected.append("orphan")

        # Add architectural for larger projects
        if len(file_contexts) > 10:
            selected.append("architectural")

        # Add stress for APIs
        if framework in [Framework.FASTAPI, Framework.FLASK, Framework.DJANGO]:
            selected.append("stress")

        return selected

    def _default_suppression_config(
        self,
        file_contexts: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generate default suppression configuration."""
        rules = []

        # Count context types
        has_tests = any(
            fc.get("context") == "TEST" for fc in file_contexts.values()
        )
        has_examples = any(
            fc.get("context") == "EXAMPLE" for fc in file_contexts.values()
        )

        if has_tests:
            rules.append({
                "pattern": "test_*.py",
                "reason": SuppressionReason.TEST_CODE.value,
                "suppress_types": ["hardcoded_password", "sql_injection"],
            })

        if has_examples:
            rules.append({
                "pattern": "examples/**",
                "reason": SuppressionReason.EXAMPLE_CODE.value,
                "suppress_types": ["all"],
            })

        return {
            "rules": rules,
            "priorities": {
                "security": "CRITICAL",
                "resilience": "HIGH",
                "orphan": "MEDIUM",
            },
            "reasoning": "Default suppression based on file contexts",
        }

    def _rule_based_suppression(
        self,
        findings: List[Dict[str, Any]],
        file_contexts: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Rule-based suppression generation."""
        suppression_rules = []

        for finding in findings:
            file_path = finding.get("file_path", "")
            file_context = file_contexts.get(file_path, {})
            context_type = file_context.get("context", "PRODUCTION")

            # Suppress test file vulnerabilities
            if context_type == "TEST" and finding.get("type") in [
                "hardcoded_password",
                "sql_injection",
            ]:
                suppression_rules.append({
                    "finding_id": finding.get("id"),
                    "reason": SuppressionReason.TEST_CODE.value,
                    "explanation": "Intentional vulnerability in test file",
                })

            # Suppress example code issues
            elif context_type == "EXAMPLE":
                suppression_rules.append({
                    "finding_id": finding.get("id"),
                    "reason": SuppressionReason.EXAMPLE_CODE.value,
                    "explanation": "Educational example code",
                })

        return suppression_rules

    async def execute_async(self, code_files: List[Any]) -> Any:
        """
        Execute LLM-enhanced classification phase.

        This is the main entry point called by the orchestrator.
        """
        logger.info(
            "llm_classification_phase_starting",
            file_count=len(code_files) if code_files else 0,
            has_llm=self.llm is not None
        )

        # Mock classification result for now
        from dataclasses import dataclass

        @dataclass
        class ClassificationResult:
            selected_frames: List[str]
            suppression_rules: List[Dict[str, Any]]
            frame_priorities: Dict[str, str]
            reasoning: str
            learned_patterns: List[Dict[str, Any]]

        # Use LLM to select frames if available
        if self.llm and code_files:
            # Use actual context values
            project_type_str = self.context.get("project_type", ProjectType.APPLICATION.value)
            framework_str = self.context.get("framework", Framework.NONE.value)
            
            # Helper to safely convert string to Enum
            def get_enum_safe(enum_cls, value, default):
                try:
                    return enum_cls(value)
                except ValueError:
                    return default

            project_type = get_enum_safe(ProjectType, project_type_str, ProjectType.APPLICATION)
            framework = get_enum_safe(Framework, framework_str, Framework.NONE)
            # Serialize file contexts if they are objects
            raw_file_contexts = self.context.get("file_contexts", {})
            file_contexts = {}
            for path, ctx in raw_file_contexts.items():
                # Handle Pydantic models (FileContextInfo)
                if hasattr(ctx, "model_dump"):
                    file_contexts[path] = ctx.model_dump(mode='json')
                elif hasattr(ctx, "to_json"):
                    file_contexts[path] = ctx.to_json()
                elif hasattr(ctx, "dict"):
                    file_contexts[path] = ctx.dict()
                else:
                    file_contexts[path] = ctx

            previous_issues = self.context.get("previous_issues", [])

            # Log context usage for traceability
            logger.info(
                "llm_classification_using_context",
                project_type=project_type.value,
                framework=framework.value,
                file_contexts_count=len(file_contexts),
                previous_issues_count=len(previous_issues)
            )

            selected_frames, suppression_config, confidence = await self.classify_and_select_frames(
                project_type=project_type,
                framework=framework,
                file_contexts=file_contexts,
                file_path=code_files[0].path if code_files else None,
                previous_issues=previous_issues
            )

            logger.info(
                "llm_classification_complete",
                frames=selected_frames,
                confidence=confidence,
                used_llm=True
            )

            # Final safety check before returning
            if not selected_frames:
                logger.warning("execute_async_empty_frames", using_fallback=True)
                selected_frames = ["security", "chaos", "orphan"]

            return ClassificationResult(
                selected_frames=selected_frames,
                suppression_rules=suppression_config.get("rules", []),
                frame_priorities=suppression_config.get("priorities", {}),
                reasoning=suppression_config.get("reasoning", "LLM-based selection"),
                learned_patterns=[]
            )

        # Fallback to default
        return ClassificationResult(
            selected_frames=["security", "chaos", "orphan"],
            suppression_rules=[],
            frame_priorities={"security": "CRITICAL", "chaos": "HIGH", "orphan": "MEDIUM"},
            reasoning="Default frame selection (no LLM)",
            learned_patterns=[]
        )