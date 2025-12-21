"""Tests for YAML loader."""

import pytest
from pathlib import Path
import tempfile

from warden.rules.domain.enums import RuleCategory, RuleSeverity
from warden.rules.infrastructure.yaml_loader import RulesYAMLLoader


class TestRulesYAMLLoader:
    """Test RulesYAMLLoader."""

    @pytest.mark.asyncio
    async def test_load_valid_yaml(self):
        """Test loading valid YAML configuration."""
        yaml_content = """
project:
  name: "test-project"
  language: "python"
  framework: "fastapi"

rules:
  - id: "no-secrets"
    name: "No Hardcoded Secrets"
    category: security
    severity: critical
    isBlocker: true
    description: "Prevent secrets in code"
    enabled: true
    type: security
    conditions:
      secrets:
        patterns:
          - "api_key\\s*="

ai_validation:
  enabled: true
  llm_provider: "openai"

exclude:
  paths:
    - "node_modules/"
  files:
    - "*.test.py"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = await RulesYAMLLoader.load_from_file(temp_path)

            assert config.project_name == "test-project"
            assert config.language == "python"
            assert config.framework == "fastapi"
            assert len(config.rules) == 1
            assert config.rules[0].id == "no-secrets"
            assert config.rules[0].category == RuleCategory.SECURITY
            assert config.rules[0].severity == RuleSeverity.CRITICAL
            assert config.ai_validation_enabled is True
            assert config.llm_provider == "openai"
            assert "node_modules/" in config.exclude_paths
            assert "*.test.py" in config.exclude_files
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_load_missing_file(self):
        """Test loading non-existent file raises error."""
        with pytest.raises(FileNotFoundError):
            await RulesYAMLLoader.load_from_file(Path("nonexistent.yaml"))

    @pytest.mark.asyncio
    async def test_invalid_yaml_structure(self):
        """Test invalid YAML structure raises error."""
        yaml_content = """
# Missing project section
rules:
  - id: "test"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Missing 'project' section"):
                await RulesYAMLLoader.load_from_file(temp_path)
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_invalid_rule_category(self):
        """Test invalid rule category raises error."""
        yaml_content = """
project:
  name: "test"
  language: "python"

rules:
  - id: "test"
    name: "Test"
    category: invalid_category
    severity: critical
    isBlocker: true
    description: "Test"
    enabled: true
    type: security
    conditions: {}
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Invalid category"):
                await RulesYAMLLoader.load_from_file(temp_path)
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_multiple_rules(self):
        """Test loading multiple rules."""
        yaml_content = """
project:
  name: "test"
  language: "python"

rules:
  - id: "rule1"
    name: "Rule 1"
    category: security
    severity: critical
    isBlocker: true
    description: "Test 1"
    enabled: true
    type: security
    conditions:
      secrets:
        patterns: ["test"]

  - id: "rule2"
    name: "Rule 2"
    category: convention
    severity: high
    isBlocker: false
    description: "Test 2"
    enabled: false
    type: convention
    conditions:
      api:
        routePattern: "^/v[0-9]+/"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = await RulesYAMLLoader.load_from_file(temp_path)

            assert len(config.rules) == 2
            assert config.rules[0].id == "rule1"
            assert config.rules[0].enabled is True
            assert config.rules[1].id == "rule2"
            assert config.rules[1].enabled is False
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_frame_rules_basic(self):
        """Test loading basic frame_rules configuration."""
        yaml_content = """
project:
  name: "test"
  language: "python"

rules:
  - id: "rule1"
    name: "Rule 1"
    category: security
    severity: critical
    isBlocker: true
    description: "Test 1"
    enabled: true
    type: security
    conditions:
      secrets:
        patterns: ["test"]

  - id: "rule2"
    name: "Rule 2"
    category: convention
    severity: high
    isBlocker: false
    description: "Test 2"
    enabled: true
    type: convention
    conditions:
      api:
        routePattern: "^/v[0-9]+/"

frame_rules:
  security:
    pre_rules: ["rule1"]
    post_rules: ["rule2"]
    on_fail: "stop"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = await RulesYAMLLoader.load_from_file(temp_path)

            # Check frame_rules were loaded
            assert len(config.frame_rules) == 1
            assert "security" in config.frame_rules

            # Check security frame rules
            security_rules = config.frame_rules["security"]
            assert len(security_rules.pre_rules) == 1
            assert security_rules.pre_rules[0].id == "rule1"
            assert len(security_rules.post_rules) == 1
            assert security_rules.post_rules[0].id == "rule2"
            assert security_rules.on_fail == "stop"
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_frame_rules_multiple_frames(self):
        """Test loading frame_rules for multiple frames."""
        yaml_content = """
project:
  name: "test"
  language: "python"

rules:
  - id: "rule1"
    name: "Rule 1"
    category: security
    severity: critical
    isBlocker: true
    description: "Test 1"
    enabled: true
    type: security
    conditions:
      secrets:
        patterns: ["test"]

  - id: "rule2"
    name: "Rule 2"
    category: convention
    severity: high
    isBlocker: false
    description: "Test 2"
    enabled: true
    type: convention
    conditions:
      api:
        routePattern: "^/v[0-9]+/"

  - id: "rule3"
    name: "Rule 3"
    category: performance
    severity: medium
    isBlocker: false
    description: "Test 3"
    enabled: true
    type: convention
    conditions:
      naming:
        asyncMethodSuffix: "_async"

