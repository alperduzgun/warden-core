"""
LLM-Enhanced Classification Phase.

Context-aware frame selection and false positive suppression with AI.
"""

import asyncio
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from warden.analysis.application.llm_phase_base import (
    LLMPhaseBase,
    LLMPhaseConfig,
)
from warden.analysis.domain.project_context import Framework, ProjectType
from warden.classification.application.classification_prompts import (
    format_classification_user_prompt,
    get_classification_system_prompt,
)
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

    def __init__(
        self,
        config: LLMPhaseConfig,
        llm_service: Any,
        available_frames: list[Any] = None,
        context: dict[str, Any] = None,
        semantic_search_service: Any = None,
        memory_manager: Any = None,
        rate_limiter: Any = None,
    ) -> None:
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
        super().__init__(
            config, llm_service, project_root=None, memory_manager=memory_manager, rate_limiter=rate_limiter
        )
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

    def format_user_prompt(self, context: dict[str, Any]) -> str:
        """Format user prompt for classification."""
        return format_classification_user_prompt(context)

    def parse_llm_response(self, response: str) -> dict[str, Any]:
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
                result["selected_frames"] = ["security", "resilience", "orphan"]
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
                "selected_frames": ["security", "resilience", "orphan"],
                "suppression_rules": [],
                "priorities": {
                    "security": "CRITICAL",
                    "resilience": "HIGH",
                    "orphan": "MEDIUM",
                },
                "reasoning": "Default frame selection due to parse error",
                "advisories": ["Warning: LLM parsing failed, using default frames."],
            }

    async def classify_batch_async(
        self,
        project_type: ProjectType,
        framework: Framework,
        files: list[str],
        file_contexts: dict[str, dict[str, Any]],
        previous_issues: list[dict[str, Any]] | None = None,
    ) -> dict[str, tuple[list[str], dict[str, Any], float]]:
        """
        Classify multiple files in batch for frame selection.
        """
        results = {}
        if not files:
            return results

        if not self.config.enabled or not self.llm:
            # Fallback for all
            for file_path in files:
                selected_frames = self._rule_based_selection(
                    project_type, framework, {file_path: file_contexts.get(file_path, {})}
                )
                suppression_config = self._default_suppression_config({file_path: file_contexts.get(file_path, {})})
                results[file_path] = (selected_frames, suppression_config, 0.6)
            return results

        # Pre-compute all batches then process in parallel — closes #305
        batch_size = self._get_realtime_safe_batch_size(2)
        batches = [files[i : i + batch_size] for i in range(0, len(files), batch_size)]
        system_prompt = self.get_system_prompt()

        async def _classify_one_batch(batch_files: list[str]) -> dict[str, tuple[list[str], dict[str, Any], float]]:
            batch_result: dict[str, tuple[list[str], dict[str, Any], float]] = {}
            try:
                prompt = self._format_classification_batch_user_prompt(
                    project_type, framework, batch_files, file_contexts, previous_issues
                )
                # In CI+Ollama: fast_clients is empty after factory.py #316 fix,
                # so use_fast_tier=True is a no-op. As defence-in-depth, detect
                # Ollama provider directly and skip fast tier routing.
                _provider_raw = getattr(self.llm, "provider", "")
                _is_ollama = "ollama" in str(_provider_raw).lower()
                response = await self._call_llm_with_retry_async(
                    system_prompt=system_prompt, user_prompt=prompt, use_fast_tier=not _is_ollama
                )
                if not response or not response.content:
                    raise RuntimeError("LLM returned no content after retries")

                llm_data_list = self._parse_classification_batch_response(response.content, len(batch_files))
                for idx, file_path in enumerate(batch_files):
                    llm_data = llm_data_list[idx] if idx < len(llm_data_list) else None
                    if llm_data:
                        selected_frames = [
                            f.lower().replace("frame", "").strip()
                            for f in llm_data.get("selected_frames", ["security", "resilience", "orphan"])
                        ]
                        suppression_config = {
                            "rules": llm_data.get("suppression_rules", []),
                            "priorities": llm_data.get("priorities", {}),
                            "reasoning": llm_data.get("reasoning", ""),
                            "advisories": llm_data.get("advisories", []),
                        }
                        batch_result[file_path] = (selected_frames, suppression_config, 0.85)
                    else:
                        batch_result[file_path] = (
                            self._rule_based_selection(
                                project_type, framework, {file_path: file_contexts.get(file_path, {})}
                            ),
                            self._default_suppression_config({file_path: file_contexts.get(file_path, {})}),
                            0.5,
                        )
            except Exception as e:
                logger.error("batch_classification_failed", error=str(e))
                for file_path in batch_files:
                    batch_result[file_path] = (
                        self._rule_based_selection(
                            project_type, framework, {file_path: file_contexts.get(file_path, {})}
                        ),
                        self._default_suppression_config({file_path: file_contexts.get(file_path, {})}),
                        0.5,
                    )
            return batch_result

        gathered = await asyncio.gather(*[_classify_one_batch(b) for b in batches])
        for batch_result in gathered:
            results.update(batch_result)

        return results

    def _format_classification_batch_user_prompt(
        self, project_type, framework, files, file_contexts, previous_issues
    ) -> str:
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
  "selected_frames": ["security", "resilience", ...],
  "suppression_rules": [...],
  "priorities": {{...}},
  "reasoning": "...",
  "advisories": ["Warn: ...", "Note: ..."]
}}

