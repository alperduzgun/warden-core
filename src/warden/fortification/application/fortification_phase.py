"""
Fortification Phase with LLM Enhancement.

Generates security fixes and patches for identified vulnerabilities.
Uses LLM to create context-aware, framework-specific solutions.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile
from warden.fortification.domain.models import Fortification
from warden.shared.infrastructure.ignore_matcher import IgnoreMatcher

# Try to import LLMService, use None if not available
try:
    from warden.shared.services import LLMService
except ImportError:
    LLMService = None

logger = get_logger(__name__)


@dataclass
class FortificationResult:
    """Result from fortification phase."""

    fortifications: List[Dict[str, Any]]
    applied_fixes: List[Dict[str, Any]]
    security_improvements: Dict[str, Any]
    confidence: float = 0.0


class FortificationPhase:
    """
    Phase 4: FORTIFICATION - Generate security fixes.

    Responsibilities:
    - Analyze vulnerabilities from validation
    - Generate context-aware fixes
    - Provide framework-specific solutions
    - Create auto-applicable patches
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        llm_service: Optional[LLMService] = None,
        semantic_search_service: Optional[Any] = None,
    ):
        """
        Initialize fortification phase.

        Args:
            config: Phase configuration
            context: Pipeline context from previous phases
            llm_service: Optional LLM service for enhanced fixes
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

        logger.info(
            "fortification_phase_initialized",
            use_llm=self.use_llm,
            context_keys=list(context.keys()) if context else [],
        )

    async def execute_async(
        self,
        validated_issues: List[Dict[str, Any]],
        code_files: Optional[List[CodeFile]] = None,
    ) -> FortificationResult:
        """
        Execute fortification phase.
        """
        logger.info(
            "fortification_phase_started",
            issue_count=len(validated_issues),
            use_llm=self.use_llm,
        )

        # Filter validated issues based on ignore matcher
        original_issue_count = len(validated_issues)
        validated_issues = [
            issue for issue in validated_issues
            if not self.ignore_matcher.should_ignore_for_frame(Path(issue.get("file_path", "")), "fortification")
        ]
        
        if len(validated_issues) < original_issue_count:
             logger.info(
                "fortification_phase_issues_ignored",
                ignored=original_issue_count - len(validated_issues),
                remaining=len(validated_issues)
            )

        from warden.fortification.application.orchestrator import FortificationOrchestrator
        orchestrator = FortificationOrchestrator()

        all_fortifications = []
        all_actions = []

        if code_files:
            # Filter files based on ignore matcher
            original_count = len(code_files)
            code_files = [
                cf for cf in code_files 
                if not self.ignore_matcher.should_ignore_for_frame(Path(cf.path), "fortification")
            ]
            
            if len(code_files) < original_count:
                logger.info(
                    "fortification_phase_files_ignored",
                    ignored=original_count - len(code_files),
                    remaining=len(code_files)
                )

            for code_file in code_files:
                res = await orchestrator.fortify_async(code_file)
                all_actions.extend(res.actions)
                # Map actions to fortifications for Panel
                for action in res.actions:
                    all_fortifications.append(Fortification(
                        id=f"fort-{len(all_fortifications)}",
                        title=action.type.value.replace("_", " ").title(),
                        detail=action.description
                    ))

        # Legacy rule-based/llm fixes for validated issues
        issues_by_type = self._group_issues_by_type(validated_issues)
        for issue_type, issues in issues_by_type.items():
            if self.use_llm:
                fixes = await self._generate_llm_fixes_async(issue_type, issues)
            else:
                fixes = await self._generate_rule_based_fixes_async(issue_type, issues)
            
            for fix in fixes:
                all_fortifications.append(Fortification(
                    id=f"fix-{len(all_fortifications)}",
                    title=fix.get("title", "Security Fix"),
                    detail=fix.get("detail", "")
                ))

        result = FortificationResult(
            fortifications=[f.to_json() if hasattr(f, 'to_json') else f for f in all_fortifications],
            applied_fixes=[],
            security_improvements=self._calculate_improvements(validated_issues, all_fortifications) if validated_issues else {},
        )

        return result


    async def _generate_llm_fixes_async(
        self,
        issue_type: str,
        issues: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Generate fixes using LLM for context-aware solutions.

        Args:
            issue_type: Type of security issue
            issues: List of issues of this type

        Returns:
            List of fortification suggestions
        """
        fixes = []

        # Create context-aware prompt
        prompt = self._create_llm_prompt(issue_type, issues)

        try:
            # Get LLM suggestions
            response = await self.llm_service.complete_async(
                prompt=prompt,
                temperature=0.3,  # Lower temperature for consistent fixes
                max_tokens=2000,
            )

            # Parse LLM response into fortifications
            parsed_fixes = self._parse_llm_response(response, issues)
            fixes.extend(parsed_fixes)

            logger.info(
                "llm_fixes_generated",
                issue_type=issue_type,
                fixes_count=len(parsed_fixes),
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
        issues: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
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

    def _create_llm_prompt(
        self,
        issue_type: str,
        issues: List[Dict[str, Any]],
    ) -> str:
        """
        Create LLM prompt for fix generation.

        Args:
            issue_type: Type of security issue
            issues: List of issues

        Returns:
            Formatted prompt for LLM
        """
        # Get context information
        project_type = self.context.get("project_type", "unknown")
        framework = self.context.get("framework", "unknown")
        language = self.context.get("language", "python")

        # Format issues for prompt
        issue_details = []
        for issue in issues[:5]:  # Limit to 5 examples
            issue_details.append(
                f"- File: {issue.get('file_path', 'unknown')}\n"
                f"  Line: {issue.get('line_number', 'unknown')}\n"
                f"  Code: {issue.get('code_snippet', 'N/A')[:100]}"
            )

        prompt = f"""
        You are a security expert fixing {issue_type} vulnerabilities.

        PROJECT CONTEXT:
        - Type: {project_type}
        - Framework: {framework}
        - Language: {language}

        ISSUES FOUND ({len(issues)} total):
        {chr(10).join(issue_details)}

        Generate secure fixes for these {issue_type} vulnerabilities.
        For each fix, provide:
        1. Title: Clear description of the fix
        2. Detail: Explanation of what the fix does
        3. Code: The actual fix code
        4. Auto-fixable: Whether this can be automatically applied (true/false)

        Format your response as JSON array of fixes.
        Focus on framework-specific best practices for {framework}.
        """

        return prompt

    def _parse_llm_response(
        self,
        response: str,
        issues: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Parse LLM response into fortification objects.

        Args:
            response: LLM response text
            issues: Original issues

        Returns:
            List of parsed fortifications
        """
        import json
        import re

        fortifications = []

        try:
            # Try to extract JSON from response
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                fixes_data = json.loads(json_match.group())

                for fix_data in fixes_data:
                    fortification = {
                        "title": fix_data.get("title", "Security Fix"),
                        "detail": fix_data.get("detail", ""),
                        "code": fix_data.get("code", ""),
                        "auto_fixable": fix_data.get("auto_fixable", False),
                        "severity": issues[0].get("severity", "high") if issues else "medium",
                        "issue_type": issues[0].get("type", "security") if issues else "unknown",
                        "confidence": 0.85,
                    }
                    fortifications.append(fortification)

        except (json.JSONDecodeError, AttributeError) as e:
            logger.error("llm_response_parsing_failed", error=str(e))

            # Create basic fortification from response
            fortification = {
                "title": f"Fix for {issues[0].get('type', 'issue')}",
                "detail": response[:500],  # First 500 chars as detail
                "code": "",
                "auto_fixable": False,
                "severity": issues[0].get("severity", "medium") if issues else "medium",
                "confidence": 0.5,
            }
            fortifications.append(fortification)

        return fortifications

    def _create_fix_for_issue(
        self,
        issue_type: str,
        issue: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Create rule-based fix for a specific issue.

        Args:
            issue_type: Type of security issue
            issue: Issue details

        Returns:
            Fortification suggestion or None
        """
        fix_templates = {
            "sql_injection": {
                "title": "Use Parameterized Queries",
                "detail": "Replace string concatenation with parameterized queries",
                "code": "cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))",
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

    def _group_issues_by_type(
        self,
        issues: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
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
        issues: List[Dict[str, Any]],
        fortifications: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
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
            severity = issue.get("severity", "medium")
            issue_severity_counts[severity] = issue_severity_counts.get(severity, 0) + 1

        # Count fixes by severity
        fix_severity_counts = {}
        auto_fixable_count = 0
        for fix in fortifications:
            severity = fix.get("severity", "medium")
            fix_severity_counts[severity] = fix_severity_counts.get(severity, 0) + 1
            if fix.get("auto_fixable", False):
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
                fix_severity_counts.get("critical", 0) /
                issue_severity_counts.get("critical", 1) * 100
                if issue_severity_counts.get("critical", 0) > 0
                else 100
            ),
        }