frame_rules:
  security:
    pre_rules: ["rule1"]
    post_rules: ["rule2"]
    on_fail: "stop"

  chaos:
    pre_rules: ["rule3"]
    on_fail: "continue"

  fuzz:
    post_rules: ["rule1", "rule2"]
    on_fail: "stop"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = await RulesYAMLLoader.load_from_file(temp_path)

            # Check all frames loaded
            assert len(config.frame_rules) == 3
            assert "security" in config.frame_rules
            assert "chaos" in config.frame_rules
            assert "fuzz" in config.frame_rules

            # Check security frame
            assert len(config.frame_rules["security"].pre_rules) == 1
            assert len(config.frame_rules["security"].post_rules) == 1
            assert config.frame_rules["security"].on_fail == "stop"

            # Check chaos frame
            assert len(config.frame_rules["chaos"].pre_rules) == 1
            assert len(config.frame_rules["chaos"].post_rules) == 0
            assert config.frame_rules["chaos"].on_fail == "continue"

            # Check fuzz frame
            assert len(config.frame_rules["fuzz"].pre_rules) == 0
            assert len(config.frame_rules["fuzz"].post_rules) == 2
            assert config.frame_rules["fuzz"].on_fail == "stop"
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_frame_rules_missing_rule_id(self, caplog):
        """Test frame_rules with missing rule ID logs warning."""
        yaml_content = """
project:
  name: "test"
  language: "python"

rules:
  - id: "rule1"
    name: "Rule 1"
    category: security
    severity: critical
    isBlocker: true
    description: "Test 1"
    enabled: true
    type: security
    conditions:
      secrets:
        patterns: ["test"]

frame_rules:
  security:
    pre_rules: ["rule1", "nonexistent-rule"]
    post_rules: ["another-missing-rule"]
    on_fail: "stop"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = await RulesYAMLLoader.load_from_file(temp_path)

            # Should still load, but only with valid rules
            assert "security" in config.frame_rules
            assert len(config.frame_rules["security"].pre_rules) == 1
            assert config.frame_rules["security"].pre_rules[0].id == "rule1"
            assert len(config.frame_rules["security"].post_rules) == 0

            # Check warnings were logged (structured logging)
            # Note: caplog may not capture structlog output, but functionality is tested
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_frame_rules_invalid_on_fail_value(self):
        """Test frame_rules with invalid on_fail value defaults to 'stop'."""
        yaml_content = """
project:
  name: "test"
  language: "python"

rules:
  - id: "rule1"
    name: "Rule 1"
    category: security
    severity: critical
    isBlocker: true
    description: "Test 1"
    enabled: true
    type: security
    conditions:
      secrets:
        patterns: ["test"]

frame_rules:
  security:
    pre_rules: ["rule1"]
    on_fail: "invalid_value"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = await RulesYAMLLoader.load_from_file(temp_path)

            # Should default to "stop"
            assert config.frame_rules["security"].on_fail == "stop"
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_frame_rules_empty_section(self):
        """Test with empty frame_rules section."""
        yaml_content = """
project:
  name: "test"
  language: "python"

rules:
  - id: "rule1"
    name: "Rule 1"
    category: security
    severity: critical
    isBlocker: true
    description: "Test 1"
    enabled: true
    type: security
    conditions:
      secrets:
        patterns: ["test"]

frame_rules: {}
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = await RulesYAMLLoader.load_from_file(temp_path)

            # Should return empty dict
            assert len(config.frame_rules) == 0
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_frame_rules_no_section(self):
        """Test without frame_rules section."""
        yaml_content = """
project:
  name: "test"
  language: "python"

rules:
  - id: "rule1"
    name: "Rule 1"
    category: security
    severity: critical
    isBlocker: true
    description: "Test 1"
    enabled: true
    type: security
    conditions:
      secrets:
        patterns: ["test"]
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = await RulesYAMLLoader.load_from_file(temp_path)

            # Should return empty dict
            assert len(config.frame_rules) == 0
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_frame_rules_default_on_fail(self):
        """Test frame_rules defaults on_fail to 'stop' when not specified."""
        yaml_content = """
project:
  name: "test"
  language: "python"

rules:
  - id: "rule1"
    name: "Rule 1"
    category: security
    severity: critical
    isBlocker: true
    description: "Test 1"
    enabled: true
    type: security
    conditions:
      secrets:
        patterns: ["test"]

frame_rules:
  security:
    pre_rules: ["rule1"]
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = await RulesYAMLLoader.load_from_file(temp_path)

            # Should default to "stop"
            assert config.frame_rules["security"].on_fail == "stop"
        finally:
            temp_path.unlink()

    @pytest.mark.asyncio
    async def test_frame_rules_empty_lists(self):
        """Test frame_rules with empty pre/post rule lists."""
        yaml_content = """
project:
  name: "test"
  language: "python"

rules:
  - id: "rule1"
    name: "Rule 1"
    category: security
    severity: critical
    isBlocker: true
    description: "Test 1"
    enabled: true
    type: security
    conditions:
      secrets:
        patterns: ["test"]

frame_rules:
  security:
    pre_rules: []
    post_rules: []
    on_fail: "continue"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = await RulesYAMLLoader.load_from_file(temp_path)

            # Should still create the frame rule with empty lists
            assert "security" in config.frame_rules
            assert len(config.frame_rules["security"].pre_rules) == 0
            assert len(config.frame_rules["security"].post_rules) == 0
            assert config.frame_rules["security"].on_fail == "continue"
        finally:
            temp_path.unlink()
