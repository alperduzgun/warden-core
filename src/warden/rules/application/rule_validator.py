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
from typing import List, Optional

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
    """

    def __init__(self, rules: List[CustomRule]):
        """Initialize validator with custom rules.

        Args:
            rules: List of custom rules (only enabled rules are kept)
        """
        self.rules = [r for r in rules if r.enabled]
        logger.info("custom_rule_validator_initialized", rule_count=len(self.rules))

    async def validate_file(self, file_path: Path) -> List[CustomRuleViolation]:
        """Validate a file against all active rules.

        Args:
            file_path: Path to the file to validate

        Returns:
            List of rule violations found

        Raises:
            FileNotFoundError: If file does not exist
            ValueError: If file is too large or unreadable
        """
        # Validate file exists
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Check file size (max 10MB)
        if file_path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError(f"File too large: {file_path}")

        # Read file content
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
                lines = content.split("\n")
        except UnicodeDecodeError as e:
            logger.warning(
                "file_decode_error",
                file_path=str(file_path),
                error=str(e),
            )
            raise ValueError(f"Cannot decode file: {file_path}") from e

        violations = []

        for rule in self.rules:
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
