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
    PromptTemplates,
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

    @property
    def phase_name(self) -> str:
        """Get phase name."""
        return "CLASSIFICATION"

    def get_system_prompt(self) -> str:
        """Get classification system prompt."""
        return PromptTemplates.FRAME_SELECTION + """

Frame Selection Criteria:
1. Project Type: Match frames to project characteristics
2. Framework: Use framework-specific validation
3. File Context: Skip irrelevant frames for test/example code
4. Previous Issues: Prioritize frames that found issues before
5. Risk Level: Focus on high-risk areas

Available Frames:
- SecurityFrame: SQL injection, XSS, hardcoded secrets
- ChaosFrame: Error handling, timeouts, resilience
- OrphanFrame: Unused code detection
- ArchitecturalFrame: Design pattern compliance
- StressFrame: Performance and load testing
- PropertyFrame: Invariant and contract validation
- FuzzFrame: Input validation and edge cases

Suppression Guidelines:
- Test files with intentional vulnerabilities
- Example code demonstrating bad practices
- Generated code from trusted sources
- Framework-specific patterns
- Documentation code snippets

Return a JSON object with:
1. selected_frames: List of frame IDs to run
2. suppression_rules: Rules for false positive filtering
3. priorities: Priority order for frames
4. reasoning: Brief explanation of choices"""

    def format_user_prompt(self, context: Dict[str, Any]) -> str:
        """Format user prompt for classification."""
        project_type = context.get("project_type", ProjectType.APPLICATION.value)
        framework = context.get("framework", Framework.NONE.value)
        file_contexts = context.get("file_contexts", {})
        previous_issues = context.get("previous_issues", [])
        file_path = context.get("file_path", "")

        # Analyze file context distribution
        context_counts = {}
        for fc in file_contexts.values():
            context_type = fc.get("context", "UNKNOWN")
            context_counts[context_type] = context_counts.get(context_type, 0) + 1

        prompt = f"""Analyze the project and select appropriate validation frames:

PROJECT TYPE: {project_type}
FRAMEWORK: {framework}
FILE: {file_path}

FILE CONTEXT DISTRIBUTION:
{json.dumps(context_counts, indent=2)}

PREVIOUS ISSUES FOUND:
{json.dumps(previous_issues[:10], indent=2) if previous_issues else "None"}

PROJECT CHARACTERISTICS:
- Total files: {len(file_contexts)}
- Test files: {context_counts.get('TEST', 0)}
- Example files: {context_counts.get('EXAMPLE', 0)}
- Production files: {context_counts.get('PRODUCTION', 0)}

Based on this context:
1. Which validation frames should run?
2. What suppression rules should apply?
3. What priority order for frames?

Consider:
- Don't run SecurityFrame on test files with intentional vulnerabilities
- Skip ArchitecturalFrame for small scripts
- Prioritize frames that found issues previously
- Apply framework-specific suppressions

Return as JSON."""

        return prompt

    def parse_llm_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM classification response."""
        try:
            # Extract JSON from response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "{" in response and "}" in response:
                start = response.index("{")
                end = response.rindex("}") + 1
                json_str = response[start:end]
            else:
                raise ValueError("No JSON found in response")

            result = json.loads(json_str)

            # Validate and provide defaults
            result.setdefault("selected_frames", ["security", "chaos", "orphan"])
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

        # Try LLM classification
        llm_result = await self.analyze_with_llm(context)

        if llm_result:
            selected_frames = llm_result["selected_frames"]
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
{json.dumps(findings[:20], indent=2)}

FILE CONTEXTS:
{json.dumps(list(file_contexts.items())[:10], indent=2)}

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

        # Add chaos for services
        if project_type in [ProjectType.MICROSERVICE, ProjectType.APPLICATION]:
            selected.append("chaos")

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
                "chaos": "HIGH",
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