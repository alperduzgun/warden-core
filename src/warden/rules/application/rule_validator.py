"""Custom rule validator.

This module implements validation logic for custom project rules.
Validates code against regex patterns and deterministic conditions.
"""

import asyncio
import fnmatch
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from warden.rules.domain.enums import RuleCategory, RuleSeverity
from warden.rules.domain.models import CustomRule, CustomRuleViolation

logger = structlog.get_logger(__name__)

# Default timeout for script execution (30 seconds)
DEFAULT_SCRIPT_TIMEOUT = 30


class CustomRuleValidator:
    """Validates code against custom project rules.

    This validator applies deterministic, pattern-based validation rules
    to code files. Unlike AI-powered frames, rules use regex patterns
    and explicit conditions to enforce project-specific policies.

    Attributes:
        rules: List of active custom rules to validate against
        llm_service: Optional LLM service for AI-powered validation
    """

    def __init__(self, rules: List[CustomRule], llm_service: Optional[Any] = None):
        """Initialize validator with custom rules.

        Args:
            rules: List of custom rules (only enabled rules are kept)
            llm_service: Optional LLM service instance
        """
        self.rules = [r for r in rules if r.enabled]
        self.llm_service = llm_service
        logger.info("custom_rule_validator_initialized", rule_count=len(self.rules), has_llm=llm_service is not None)

    async def validate_file_async(
        self, 
        file_path: Path | str, 
        rules: Optional[List[CustomRule]] = None
    ) -> List[CustomRuleViolation]:
        """Validate a file against rules.

        Args:
            file_path: Path to the file to validate
            rules: Optional list of rules to validate against (overrides global rules)

        Returns:
            List of rule violations found
        """
        # Support both Path and str
        if isinstance(file_path, str):
            file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Use passed rules or fallback to global rules
        active_rules = rules if rules is not None else self.rules
        
        if not active_rules:
            return []

        # Read file content
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.split("\n")
        except Exception as e:
            logger.error("file_read_error", file=str(file_path), error=str(e))
            return []

        violations = []

        for rule in active_rules:
            logger.debug("processing_rule", rule_id=rule.id, rule_type=rule.type)
            # Check language filter
            if rule.language and not self._is_language_match(file_path, rule.language):
                continue

            # Check exceptions
            if rule.exceptions and self._is_exception_match(file_path, rule.exceptions):
                continue

            # Validate based on rule type
            if rule.type == "security":
                violations.extend(
                    self._validate_security_rule(rule, file_path, lines, content)
                )
            elif rule.type == "convention":
                violations.extend(
                    self._validate_convention_rule(rule, file_path, lines, content)
                )
            elif rule.type == "script":
                violation = await self._validate_script(rule, file_path)
                if violation:
                    violations.append(violation)
            elif rule.type == "ai":
                if self.llm_service:
                    ai_violations = await self._validate_ai_rule(rule, file_path, content)
                    violations.extend(ai_violations)
                else:
                    logger.warning("ai_rule_skipped_no_llm", rule_id=rule.id)

        logger.info(
            "file_validation_complete",
            file_path=str(file_path),
            violation_count=len(violations),
        )

        return violations

    def _is_language_match(self, file_path: Path, languages: List[str]) -> bool:
        """Check if file matches language filter.

        Args:
            file_path: File to check
            languages: List of allowed languages

        Returns:
            True if file matches any of the languages
        """
        suffix = file_path.suffix.lower().lstrip(".")
        language_map = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "cs": "csharp",
            "java": "java",
            "go": "go",
            "rs": "rust",
            "rb": "ruby",
            "php": "php",
        }

        file_language = language_map.get(suffix)
        return file_language in [lang.lower() for lang in languages] if file_language else False

    def _is_exception_match(self, file_path: Path, exceptions: List[str]) -> bool:
        """Check if file matches exception pattern.

        Args:
            file_path: File to check
            exceptions: List of exception patterns (glob-style)

        Returns:
            True if file matches any exception pattern
        """
        file_str = str(file_path)
        for pattern in exceptions:
            # Use fnmatch for proper glob matching (handles *, ?, [], etc.)
            if fnmatch.fnmatch(file_str, pattern):
                return True
        return False

    def _validate_security_rule(
        self,
        rule: CustomRule,
        file_path: Path,
        lines: List[str],
        content: str,
    ) -> List[CustomRuleViolation]:
        """Validate security rules (secrets, connections, git).

        Args:
            rule: Security rule to validate
            file_path: File being validated
            lines: File content split into lines
            content: Full file content

        Returns:
            List of violations found
        """
        violations = []
        conditions = rule.conditions

        # Secrets detection
        if "secrets" in conditions:
            violations.extend(
                self._validate_secrets_condition(rule, file_path, lines, conditions["secrets"])
            )

        # Git authorship rules
        if "git" in conditions:
            # TODO: Git validation requires git history, not file content
            # Should be implemented in a separate validate_project() method that:
            # 1. Runs once per pipeline (not per file)
            # 2. Uses subprocess to run: git log --format=%ae -n 100
            # 3. Checks author emails against blacklist
            # 4. Returns CustomRuleViolation with project-level context
            # See: RULES_SYSTEM_EXPLAINED.md, SORUN 3
            logger.warning(
                "git_validation_not_implemented",
                rule_id=rule.id,
                rule_name=rule.name,
                message="Git validation skipped - requires project-level implementation"
            )
            pass

        # Connection string rules
        if "connections" in conditions:
            violations.extend(
                self._validate_connections_condition(rule, file_path, lines, conditions["connections"])
            )

        return violations

    def _validate_secrets_condition(
        self,
        rule: CustomRule,
        file_path: Path,
        lines: List[str],
        condition: dict,
    ) -> List[CustomRuleViolation]:
        """Validate secrets detection condition.

        Args:
            rule: Rule being validated
            file_path: File being validated
            lines: File content lines
            condition: Secrets condition configuration

        Returns:
            List of violations found
        """
        violations = []
        patterns = condition.get("patterns", [])

        for pattern in patterns:
            for i, line in enumerate(lines, start=1):
                if re.search(pattern, line):
                    violations.append(
                        CustomRuleViolation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            category=rule.category,
                            severity=rule.severity,
                            is_blocker=rule.is_blocker,
                            file=str(file_path),
                            line=i,
                            message=rule.message or f"Potential secret detected: {rule.name}",
                            code_snippet=line.strip(),
                        )
                    )

        return violations

    def _validate_connections_condition(
        self,
        rule: CustomRule,
        file_path: Path,
        lines: List[str],
        condition: dict,
    ) -> List[CustomRuleViolation]:
        """Validate connection string condition.

        Args:
            rule: Rule being validated
            file_path: File being validated
            lines: File content lines
            condition: Connections condition configuration

        Returns:
            List of violations found
        """
        violations = []
        forbidden_patterns = condition.get("forbiddenPatterns", [])

        for pattern in forbidden_patterns:
            for i, line in enumerate(lines, start=1):
                if re.search(pattern, line):
                    violations.append(
                        CustomRuleViolation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            category=rule.category,
                            severity=rule.severity,
                            is_blocker=rule.is_blocker,
                            file=str(file_path),
                            line=i,
                            message=rule.message or f"Forbidden connection pattern: {rule.name}",
                            code_snippet=line.strip(),
                        )
                    )

        return violations

    def _validate_convention_rule(
        self,
        rule: CustomRule,
        file_path: Path,
        lines: List[str],
        content: str,
    ) -> List[CustomRuleViolation]:
        """Validate convention rules (redis, api, naming).

        Args:
            rule: Convention rule to validate
            file_path: File being validated
            lines: File content split into lines
            content: Full file content

        Returns:
            List of violations found
        """
        violations = []
        conditions = rule.conditions

        # Redis key pattern validation
        if "redis" in conditions:
            violations.extend(
                self._validate_redis_condition(rule, file_path, lines, conditions["redis"])
            )

        # API route pattern validation
        if "api" in conditions:
            violations.extend(
                self._validate_api_condition(rule, file_path, lines, conditions["api"])
            )

        # Naming convention validation
        if "naming" in conditions:
            violations.extend(
                self._validate_naming_condition(rule, file_path, lines, conditions["naming"])
            )

        return violations

    def _validate_redis_condition(
        self,
        rule: CustomRule,
        file_path: Path,
        lines: List[str],
        condition: dict,
    ) -> List[CustomRuleViolation]:
        """Validate Redis key pattern condition.

        Args:
            rule: Rule being validated
            file_path: File being validated
            lines: File content lines
            condition: Redis condition configuration

        Returns:
            List of violations found
        """
        violations = []
        key_pattern = condition.get("keyPattern")

        if key_pattern:
            # TODO: Improve Redis operation patterns (currently too specific)
            # Should support more generic patterns or make configurable via YAML
            # Current patterns may miss different Redis client APIs
            # See: RULES_SYSTEM_EXPLAINED.md, SORUN 5

            # Look for Redis set/get operations
            redis_operations = [
                r'\.set\s*\(\s*["\']([^"\']+)["\']',
                r'\.get\s*\(\s*["\']([^"\']+)["\']',
                r'cache\.set\s*\(\s*["\']([^"\']+)["\']',
            ]

            for operation_pattern in redis_operations:
                for i, line in enumerate(lines, start=1):
                    match = re.search(operation_pattern, line)
                    if match:
                        key = match.group(1)
                        if not re.match(key_pattern, key):
                            violations.append(
                                CustomRuleViolation(
                                    rule_id=rule.id,
                                    rule_name=rule.name,
                                    category=rule.category,
                                    severity=rule.severity,
                                    is_blocker=rule.is_blocker,
                                    file=str(file_path),
                                    line=i,
                                    message=rule.message or f"Redis key '{key}' does not match pattern: {key_pattern}",
                                    code_snippet=line.strip(),
                                    suggestion=f"Redis keys must match pattern: {key_pattern}",
                                )
                            )

        return violations

    def _validate_api_condition(
        self,
        rule: CustomRule,
        file_path: Path,
        lines: List[str],
        condition: dict,
    ) -> List[CustomRuleViolation]:
        """Validate API route pattern condition.

        Args:
            rule: Rule being validated
            file_path: File being validated
            lines: File content lines
            condition: API condition configuration

        Returns:
            List of violations found
        """
        violations = []
        route_pattern = condition.get("routePattern")

        if route_pattern:
            # TODO: Improve route group extraction (currently fragile)
            # Should use (pattern, group_index) tuples for clarity
            # See: RULES_SYSTEM_EXPLAINED.md, SORUN 2

            # Look for API route definitions
            route_definitions = [
                r'@app\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
                r'@router\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
                r'Route\s*\(\s*["\']([^"\']+)["\']',
            ]

            for route_def_pattern in route_definitions:
                for i, line in enumerate(lines, start=1):
                    match = re.search(route_def_pattern, line)
                    if match:
                        route = match.group(2) if match.lastindex >= 2 else match.group(1)
                        if not re.match(route_pattern, route):
                            violations.append(
                                CustomRuleViolation(
                                    rule_id=rule.id,
                                    rule_name=rule.name,
                                    category=rule.category,
                                    severity=rule.severity,
                                    is_blocker=rule.is_blocker,
                                    file=str(file_path),
                                    line=i,
                                    message=rule.message or f"API route '{route}' does not match pattern: {route_pattern}",
                                    code_snippet=line.strip(),
                                    suggestion=f"API routes must match pattern: {route_pattern}",
                                )
                            )

        return violations

    def _validate_naming_condition(
        self,
        rule: CustomRule,
        file_path: Path,
        lines: List[str],
        condition: dict,
    ) -> List[CustomRuleViolation]:
        """Validate naming convention condition.

        Args:
            rule: Rule being validated
            file_path: File being validated
            lines: File content lines
            condition: Naming condition configuration

        Returns:
            List of violations found
        """
        violations = []
        async_suffix = condition.get("asyncMethodSuffix")

        if async_suffix:
            # TODO: Language-specific async patterns (currently Python-only)
            # Should detect file language and use appropriate pattern:
            # - Python: r'async\s+def\s+(\w+)\s*\('
            # - C#: r'async\s+\w+\s+(\w+)\s*\('
            # - JavaScript/TypeScript: r'async\s+(?:function\s+)?(\w+)\s*\('
            # See: RULES_SYSTEM_EXPLAINED.md, SORUN 1

            # Look for async methods without proper suffix (Python only for now)
            async_pattern = r'async\s+def\s+(\w+)\s*\('

            for i, line in enumerate(lines, start=1):
                match = re.search(async_pattern, line)
                if match:
                    method_name = match.group(1)
                    if not method_name.endswith(async_suffix):
                        violations.append(
                            CustomRuleViolation(
                                rule_id=rule.id,
                                rule_name=rule.name,
                                category=rule.category,
                                severity=rule.severity,
                                is_blocker=rule.is_blocker,
                                file=str(file_path),
                                line=i,
                                message=rule.message or f"Async method '{method_name}' must end with '{async_suffix}'",
                                code_snippet=line.strip(),
                                suggestion=f"Rename to '{method_name}{async_suffix}'",
                            )
                        )

        return violations

    async def _validate_script(
        self,
        rule: CustomRule,
        file_path: Path,
    ) -> Optional[CustomRuleViolation]:
        """Execute external script for validation.

        Script contract:
            - Input: file_path as argument
            - Exit code: 0 = pass, non-zero = violation
            - Stdout: Violation message (if failed)

        Example:
            ./scripts/check_size.sh /path/to/file.py
            # Exit 1 if file > 10MB
            # Echo "File too large: 15MB"

        Args:
            rule: Rule with script configuration
            file_path: File being validated

        Returns:
            CustomRuleViolation if script fails, None if passes or error

        Raises:
            ValueError: If script_path is missing or invalid
        """
        # Validate script_path is provided
        if not rule.script_path:
            logger.error(
                "script_path_missing",
                rule_id=rule.id,
                rule_name=rule.name,
            )
            raise ValueError(f"Rule '{rule.id}' has type='script' but no script_path")

        # Resolve script path (support relative paths from project root)
        script_path = Path(rule.script_path)
        if not script_path.is_absolute():
            # Resolve relative to current working directory
            script_path = Path.cwd() / script_path

        # Security check: Validate script path (prevent path traversal)
        try:
            script_path = script_path.resolve()
        except (OSError, RuntimeError) as e:
            logger.error(
                "script_path_resolution_failed",
                rule_id=rule.id,
                script_path=rule.script_path,
                error=str(e),
            )
            return None

        # Check if script exists
        if not script_path.exists():
            logger.error(
                "script_not_found",
                rule_id=rule.id,
                script_path=str(script_path),
            )
            return None

        # Check if script is a file (not directory)
        if not script_path.is_file():
            logger.error(
                "script_not_file",
                rule_id=rule.id,
                script_path=str(script_path),
            )
            return None

        # Check if script is executable
        if not os.access(script_path, os.X_OK):
            logger.error(
                "script_not_executable",
                rule_id=rule.id,
                script_path=str(script_path),
            )
            return None

        # Get timeout (use rule timeout or default)
        timeout = rule.timeout if rule.timeout else DEFAULT_SCRIPT_TIMEOUT

        # Log script execution start
        start_time = time.time()
        logger.info(
            "script_execution_start",
            rule_id=rule.id,
            rule_name=rule.name,
            script_path=str(script_path),
            file_path=str(file_path),
            timeout=timeout,
        )

        try:
            # Execute script with timeout (use list args for security)
            process = await asyncio.create_subprocess_exec(
                str(script_path),
                str(file_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Wait for process with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                # Kill process on timeout
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass

                duration = time.time() - start_time
                logger.error(
                    "script_execution_timeout",
                    rule_id=rule.id,
                    rule_name=rule.name,
                    script_path=str(script_path),
                    file_path=str(file_path),
                    timeout=timeout,
                    duration=duration,
                )
                return None

            # Calculate duration
            duration = time.time() - start_time

            # Get exit code
            exit_code = process.returncode

            # Decode output
            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()

            # Log script execution complete
            logger.info(
                "script_execution_complete",
                rule_id=rule.id,
                rule_name=rule.name,
                script_path=str(script_path),
                file_path=str(file_path),
                exit_code=exit_code,
                duration=duration,
                stdout_length=len(stdout_text),
                stderr_length=len(stderr_text),
            )

            # If exit code is 0, no violation
            if exit_code == 0:
                return None

            # Create violation with stdout as message
            violation_message = stdout_text if stdout_text else (
                rule.message or f"Script validation failed: {rule.name}"
            )

            # If stderr has content, log it as additional context
            if stderr_text:
                logger.warning(
                    "script_stderr_output",
                    rule_id=rule.id,
                    script_path=str(script_path),
                    stderr=stderr_text,
                )

            return CustomRuleViolation(
                rule_id=rule.id,
                rule_name=rule.name,
                category=rule.category,
                severity=rule.severity,
                is_blocker=rule.is_blocker,
                file=str(file_path),
                line=1,  # Scripts don't have line numbers
                message=violation_message,
                suggestion=None,
                code_snippet=None,
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                "script_execution_error",
                rule_id=rule.id,
                rule_name=rule.name,
                script_path=str(script_path),
                file_path=str(file_path),
                error=str(e),
                error_type=type(e).__name__,
                duration=duration,
            )
            return None

    async def _validate_ai_rule(
        self,
        rule: CustomRule,
        file_path: Path,
        content: str,
    ) -> List[CustomRuleViolation]:
        """Validate code using LLM as a pure AI rule.

        Args:
            rule: AI rule to validate
            file_path: File being validated
            content: File content

        Returns:
            List of violations found
        """
        if not self.llm_service:
            return []

        # Prepare prompt for LLM
        prompt = f"""
You are a Senior Code Auditor. Your task is to audit the following code against a specific PROJECT RULE.

PROJECT RULE:
- ID: {rule.id}
- Name: {rule.name}
- Directive: {rule.description}
- Severity: {rule.severity.value if hasattr(rule.severity, 'value') else rule.severity}

CODE TO AUDIT ({file_path.name}):
```
{content[:10000]}  # Limit content size for LLM
```

INSTRUCTIONS:
1. Does the code violate the PROJECT RULE?
2. If yes, explain exactly WHY and where in the code (provide line numbers if possible).
3. If no violation is found, return as clean.

RETURN ONLY A JSON OBJECT:
{{
    "violation_found": boolean,
    "line_number": integer (0 if multiple or unknown),
    "explanation": "Short explanation",
    "suggestion": "How to fix it"
}}
"""
        try:
            # Call LLM service (assuming complete_async interface)
            logger.debug("executing_ai_rule", rule_id=rule.id, file=str(file_path))
            response = await self.llm_service.complete_async(prompt, "You are a specialized code validation agent.")
            logger.debug("ai_rule_response_received", rule_id=rule.id)
            
            # Parse JSON response
            from warden.shared.utils.json_parser import parse_json_from_llm
            result = parse_json_from_llm(response.content if hasattr(response, 'content') else str(response))
            
            if result.get("violation_found"):
                logger.info("ai_rule_violation_found", rule_id=rule.id, file=str(file_path), explanation=result.get("explanation"))
                return [
                    CustomRuleViolation(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        category=rule.category,
                        severity=rule.severity,
                        is_blocker=rule.is_blocker,
                        file=str(file_path),
                        line=result.get("line_number", 1),
                        message=rule.message.format(reason=result.get("explanation")) if rule.message and "{reason}" in rule.message else (result.get("explanation") or f"AI violation: {rule.name}"),
                        suggestion=result.get("suggestion"),
                        code_snippet=None, # AI doesn't always provide snippets
                    )
                ]
            
            return []

        except Exception as e:
            logger.error("ai_rule_execution_failed", rule_id=rule.id, error=str(e))
            return []