FILES TO ANALYZE:
{batch_summary}
"""

    def _parse_classification_batch_response(self, response: str, count: int) -> list[dict[str, Any]]:
        try:
            from warden.shared.utils.json_parser import parse_json_from_llm

            result = parse_json_from_llm(response)

            # If the LLM returned a single dict (common when count=1), wrap it
            if isinstance(result, dict):
                result = [result]

            if isinstance(result, list):
                # Ensure all items have an 'idx' field or map them sequentially
                for i, item in enumerate(result):
                    if not isinstance(item, dict):
                        continue
                    if "idx" not in item:
                        item["idx"] = i
                return result

            return []
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            logger.error("batch_classification_parse_error", error=str(e), response=response[:200])
            # LLM response parsing failed - return empty list for graceful degradation
            return []

    async def generate_suppression_rules_async(
        self,
        findings: list[dict[str, Any]],
        file_contexts: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
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

        llm_result = await self.analyze_with_llm_async({"custom_prompt": prompt})

        if llm_result and isinstance(llm_result, list):
            return llm_result

        # Fallback to rule-based suppression
        return self._rule_based_suppression(findings, file_contexts)

    async def learn_from_feedback_async(
        self,
        false_positive_ids: list[str],
        true_positive_ids: list[str],
        findings: list[dict[str, Any]],
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
            "false_positives": [f for f in findings if f.get("id") in false_positive_ids],
            "true_positives": [f for f in findings if f.get("id") in true_positive_ids],
        }

        prompt = f"""Learn from this feedback to improve future classification:

FALSE POSITIVES (should be suppressed):
{json.dumps(context["false_positives"][:10], indent=2)}

