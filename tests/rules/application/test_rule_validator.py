"""Tests for rule validator."""

import asyncio
import os
import pytest
from pathlib import Path
import tempfile
import stat

from warden.rules.domain.enums import RuleCategory, RuleSeverity
from warden.rules.domain.models import CustomRule
from warden.rules.application.rule_validator import CustomRuleValidator


class TestCustomRuleValidator:
    """Test CustomRuleValidator."""

    def test_validator_filters_disabled_rules(self):
        """Test validator only keeps enabled rules."""
        rules = [
            CustomRule(
                id="rule1",
                name="Rule 1",
                category=RuleCategory.SECURITY,
                severity=RuleSeverity.CRITICAL,
                is_blocker=True,
                description="Test",
                enabled=True,
                type="security",
                conditions={},
            ),
            CustomRule(
                id="rule2",
                name="Rule 2",
                category=RuleCategory.SECURITY,
                severity=RuleSeverity.CRITICAL,
                is_blocker=True,
                description="Test",
                enabled=False,
                type="security",
                conditions={},
            ),
        ]

        validator = CustomRuleValidator(rules)
        assert len(validator.rules) == 1
        assert validator.rules[0].id == "rule1"

    @pytest.mark.asyncio
    async def test_validate_secrets_rule(self):
        """Test secrets detection rule."""
        rule = CustomRule(
            id="no-secrets",
            name="No Hardcoded Secrets",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            is_blocker=True,
            description="Prevent hardcoded secrets",
            enabled=True,
            type="security",
            conditions={
                "secrets": {
                    "patterns": [
                        r"api[_-]?key\s*=\s*[\"'][^\"']+[\"']",
                        r"password\s*=\s*[\"'][^\"']+[\"']",
                    ]
                }
            },
        )

        validator = CustomRuleValidator([rule])

        # Create temp file with secret
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('api_key = "sk-1234567890"\n')
            f.write('password = "MyPassword123"\n')
            f.write('user = "john"\n')
            temp_path = Path(f.name)

        try:
            violations = await validator.validate_file(temp_path)

            assert len(violations) == 2
            assert violations[0].rule_id == "no-secrets"
            assert violations[0].line == 1
            assert "api_key" in violations[0].code_snippet
            assert violations[1].line == 2
            assert "password" in violations[1].code_snippet
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_validate_redis_key_pattern(self):
        """Test Redis key pattern validation."""
        rule = CustomRule(
            id="redis-key-format",
            name="Redis Key Format",
            category=RuleCategory.CONVENTION,
            severity=RuleSeverity.HIGH,
            is_blocker=False,
            description="Redis keys must follow env:module:key format",
            enabled=True,
            type="convention",
            conditions={
                "redis": {
                    "keyPattern": r"^(dev|staging|prod):[a-z_]+:[a-z0-9_-]+$"
                }
            },
        )

        validator = CustomRuleValidator([rule])

        # Create temp file with Redis operations
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('cache.set("user123", data)  # Invalid\n')
            f.write('cache.set("prod:users:user_123", data)  # Valid\n')
            f.write('cache.get("INVALID_KEY")  # Invalid\n')
            temp_path = Path(f.name)

        try:
            violations = await validator.validate_file(temp_path)

            assert len(violations) == 2
            assert violations[0].line == 1
            assert "user123" in violations[0].message
            assert violations[1].line == 3
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_validate_api_versioning(self):
        """Test API versioning rule."""
        rule = CustomRule(
            id="api-versioning",
            name="API Versioning Required",
            category=RuleCategory.CONVENTION,
            severity=RuleSeverity.HIGH,
            is_blocker=True,
            description="API endpoints must include version",
            enabled=True,
            type="convention",
            conditions={
                "api": {
                    "routePattern": r"^/v[0-9]+/"
                }
            },
        )

        validator = CustomRuleValidator([rule])

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('@app.get("/users")  # Invalid\n')
            f.write('@app.post("/v1/users")  # Valid\n')
            f.write('@router.put("/payment")  # Invalid\n')
            temp_path = Path(f.name)

        try:
            violations = await validator.validate_file(temp_path)

            assert len(violations) == 2
            assert "/users" in violations[0].message
            assert "/payment" in violations[1].message
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_language_filter(self):
        """Test language filtering."""
        rule = CustomRule(
            id="test-rule",
            name="Test Rule",
            category=RuleCategory.CONVENTION,
            severity=RuleSeverity.MEDIUM,
            is_blocker=False,
            description="Test",
            enabled=True,
            type="convention",
            conditions={"secrets": {"patterns": ["test"]}},
            language=["python"],
        )

        validator = CustomRuleValidator([rule])

        # Python file should match
        py_file = Path("test.py")
        assert validator._is_language_match(py_file, ["python"]) is True

        # JS file should not match
        js_file = Path("test.js")
        assert validator._is_language_match(js_file, ["python"]) is False

    @pytest.mark.asyncio
    async def test_exception_pattern(self):
        """Test exception pattern matching."""
        rule = CustomRule(
            id="test-rule",
            name="Test Rule",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            is_blocker=True,
            description="Test",
            enabled=True,
            type="security",
            conditions={"secrets": {"patterns": [r"secret"]}},
            exceptions=["*.test.py", "*_test.py"],
        )

        validator = CustomRuleValidator([rule])

        # Create test file (should be excluded)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".test.py", delete=False) as f:
            f.write('secret = "value"\n')
            temp_path = Path(f.name)

        try:
            violations = await validator.validate_file(temp_path)
            # Should be 0 because test files are excluded
            assert len(violations) == 0
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_script_validation_pass(self):
        """Test script validation that passes."""
        # Create a simple script that always passes (exit 0)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as script_file:
            script_file.write("#!/bin/bash\n")
            script_file.write("# Script always passes\n")
            script_file.write("exit 0\n")
            script_path = Path(script_file.name)

        # Make script executable
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

        # Create test file to validate
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as test_file:
            test_file.write("# Test file\n")
            test_file_path = Path(test_file.name)

        try:
            rule = CustomRule(
                id="script-test",
                name="Script Test",
                category=RuleCategory.CUSTOM,
                severity=RuleSeverity.MEDIUM,
                is_blocker=False,
                description="Test script validation",
                enabled=True,
                type="script",
                conditions={},
                script_path=str(script_path),
                timeout=5,
            )

            validator = CustomRuleValidator([rule])
            violations = await validator.validate_file(test_file_path)

            # Should pass (no violations)
            assert len(violations) == 0
        finally:
            script_path.unlink()
            test_file_path.unlink()

    @pytest.mark.asyncio
    async def test_script_validation_fail(self):
        """Test script validation that fails."""
        # Create a script that always fails (exit 1)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as script_file:
            script_file.write("#!/bin/bash\n")
            script_file.write('echo "File validation failed: Custom error message"\n')
            script_file.write("exit 1\n")
            script_path = Path(script_file.name)

        # Make script executable
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

        # Create test file to validate
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as test_file:
            test_file.write("# Test file\n")
            test_file_path = Path(test_file.name)

        try:
            rule = CustomRule(
                id="script-test",
                name="Script Test",
                category=RuleCategory.CUSTOM,
                severity=RuleSeverity.HIGH,
                is_blocker=True,
                description="Test script validation",
                enabled=True,
                type="script",
                conditions={},
                script_path=str(script_path),
                timeout=5,
            )

            validator = CustomRuleValidator([rule])
            violations = await validator.validate_file(test_file_path)

            # Should have 1 violation
            assert len(violations) == 1
            assert violations[0].rule_id == "script-test"
            assert violations[0].severity == RuleSeverity.HIGH
            assert violations[0].is_blocker is True
            assert "Custom error message" in violations[0].message
            assert violations[0].file == str(test_file_path)
        finally:
            script_path.unlink()
            test_file_path.unlink()

    @pytest.mark.asyncio
    async def test_script_validation_file_size(self):
        """Test script that checks file size."""
        # Create a script that checks file size
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as script_file:
            script_file.write("#!/bin/bash\n")
            script_file.write("FILE=$1\n")
            script_file.write("SIZE=$(wc -c < \"$FILE\")\n")
            script_file.write("if [ $SIZE -gt 100 ]; then\n")
            script_file.write('  echo "File too large: ${SIZE} bytes (max 100 bytes)"\n')
            script_file.write("  exit 1\n")
            script_file.write("fi\n")
            script_file.write("exit 0\n")
            script_path = Path(script_file.name)

        # Make script executable
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

        # Create small file (should pass)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as small_file:
            small_file.write("# Small\n")
            small_file_path = Path(small_file.name)

        # Create large file (should fail)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as large_file:
            large_file.write("# " + ("x" * 200) + "\n")
            large_file_path = Path(large_file.name)

        try:
            rule = CustomRule(
                id="file-size-limit",
                name="File Size Limit",
                category=RuleCategory.CONVENTION,
                severity=RuleSeverity.MEDIUM,
                is_blocker=False,
                description="Files must be under 100 bytes",
                enabled=True,
                type="script",
                conditions={},
                script_path=str(script_path),
                timeout=5,
            )

            validator = CustomRuleValidator([rule])

            # Small file should pass
            violations_small = await validator.validate_file(small_file_path)
            assert len(violations_small) == 0

            # Large file should fail
            violations_large = await validator.validate_file(large_file_path)
            assert len(violations_large) == 1
            assert "too large" in violations_large[0].message.lower()
        finally:
            script_path.unlink()
            small_file_path.unlink()
            large_file_path.unlink()

    @pytest.mark.asyncio
    async def test_script_validation_timeout(self):
        """Test script execution timeout."""
        # Create a script that sleeps forever
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as script_file:
            script_file.write("#!/bin/bash\n")
            script_file.write("sleep 100\n")
            script_file.write("exit 0\n")
            script_path = Path(script_file.name)

        # Make script executable
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

        # Create test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as test_file:
            test_file.write("# Test\n")
            test_file_path = Path(test_file.name)

        try:
            rule = CustomRule(
                id="timeout-test",
                name="Timeout Test",
                category=RuleCategory.CUSTOM,
                severity=RuleSeverity.LOW,
                is_blocker=False,
                description="Test timeout",
                enabled=True,
                type="script",
                conditions={},
                script_path=str(script_path),
                timeout=1,  # 1 second timeout
            )

            validator = CustomRuleValidator([rule])
            violations = await validator.validate_file(test_file_path)

            # Should return None (no violation) on timeout
            assert len(violations) == 0
        finally:
            script_path.unlink()
            test_file_path.unlink()

    @pytest.mark.asyncio
    async def test_script_not_found(self):
        """Test script not found error."""
        # Create test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as test_file:
            test_file.write("# Test\n")
            test_file_path = Path(test_file.name)

        try:
            rule = CustomRule(
                id="missing-script",
                name="Missing Script",
                category=RuleCategory.CUSTOM,
                severity=RuleSeverity.LOW,
                is_blocker=False,
                description="Test missing script",
                enabled=True,
                type="script",
                conditions={},
                script_path="/nonexistent/script.sh",
                timeout=5,
            )

            validator = CustomRuleValidator([rule])
            violations = await validator.validate_file(test_file_path)

            # Should return no violations (error logged)
            assert len(violations) == 0
        finally:
            test_file_path.unlink()

    @pytest.mark.asyncio
    async def test_script_not_executable(self):
        """Test script not executable error."""
        # Create a script that is not executable
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as script_file:
            script_file.write("#!/bin/bash\n")
            script_file.write("exit 0\n")
            script_path = Path(script_file.name)

        # Don't make it executable

        # Create test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as test_file:
            test_file.write("# Test\n")
            test_file_path = Path(test_file.name)

        try:
            rule = CustomRule(
                id="non-executable",
                name="Non Executable",
                category=RuleCategory.CUSTOM,
                severity=RuleSeverity.LOW,
                is_blocker=False,
                description="Test non-executable script",
                enabled=True,
                type="script",
                conditions={},
                script_path=str(script_path),
                timeout=5,
            )

            validator = CustomRuleValidator([rule])
            violations = await validator.validate_file(test_file_path)

            # Should return no violations (error logged)
            assert len(violations) == 0
        finally:
            script_path.unlink()
            test_file_path.unlink()

    @pytest.mark.asyncio
    async def test_script_missing_script_path(self):
        """Test script rule without script_path."""
        # Create test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as test_file:
            test_file.write("# Test\n")
            test_file_path = Path(test_file.name)

        try:
            rule = CustomRule(
                id="no-script-path",
                name="No Script Path",
                category=RuleCategory.CUSTOM,
                severity=RuleSeverity.LOW,
                is_blocker=False,
                description="Test missing script_path",
                enabled=True,
                type="script",
                conditions={},
                script_path=None,  # Missing script_path
                timeout=5,
            )

            validator = CustomRuleValidator([rule])

            # Should raise ValueError
            with pytest.raises(ValueError, match="no script_path"):
                await validator.validate_file(test_file_path)
        finally:
            test_file_path.unlink()

    @pytest.mark.asyncio
    async def test_script_with_stderr(self):
        """Test script that outputs to stderr."""
        # Create a script that outputs to both stdout and stderr
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as script_file:
            script_file.write("#!/bin/bash\n")
            script_file.write('echo "Violation message" >&1\n')
            script_file.write('echo "Debug info" >&2\n')
            script_file.write("exit 1\n")
            script_path = Path(script_file.name)

        # Make script executable
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

        # Create test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as test_file:
            test_file.write("# Test\n")
            test_file_path = Path(test_file.name)

        try:
            rule = CustomRule(
                id="stderr-test",
                name="Stderr Test",
                category=RuleCategory.CUSTOM,
                severity=RuleSeverity.LOW,
                is_blocker=False,
                description="Test stderr handling",
                enabled=True,
                type="script",
                conditions={},
                script_path=str(script_path),
                timeout=5,
            )

            validator = CustomRuleValidator([rule])
            violations = await validator.validate_file(test_file_path)

            # Should capture stdout as violation message
            assert len(violations) == 1
            assert "Violation message" in violations[0].message
            # Stderr should be logged but not in violation message
        finally:
            script_path.unlink()
            test_file_path.unlink()

    @pytest.mark.asyncio
    async def test_script_relative_path(self):
        """Test script with relative path."""
        # Create a script in a temp directory
        temp_dir = Path(tempfile.mkdtemp())
        script_path = temp_dir / "check.sh"

        with open(script_path, "w") as f:
            f.write("#!/bin/bash\n")
            f.write("exit 0\n")

        # Make script executable
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

        # Create test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as test_file:
            test_file.write("# Test\n")
            test_file_path = Path(test_file.name)

        try:
            # Use relative path
            relative_path = os.path.relpath(script_path, Path.cwd())

            rule = CustomRule(
                id="relative-path-test",
                name="Relative Path Test",
                category=RuleCategory.CUSTOM,
                severity=RuleSeverity.LOW,
                is_blocker=False,
                description="Test relative path",
                enabled=True,
                type="script",
                conditions={},
                script_path=relative_path,
                timeout=5,
            )

            validator = CustomRuleValidator([rule])
            violations = await validator.validate_file(test_file_path)

            # Should work with relative path
            assert len(violations) == 0
        finally:
            script_path.unlink()
            temp_dir.rmdir()
            test_file_path.unlink()
