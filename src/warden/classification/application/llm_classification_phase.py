"""
LLM-Enhanced Classification Phase.

Context-aware frame selection and false positive suppression with AI.
"""

import json
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from warden.analysis.application.llm_phase_base import (
    LLMPhaseBase,
    LLMPhaseConfig,
)
from warden.classification.application.classification_prompts import (
    get_classification_system_prompt,
    format_classification_user_prompt,
)
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

    def __init__(self, config: LLMPhaseConfig, llm_service: Any, available_frames: List[Any] = None, context: Dict[str, Any] = None, semantic_search_service: Any = None, memory_manager: Any = None, rate_limiter: Any = None) -> None:
        """
        Initialize LLM classification phase.
        
        Args:
            config: Phase configuration
            llm_service: LLM service instance
            available_frames: List of validation frames to choose from
            context: Pipeline context dictionary
            semantic_search_service: Optional semantic search service
            memory_manager: Optional memory manager for caching
            rate_limiter: Optional shared RateLimiter
        """
        super().__init__(config, llm_service, project_root=None, memory_manager=memory_manager, rate_limiter=rate_limiter)
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
            result.setdefault("suppression_rules", [])
            result.setdefault("priorities", {})
            result.setdefault("reasoning", "")
            result.setdefault("advisories", [])

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
                "advisories": ["Warning: LLM parsing failed, using default frames."],
            }

    async def classify_batch_async(
        self,
        project_type: ProjectType,
        framework: Framework,
        files: List[str],
        file_contexts: Dict[str, Dict[str, Any]],
        previous_issues: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Tuple[List[str], Dict[str, Any], float]]:
        """
        Classify multiple files in batch for frame selection.
        """
        results = {}
        if not files:
            return results

        if not self.config.enabled or not self.llm:
            # Fallback for all
            for file_path in files:
                selected_frames = self._rule_based_selection(project_type, framework, {file_path: file_contexts.get(file_path, {})})
                suppression_config = self._default_suppression_config({file_path: file_contexts.get(file_path, {})})
                results[file_path] = (selected_frames, suppression_config, 0.6)
            return results

        # Initial requested batch size
        requested_batch_size = 2
        
        i = 0
        while i < len(files):
            # Dynamically adjust batch size based on system resources
            batch_size = self._get_realtime_safe_batch_size(requested_batch_size)
            batch_files = files[i : i + batch_size]
            
            try:
                # Prepare Batch Prompt
                prompt = self._format_classification_batch_user_prompt(
                    project_type, framework, batch_files, file_contexts, previous_issues
                )
                
                # Call LLM via Base Retry Logic (Enables Complexity Routing & Rate Limiting)
                response = await self._call_llm_with_retry_async(
                    system_prompt=self.get_system_prompt(),
                    user_prompt=prompt,
                    use_fast_tier=True
                )
                
                # Parse Batch Results
                batch_results = self._parse_classification_batch_response(response.content, len(batch_files))
                
                # Map back
                for idx, file_path in enumerate(batch_files):
                    llm_data = batch_results[idx] if idx < len(batch_results) else None
                    if llm_data:
                        selected_frames = llm_data.get("selected_frames", ["security", "chaos", "orphan"])
                        # Normalize
                        selected_frames = [f.lower().replace("frame", "").strip() for f in selected_frames]
                        
                        suppression_config = {
                            "rules": llm_data.get("suppression_rules", []),
                            "priorities": llm_data.get("priorities", {}),
                            "reasoning": llm_data.get("reasoning", ""),
                            "advisories": llm_data.get("advisories", [])
                        }
                        results[file_path] = (selected_frames, suppression_config, 0.85)
                    else:
                        # Fallback
                        selected_frames = self._rule_based_selection(project_type, framework, {file_path: file_contexts.get(file_path, {})})
                        suppression_config = self._default_suppression_config({file_path: file_contexts.get(file_path, {})})
                        results[file_path] = (selected_frames, suppression_config, 0.5)

            except Exception as e:
                logger.error("batch_classification_failed", error=str(e))
                for file_path in batch_files:
                    selected_frames = self._rule_based_selection(project_type, framework, {file_path: file_contexts.get(file_path, {})})
                    suppression_config = self._default_suppression_config({file_path: file_contexts.get(file_path, {})})
                    results[file_path] = (selected_frames, suppression_config, 0.5)
            # Increment by the actual size of the batch we just processed
            i += len(batch_files)

        return results

    def _format_classification_batch_user_prompt(self, project_type, framework, files, file_contexts, previous_issues) -> str:
        batch_summary = ""
        for i, file_path in enumerate(files):
            ctx = file_contexts.get(file_path, {})
            batch_summary += f"""
FILE #{i}: {file_path}
Context: {json.dumps(ctx)}
"""
        return f"""Classify and select validation frames for {len(files)} files in a {framework.value} {project_type.value} project.
Return a JSON array of objects with schema:
{{
  "idx": int,
  "selected_frames": ["security", "chaos", ...],
  "suppression_rules": [...],
  "priorities": {{...}},
  "reasoning": "...",
  "advisories": ["Warn: ...", "Note: ..."]
}}

FILES TO ANALYZE:
{{batch_summary}}
"""

    def _parse_classification_batch_response(self, response: str, count: int) -> List[Dict[str, Any]]:
        try:
            from warden.shared.utils.json_parser import parse_json_from_llm
            result = parse_json_from_llm(response)
            if isinstance(result, list):
                return result
            # Try to handle if it returns a single object instead of list
            if isinstance(result, dict):
                 return [result]
            return []
        except (json.JSONDecodeError, ValueError, KeyError, TypeError):
            # LLM response parsing failed - return empty list for graceful degradation
            return []

    async def generate_suppression_rules_async(
        self,
        findings: List[Dict[str, Any]],
        file_contexts: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        # ... (unchanged) ...
        return await super().generate_suppression_rules_async(findings, file_contexts) # Reverting to original flow if not needed
        # Actually I need to keep the method, I just won't touch it.
        # But wait, replace_file_content replaces chunks. I should have targeted smaller chunks.
        # Since I'm targeting big chunks, I need to be careful.
        # I'll just skip replacing generate_suppression_rules_async in this call and rely on the existing one.
        # The key is to properly implementation classify_batch_async and the return of execute_async.

    # ... (skipping generate_suppression_rules_async and learn_from_feedback_async as they are fine) ...

    # Wait, I cannot skip methods in the middle of a large replacement block if I claimed to replace up to line 535.
    # I should restart the strategy and use multiple smaller edits.

    async def generate_suppression_rules_async(
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

        {
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

        llm_result = await self.analyze_with_llm_async(
            {"custom_prompt": prompt}
        )

        if llm_result and isinstance(llm_result, list):
            return llm_result

        # Fallback to rule-based suppression
        return self._rule_based_suppression(findings, file_contexts)

    async def learn_from_feedback_async(
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

        llm_result = await self.analyze_with_llm_async({"custom_prompt": prompt})

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
        Execute LLM-enhanced classification phase with True Batching.
        """
        if not code_files:
            return self._create_default_result(["security", "chaos", "orphan"])

        logger.info(
            "llm_classification_phase_starting_batch",
            file_count=len(code_files),
            has_llm=self.llm is not None
        )

        # Prepare context
        project_type_str = self.context.get("project_type", ProjectType.APPLICATION.value)
        framework_str = self.context.get("framework", Framework.NONE.value)
        
        def get_enum_safe(enum_cls, value, default):
            try:
                return enum_cls(value)
            except ValueError:
                return default

        project_type = get_enum_safe(ProjectType, project_type_str, ProjectType.APPLICATION)
        framework = get_enum_safe(Framework, framework_str, Framework.NONE)
        
        raw_file_contexts = self.context.get("file_contexts", {})
        file_contexts = {}
        for path, ctx in raw_file_contexts.items():
            if hasattr(ctx, "model_dump"):
                file_contexts[path] = ctx.model_dump(mode='json')
            elif hasattr(ctx, "to_json"):
                file_contexts[path] = ctx.to_json()
            elif hasattr(ctx, "dict"):
                file_contexts[path] = ctx.dict()
            else:
                file_contexts[path] = ctx

        previous_issues = self.context.get("previous_issues", [])
        file_paths = [cf.path for cf in code_files]

        # Perform Batch Classification
        # classify_batch_async returns Dict[str, Tuple[List[str], Dict[str, Any], float]]
        batch_results = await self.classify_batch_async(
            project_type=project_type,
            framework=framework,
            files=file_paths,
            file_contexts=file_contexts,
            previous_issues=previous_issues
        )

        if not batch_results:
             return self._create_default_result(["security", "chaos", "orphan"])

        # Aggregate results
        # For frames, we take a UNION of all frames suggested for any file in the project
        all_frames = set()
        all_suppression_rules = []
        all_priorities = {}
        all_reasoning = []
        all_advisories = []

        for file_path, (frames, suppression_config, confidence) in batch_results.items():
            all_frames.update(frames)
            all_suppression_rules.extend(suppression_config.get("rules", []))
            all_priorities.update(suppression_config.get("priorities", {}))
            if suppression_config.get("reasoning"):
                all_reasoning.append(f"{file_path}: {suppression_config['reasoning']}")
            if suppression_config.get("advisories"):
                all_advisories.extend(suppression_config.get("advisories", []))

        # Ensure we always have some base frames
        if not all_frames:
            all_frames = {"security", "chaos", "orphan"}

        logger.info(
            "llm_batch_classification_complete",
            frames=list(all_frames),
            files_analyzed=len(batch_results)
        )

        from dataclasses import dataclass
        @dataclass
        class ClassificationResult:
            selected_frames: List[str]
            suppression_rules: List[Dict[str, Any]]
            frame_priorities: Dict[str, str]
            reasoning: str
            learned_patterns: List[Dict[str, Any]]
            advisories: List[str]

        return ClassificationResult(
            selected_frames=list(all_frames),
            suppression_rules=all_suppression_rules[:100], # Cap it
            frame_priorities=all_priorities,
            reasoning=" | ".join(all_reasoning[:5]) + ("..." if len(all_reasoning) > 5 else ""),
            learned_patterns=[],
            advisories=list(set(all_advisories))[:20] # Cap and dedup
        )

    def _create_default_result(self, frames: List[str]) -> Any:
        from dataclasses import dataclass
        @dataclass
        class ClassificationResult:
            selected_frames: List[str]
            suppression_rules: List[Dict[str, Any]]
            frame_priorities: Dict[str, str]
            reasoning: str
            learned_patterns: List[Dict[str, Any]]
            
        return ClassificationResult(
            selected_frames=frames,
            suppression_rules=[],
            frame_priorities={f: "HIGH" for f in frames},
            reasoning="Default frames (fallback)",
            learned_patterns=[]
        )