TRUE POSITIVES (correctly identified):
{json.dumps(context["true_positives"][:10], indent=2)}

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

            # Persist to disk so next scan can load them
            project_root = getattr(self, "project_root", None) or Path.cwd()
            patterns = self._build_patterns_dict(
                context["false_positives"],
                context["true_positives"],
            )
            self._persist_learned_patterns(patterns, project_root)

            logger.info(
                "classification_learning_complete",
                false_positive_count=len(false_positive_ids),
                true_positive_count=len(true_positive_ids),
            )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_patterns_dict(
        fp_findings: list[dict[str, Any]],
        tp_findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Build a raw patterns dict from categorised finding lists.

        The dict is compatible with the .warden/learned_patterns.yaml schema.
        """
        now = datetime.now(timezone.utc).isoformat()
        patterns: list[dict[str, Any]] = []

        for f in fp_findings:
            rule_id = f.get("id") or f.get("rule_id") or ""
            file_path = f.get("file_path") or f.get("path") or ""
            message = f.get("message") or ""
            patterns.append(
                {
                    "rule_id": rule_id,
                    "file_pattern": str(Path(file_path).name) if file_path else "",
                    "message_pattern": message[:80] if message else "",
                    "type": "false_positive",
                    "occurrence_count": 1,
                    "confidence": 0.5,
                    "first_seen": now,
                    "last_seen": now,
                }
            )

        for f in tp_findings:
            rule_id = f.get("id") or f.get("rule_id") or ""
            file_path = f.get("file_path") or f.get("path") or ""
            message = f.get("message") or ""
            patterns.append(
                {
                    "rule_id": rule_id,
                    "file_pattern": str(Path(file_path).name) if file_path else "",
                    "message_pattern": message[:80] if message else "",
                    "type": "true_positive",
                    "occurrence_count": 1,
                    "confidence": 0.5,
                    "first_seen": now,
                    "last_seen": now,
                }
            )

        return {"version": 1, "patterns": patterns}

    @staticmethod
    def _persist_learned_patterns(
        new_patterns: dict[str, Any],
        project_root: Path,
    ) -> None:
        """
        Merge *new_patterns* into .warden/learned_patterns.yaml on disk.

        Existing patterns with the same (rule_id, file_pattern,
        message_pattern, type) key have their occurrence_count incremented
        and last_seen updated.  New patterns are appended.

        Args:
            new_patterns: Dict with schema {"version": 1, "patterns": [...]}
            project_root: Absolute path to the project root.
        """
        try:
            import yaml
        except ImportError:
            logger.warning("learned_patterns_persist_skipped", reason="pyyaml not installed")
            return

        patterns_file = project_root / ".warden" / "learned_patterns.yaml"
        patterns_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing data
        existing: dict[str, Any] = {"version": 1, "patterns": []}
        if patterns_file.exists():
            try:
                with open(patterns_file) as fh:
                    loaded = yaml.safe_load(fh) or {}
                    existing = loaded if isinstance(loaded, dict) else existing
            except Exception as exc:
                logger.warning("learned_patterns_load_failed", error=str(exc))

        existing_patterns: list[dict[str, Any]] = existing.get("patterns", [])

        now = datetime.now(timezone.utc).isoformat()

        # Build a lookup key for deduplication
        def _key(p: dict[str, Any]) -> tuple:
            return (
                p.get("rule_id", ""),
                p.get("file_pattern", ""),
                p.get("message_pattern", ""),
                p.get("type", ""),
            )

        existing_index: dict[tuple, int] = {
            _key(p): idx for idx, p in enumerate(existing_patterns)
        }

        for new_p in new_patterns.get("patterns", []):
            k = _key(new_p)
            if k in existing_index:
                idx = existing_index[k]
                existing_patterns[idx]["occurrence_count"] = (
                    existing_patterns[idx].get("occurrence_count", 1) + 1
                )
                existing_patterns[idx]["last_seen"] = now
                # Raise confidence: confidence = min(1.0, occurrences / 2)
                occ = existing_patterns[idx]["occurrence_count"]
                existing_patterns[idx]["confidence"] = min(1.0, occ / 2)
            else:
                existing_patterns.append(new_p)
                existing_index[k] = len(existing_patterns) - 1

        existing["patterns"] = existing_patterns

        try:
            with open(patterns_file, "w") as fh:
                yaml.safe_dump(existing, fh, default_flow_style=False, sort_keys=False)
            logger.info(
                "learned_patterns_persisted",
                path=str(patterns_file),
                total_patterns=len(existing_patterns),
            )
        except Exception as exc:
            logger.warning("learned_patterns_write_failed", error=str(exc))

    @staticmethod
    def _load_learned_patterns(project_root: Path) -> list[dict[str, Any]]:
        """
        Load learned patterns from .warden/learned_patterns.yaml.

        Returns an empty list if the file does not exist or cannot be parsed.

        Args:
            project_root: Absolute path to the project root.

        Returns:
            List of pattern dicts as stored in the YAML file.
        """
        try:
            import yaml
        except ImportError:
            return []

        patterns_file = project_root / ".warden" / "learned_patterns.yaml"
        if not patterns_file.exists():
            return []

        try:
            with open(patterns_file) as fh:
                data = yaml.safe_load(fh) or {}
            return data.get("patterns", [])
        except Exception as exc:
            logger.warning("learned_patterns_load_failed", error=str(exc))
            return []

    def _rule_based_selection(
        self,
        project_type: ProjectType,
        framework: Framework,
        file_contexts: dict[str, dict[str, Any]],
    ) -> list[str]:
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
            selected.append("architecture")

        # Add stress for APIs
        if framework in [Framework.FASTAPI, Framework.FLASK, Framework.DJANGO]:
            selected.append("stress")

        return selected

    def _default_suppression_config(
        self,
        file_contexts: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate default suppression configuration."""
        rules = []

        # Count context types
        has_tests = any(fc.get("context") == "TEST" for fc in file_contexts.values())
        has_examples = any(fc.get("context") == "EXAMPLE" for fc in file_contexts.values())

        if has_tests:
            rules.append(
                {
                    "pattern": "test_*.py",
                    "reason": SuppressionReason.TEST_CODE.value,
                    "suppress_types": ["hardcoded_password", "sql_injection"],
                }
            )

        if has_examples:
            rules.append(
                {
                    "pattern": "examples/**",
                    "reason": SuppressionReason.EXAMPLE_CODE.value,
                    "suppress_types": ["all"],
                }
            )

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
        findings: list[dict[str, Any]],
        file_contexts: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Rule-based suppression generation."""
        suppression_rules = []

        for finding in findings:
            file_path = self._get_val(finding, "file_path", "")
            file_context = file_contexts.get(file_path, {})
            context_type = file_context.get("context", "PRODUCTION")

            # Suppress test file vulnerabilities
            if context_type == "TEST" and self._get_val(finding, "type") in [
                "hardcoded_password",
                "sql_injection",
            ]:
                suppression_rules.append(
                    {
                        "finding_id": self._get_val(finding, "id"),
                        "reason": SuppressionReason.TEST_CODE.value,
                        "explanation": "Intentional vulnerability in test file",
                    }
                )

            # Suppress example code issues
            elif context_type == "EXAMPLE":
                suppression_rules.append(
                    {
                        "finding_id": self._get_val(finding, "id"),
                        "reason": SuppressionReason.EXAMPLE_CODE.value,
                        "explanation": "Educational example code",
                    }
                )

        return suppression_rules

    async def execute_async(self, code_files: list[Any]) -> Any:
        """
        Execute LLM-enhanced classification phase with True Batching.
        """
        if not code_files:
            return self._create_default_result(["security", "resilience", "orphan"])

        logger.info("llm_classification_phase_starting_batch", file_count=len(code_files), has_llm=self.llm is not None)

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
                file_contexts[path] = ctx.model_dump(mode="json")
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
            previous_issues=previous_issues,
        )

        if not batch_results:
            return self._create_default_result(["security", "resilience", "orphan"])

        # Aggregate results
        # For frames, we take a UNION of all frames suggested for any file in the project
        all_frames = set()
        all_suppression_rules = []
        all_priorities = {}
        all_reasoning = []
        all_advisories = []

        for file_path, (frames, suppression_config, _confidence) in batch_results.items():
            all_frames.update(frames)
            all_suppression_rules.extend(suppression_config.get("rules", []))
            all_priorities.update(suppression_config.get("priorities", {}))
            if suppression_config.get("reasoning"):
                all_reasoning.append(f"{file_path}: {suppression_config['reasoning']}")
            if suppression_config.get("advisories"):
                all_advisories.extend(suppression_config.get("advisories", []))

        # Ensure we always have some base frames
        if not all_frames:
            all_frames = {"security", "resilience", "orphan"}

        logger.info("llm_batch_classification_complete", frames=list(all_frames), files_analyzed=len(batch_results))

        from dataclasses import dataclass

        @dataclass
        class ClassificationResult:
            selected_frames: list[str]
            suppression_rules: list[dict[str, Any]]
            frame_priorities: dict[str, str]
            reasoning: str
            learned_patterns: list[dict[str, Any]]
            advisories: list[str]

        return ClassificationResult(
            selected_frames=list(all_frames),
            suppression_rules=all_suppression_rules[:100],  # Cap it
            frame_priorities=all_priorities,
            reasoning=" | ".join(all_reasoning[:5]) + ("..." if len(all_reasoning) > 5 else ""),
            learned_patterns=[],
            advisories=list(set(all_advisories))[:20],  # Cap and dedup
        )

    def _create_default_result(self, frames: list[str]) -> Any:
        from dataclasses import dataclass

        @dataclass
        class ClassificationResult:
            selected_frames: list[str]
            suppression_rules: list[dict[str, Any]]
            frame_priorities: dict[str, str]
            reasoning: str
            learned_patterns: list[dict[str, Any]]

        return ClassificationResult(
            selected_frames=frames,
            suppression_rules=[],
            frame_priorities=dict.fromkeys(frames, "HIGH"),
            reasoning="Default frames (fallback)",
            learned_patterns=[],
        )
