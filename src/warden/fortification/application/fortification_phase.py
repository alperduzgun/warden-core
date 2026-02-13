"""
Fortification Phase with LLM Enhancement.

Generates security fixes and patches for identified vulnerabilities.
Uses LLM to create context-aware, framework-specific solutions.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from warden.fortification.application.prompt_builder import FortificationPromptBuilder
from warden.fortification.domain.models import Fortification
from warden.shared.infrastructure.ignore_matcher import IgnoreMatcher
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile

# Try to import LLMService, use None if not available
try:
    from warden.shared.services import LLMService
except ImportError:
    LLMService = None

logger = get_logger(__name__)


@dataclass
class FortificationResult:
    """Result from fortification phase."""

    fortifications: list[dict[str, Any]]
    applied_fixes: list[dict[str, Any]]
    security_improvements: dict[str, Any]
    confidence: float = 0.0


class FortificationPhase:
    """
    Phase 4: FORTIFICATION - Generate security remediation guidance.

    Responsibilities:
    - Analyze vulnerabilities from validation
    - Generate context-aware remediation suggestions
    - Provide framework-specific code examples
    - Assess fixability (auto-fixable flag for reporting)

    Warden is a Read-Only tool. This phase acts as an AI Tech Lead,
    providing advice but NEVER modifying source code directly.
    """

    # Delegated to FortificationPromptBuilder

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        llm_service: LLMService | None = None,
        semantic_search_service: Any | None = None,
        rate_limiter: Any | None = None,
    ):
        """
        Initialize fortification phase.

        Args:
            config: Phase configuration
            context: Pipeline context from previous phases
            llm_service: Optional LLM service for enhanced fixes
            rate_limiter: Optional rate limiter for LLM calls
        """
        self.config = config or {}
        self.context = context or {}
        self.llm_service = llm_service
        self.semantic_search_service = semantic_search_service
        self.rate_limiter = rate_limiter
        self.use_llm = self.config.get("use_llm", True) and llm_service is not None

        # Initialize IgnoreMatcher
        project_root = getattr(self.context, "project_root", None) or Path.cwd()
        if isinstance(self.context, dict):
            project_root = self.context.get("project_root") or project_root
            use_gitignore = self.context.get("use_gitignore", True)
        else:
            use_gitignore = getattr(self.context, "use_gitignore", True)

        self.ignore_matcher = IgnoreMatcher(Path(project_root), use_gitignore=use_gitignore)

        logger.info(
            "fortification_phase_initialized",
            use_llm=self.use_llm,
            context_keys=list(context.keys()) if context else [],
        )

    async def execute_async(
        self,
        validated_issues: list[dict[str, Any]],
        code_files: list[CodeFile] | None = None,
    ) -> FortificationResult:
        """
        Execute fortification phase.
        """
        # Use debug level for empty runs to reduce CI noise
        log_func = logger.info if validated_issues else logger.debug
        log_func(
            "fortification_phase_started",
            issue_count=len(validated_issues),
            use_llm=self.use_llm,
        )

        # Filter validated issues based on ignore matcher
        normalized_issues = []
        for issue in validated_issues:
            normalized = self._normalize_issue(issue)
            if not self.ignore_matcher.should_ignore_for_frame(Path(normalized.get("file_path", "")), "fortification"):
                normalized_issues.append(normalized)

        if len(validated_issues) > len(normalized_issues):
            logger.info(
                "fortification_phase_issues_ignored",
                ignored=len(validated_issues) - len(normalized_issues),
                remaining=len(normalized_issues),
            )

        validated_issues = normalized_issues

        from warden.fortification.application.orchestrator import FortificationOrchestrator

        orchestrator = FortificationOrchestrator(llm_service=self.llm_service)

        all_fortifications = []
        all_actions = []

        if code_files:
            # Filter files based on ignore matcher
            original_count = len(code_files)
            code_files = [
                cf
                for cf in code_files
                if not self.ignore_matcher.should_ignore_for_frame(Path(cf.path), "fortification")
            ]

            if len(code_files) < original_count:
                logger.info(
                    "fortification_phase_files_ignored",
                    ignored=original_count - len(code_files),
                    remaining=len(code_files),
                )

            for code_file in code_files:
                res = await orchestrator.fortify_async(code_file)
                all_actions.extend(res.actions)
                # Map actions to fortifications for Panel
                for action in res.actions:
                    all_fortifications.append(
                        Fortification(
                            id=f"fort-{len(all_fortifications)}",
                            title=action.type.value.replace("_", " ").title(),
                            detail=action.description,
                            severity=action.severity.lower() if hasattr(action, "severity") else "high",
                            auto_fixable=True,
                            line_number=action.line_number,
                        )
                    )

        # Legacy rule-based/llm fixes for validated issues
        issues_by_type = self._group_issues_by_type(validated_issues)
        for issue_type, issues in issues_by_type.items():
            if self.use_llm:
                fixes = await self._generate_llm_fixes_async(issue_type, issues)
            else:
                fixes = await self._generate_rule_based_fixes_async(issue_type, issues)

            for fix in fixes:
                # Use the finding ID from the fix or the first issue in the group
                fid = fix.get("finding_id")
                if not fid and issues:
                    fid = issues[0].get("id")

                all_fortifications.append(
                    Fortification(
                        id=f"fix-{len(all_fortifications)}",
                        title=fix.get("title", "Security Fix"),
                        detail=fix.get("detail", ""),
                        suggested_code=fix.get("code") or fix.get("suggested_code"),
                        original_code=fix.get("original_code"),
                        file_path=fix.get("file_path"),
                        line_number=fix.get("line_number"),
                        confidence=fix.get("confidence", 0.0),
                        severity=fix.get("severity", "medium"),
                        auto_fixable=fix.get("auto_fixable", False),
                        finding_id=fid,
                    )
                )

        result = FortificationResult(
            fortifications=[f.to_json() if hasattr(f, "to_json") else f for f in all_fortifications],
            applied_fixes=[],
            security_improvements=self._calculate_improvements(validated_issues, all_fortifications)
            if validated_issues
            else {},
        )

        return result

    async def _generate_llm_fixes_async(
        self,
        issue_type: str,
        issues: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Generate fixes using LLM for context-aware solutions.

        Uses semantic search to find similar secure patterns from the project,
        then provides them as context to the LLM for project-style-matching fixes.

        Args:
            issue_type: Type of security issue
            issues: List of issues of this type

        Returns:
            List of fortification suggestions
        """
        fixes = []
        semantic_context = []

        # Step 1: Retrieve semantic context from project
        if self.semantic_search_service and hasattr(self.semantic_search_service, "is_available"):
            try:
                if self.semantic_search_service.is_available():
                    # Get search queries for this issue type
                    queries = FortificationPromptBuilder.ISSUE_SEARCH_QUERIES.get(
                        issue_type.lower(), [f"secure {issue_type} handling", f"safe {issue_type} pattern"]
                    )

                    # Search for similar patterns
                    for query in queries[:2]:  # Limit to 2 queries
                        results = await self.semantic_search_service.search(
                            query=query,
                            language=self.context.get("language", "python"),
                            limit=2,
                        )
                        if results:
                            semantic_context.extend(results)

                    if semantic_context:
                        logger.info(
                            "semantic_context_retrieved",
                            issue_type=issue_type,
                            examples_found=len(semantic_context),
                        )
            except Exception as e:
                logger.warning(
                    "semantic_search_failed_fallback",
                    issue_type=issue_type,
                    error=str(e),
                )
                # Continue without semantic context
                pass

        # Deduplicate and Re-Rank semantic context
        # Ensure we prioritize the highest scoring examples, especially since we merged multiple queries
        if semantic_context:
            # unique by content to avoid dupes
            seen = set()
            unique_context = []
            for item in semantic_context:
                # content attribute or str representation
                content = getattr(item, "content", str(item))
                if content not in seen:
                    seen.add(content)
                    unique_context.append(item)

            # Sort by score descending (if available)
            unique_context.sort(key=lambda x: getattr(x, "score", 0.0), reverse=True)
            semantic_context = unique_context

        # Step 2: Create context-aware prompt with semantic examples
        prompt = FortificationPromptBuilder.create_llm_prompt(issue_type, issues, self.context, semantic_context)

        try:
            # Acquire rate limit if available
            if self.rate_limiter:
                # Estimate tokens: prompt chars / 4 + output limit
                estimated_tokens = (len(prompt) // 4) + 2000
                await self.rate_limiter.acquire_async(estimated_tokens)

            # Determine model tier
            model = None
            llm_cfg = None
            if self.context and hasattr(self.context, "llm_config"):
                llm_cfg = self.context.llm_config
            elif isinstance(self.context, dict):
                llm_cfg = self.context.get("llm_config")

            if llm_cfg:
                if isinstance(llm_cfg, dict):
                    model = llm_cfg.get("smart_model")
                else:
                    model = getattr(llm_cfg, "smart_model", None)

            # Step 3: Get LLM suggestions
            response = await self.llm_service.complete_async(prompt=prompt, model=model)

            if not response:
                logger.warning("llm_security_fix_response_empty", issue_type=issue_type)
                return await self._generate_rule_based_fixes_async(issue_type, issues)

            # Step 4: Parse LLM response into fortifications
            parsed_fixes = FortificationPromptBuilder.parse_llm_response(response.content, issues)
            fixes.extend(parsed_fixes)

            logger.info(
                "llm_fixes_generated",
                issue_type=issue_type,
                fixes_count=len(parsed_fixes),
                used_semantic_context=len(semantic_context) > 0,
            )

        except Exception as e:
            logger.error(
                "llm_fix_generation_failed",
                issue_type=issue_type,
                error=str(e),
            )
            # Fall back to rule-based fixes
            fixes = await self._generate_rule_based_fixes_async(issue_type, issues)

        return fixes

    async def _generate_rule_based_fixes_async(
        self,
        issue_type: str,
        issues: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Generate fixes using predefined rules and templates.

        Args:
            issue_type: Type of security issue
            issues: List of issues of this type

        Returns:
            List of fortification suggestions
        """
        fixes = []

        for issue in issues:
            fix = self._create_fix_for_issue(issue_type, issue)
            if fix:
                fixes.append(fix)

        return fixes

    # Refactored to FortificationPromptBuilder

    def _create_fix_for_issue(
        self,
        issue_type: str,
        issue: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Create rule-based fix for a specific issue.

        Args:
            issue_type: Type of security issue
            issue: Issue details

        Returns:
            Fortification suggestion or None
        """
        # Use machine_context for strategy selection if available
        machine_context = issue.get("machineContext") or issue.get("machine_context")
        if machine_context and isinstance(machine_context, dict):
            suggested = machine_context.get("suggested_fix_type")
            if suggested:
                # Map suggested_fix_type to issue_type for template lookup
                fix_type_map = {
                    "parameterized_query": "sql_injection",
                    "input_validation": "xss",
                    "html_escape": "xss",
                    "env_variable": "hardcoded_secret",
                    "path_sanitization": "path_traversal",
                }
                mapped_type = fix_type_map.get(suggested)
                if mapped_type:
                    issue_type = mapped_type

        fix_templates = {
            "sql_injection": {
                "title": "Use Parameterized Queries",
                "detail": "Replace string concatenation with parameterized queries",
                "code": "cursor.execute_async('SELECT * FROM users WHERE id = ?', (user_id,))",
                "auto_fixable": True,
            },
            "xss": {
                "title": "Escape HTML Output",
                "detail": "Use proper HTML escaping for user input",
                "code": "from html import escape\noutput = escape(user_input)",
                "auto_fixable": True,
            },
            "hardcoded_secret": {
                "title": "Move Secret to Environment Variable",
                "detail": "Replace hardcoded secret with environment variable",
                "code": "import os\nsecret = os.environ.get('SECRET_KEY')",
                "auto_fixable": False,
            },
            "path_traversal": {
                "title": "Validate and Sanitize File Paths",
                "detail": "Use safe path construction to prevent directory traversal",
                "code": "safe_path = os.path.join(base_dir, os.path.basename(user_input))",
                "auto_fixable": True,
            },
            "weak_crypto": {
                "title": "Use Strong Cryptographic Algorithm",
                "detail": "Replace weak algorithm with secure alternative",
                "code": "from cryptography.fernet import Fernet\nkey = Fernet.generate_key()",
                "auto_fixable": False,
            },
        }

        template = fix_templates.get(issue_type.lower())
        if not template:
            return None

        return {
            **template,
            "file_path": issue.get("file_path"),
            "line_number": issue.get("line_number"),
            "severity": issue.get("severity", "medium"),
            "issue_id": issue.get("id"),
            "confidence": 0.7,
        }

    def _normalize_issue(self, issue: Any) -> dict[str, Any]:
        """
        Normalize issue to standard dictionary format.

        Handles:
        - Dictionary objects
        - Finding objects
        - CustomRuleViolation objects (rules/domain/models.py)
        - Legacy objects with file_path/line_number or file/line
        """
        if isinstance(issue, dict):
            return issue

        # Convert object to dict logic
        normalized = {}

        # safely get attributes
        def get_attr(obj, attrs, default=None):
            for attr in attrs:
                if hasattr(obj, attr):
                    return getattr(obj, attr)
            return default

        # ID
        normalized["id"] = get_attr(issue, ["id", "rule_id", "ruleId"], "unknown")

        # File Path
        normalized["file_path"] = get_attr(issue, ["file_path", "file", "path"], "")

        # Line Number
        normalized["line_number"] = get_attr(issue, ["line_number", "line"], 0)

        # Type/Category
        normalized["type"] = get_attr(issue, ["type", "category", "rule_name", "ruleName"], "issue")
        if hasattr(normalized["type"], "value"):  # Handle Enum
            normalized["type"] = normalized["type"].value

        # Severity
        normalized["severity"] = get_attr(issue, ["severity"], "medium")
        if hasattr(normalized["severity"], "value"):  # Handle Enum
            normalized["severity"] = normalized["severity"].value.lower()

        # Message/Description
        normalized["message"] = get_attr(issue, ["message", "description", "detail"], "")

        # Source Object (for specialized fixing if needed)
        # normalized["_source"] = issue

        return normalized

    def _group_issues_by_type(
        self,
        issues: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Group issues by their type for batch processing.

        Args:
            issues: List of all issues

        Returns:
            Dictionary mapping issue type to list of issues
        """
        grouped = {}
        for issue in issues:
            issue_type = issue.get("type", "unknown")
            if issue_type not in grouped:
                grouped[issue_type] = []
            grouped[issue_type].append(issue)

        return grouped

    def _calculate_improvements(
        self,
        issues: list[dict[str, Any]],
        fortifications: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Calculate security improvements from fortifications.

        Args:
            issues: Original issues
            fortifications: Generated fortifications

        Returns:
            Dictionary of security metrics improvements
        """
        # Count issues by severity
        issue_severity_counts = {}
        for issue in issues:
            severity = (
                issue.get("severity", "medium") if isinstance(issue, dict) else getattr(issue, "severity", "medium")
            )
            issue_severity_counts[severity] = issue_severity_counts.get(severity, 0) + 1

        # Count fixes by severity
        fix_severity_counts = {}
        auto_fixable_count = 0
        for fix in fortifications:
            # Use attribute access since these are Fortification objects
            severity = getattr(fix, "severity", "medium")
            fix_severity_counts[severity] = fix_severity_counts.get(severity, 0) + 1
            if getattr(fix, "auto_fixable", False):
                auto_fixable_count += 1

        # Calculate coverage
        coverage = (len(fortifications) / len(issues) * 100) if issues else 0

        return {
            "total_issues": len(issues),
            "total_fixes": len(fortifications),
            "auto_fixable": auto_fixable_count,
            "coverage_percentage": round(coverage, 1),
            "issues_by_severity": issue_severity_counts,
            "fixes_by_severity": fix_severity_counts,
            "critical_coverage": (
                fix_severity_counts.get("critical", 0) / issue_severity_counts.get("critical", 1) * 100
                if issue_severity_counts.get("critical", 0) > 0
                else 100
            ),
        }
