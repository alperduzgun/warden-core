"""Tests for type:ai rule validation and the rule_generator module.

Covers:
  - AI rule skip when llm_service=None
  - Skipped blocker tracking (Risk 4 fix)
  - violation_found=true / false paths via mock LLM
  - LLM exception → silent return []
  - YAML loader accepts type:ai rule without conditions
  - Generated YAML roundtrip through RulesYAMLLoader
  - generate_rules_for_project writes a valid file
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from warden.rules.application.rule_validator import CustomRuleValidator
from warden.rules.domain.enums import RuleCategory, RuleSeverity
from warden.rules.domain.models import CustomRule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ai_rule(
    rule_id: str = "test-ai-rule",
    is_blocker: bool = False,
    enabled: bool = True,
) -> CustomRule:
    return CustomRule(
        id=rule_id,
        name="Test AI Rule",
        category=RuleCategory.SECURITY,
        severity=RuleSeverity.HIGH,
        is_blocker=is_blocker,
        description="Flag any use of eval() with user-controlled input.",
        enabled=enabled,
        type="ai",
        conditions={},
    )


def _make_mock_llm(violation: bool = False, raise_exc: Exception | None = None) -> AsyncMock:
    """Return a mock LLM service whose complete_async behaves as requested."""
    service = AsyncMock()
    service.provider = "mock"

    if raise_exc is not None:
        service.complete_async = AsyncMock(side_effect=raise_exc)
    else:
        payload = json.dumps(
            {
                "violation_found": violation,
                "line_number": 10 if violation else 0,
                "explanation": "eval() called with user input" if violation else "",
                "suggestion": "Replace with ast.literal_eval()" if violation else "",
            }
        )
        service.complete_async = AsyncMock(return_value=payload)

    # Attach dummy config so rule_validator can probe .config.smart_model
    service.config = MagicMock()
    service.config.smart_model = None
    return service


# ---------------------------------------------------------------------------
# Test 1 — skip when no LLM, no blocker
# ---------------------------------------------------------------------------

class TestAiRuleSkipNoLlm:
    @pytest.mark.asyncio
    async def test_ai_rule_skip_when_no_llm(self, tmp_path: Path) -> None:
        """type:ai rule with llm_service=None → violations=[], no exception."""
        rule = _make_ai_rule()
        validator = CustomRuleValidator([rule], llm_service=None)

        target = tmp_path / "code.py"
        target.write_text("x = eval(user_input)\n", encoding="utf-8")

        violations = await validator.validate_file_async(target)

        assert violations == []
        assert validator.skipped_ai_blockers == []


# ---------------------------------------------------------------------------
# Test 2 — skipped blocker is tracked and visible
# ---------------------------------------------------------------------------

class TestAiRuleBlockerSkipped:
    @pytest.mark.asyncio
    async def test_ai_rule_blocker_skipped_visible(self, tmp_path: Path) -> None:
        """isBlocker:true + llm_service=None → rule id appears in skipped_ai_blockers."""
        rule = _make_ai_rule(rule_id="eval-blocker", is_blocker=True)
        validator = CustomRuleValidator([rule], llm_service=None)

        target = tmp_path / "code.py"
        target.write_text("result = eval(data)\n", encoding="utf-8")

        violations = await validator.validate_file_async(target)

        assert violations == []
        assert "eval-blocker" in validator.skipped_ai_blockers


# ---------------------------------------------------------------------------
# Test 3 — violation_found: true
# ---------------------------------------------------------------------------

class TestAiRuleViolationFound:
    @pytest.mark.asyncio
    async def test_validate_ai_rule_violation_found(self, tmp_path: Path) -> None:
        """Mock LLM returns violation_found:true → CustomRuleViolation produced."""
        rule = _make_ai_rule(rule_id="eval-check")
        llm = _make_mock_llm(violation=True)
        validator = CustomRuleValidator([rule], llm_service=llm)

        target = tmp_path / "code.py"
        target.write_text("result = eval(user_data)\n", encoding="utf-8")

        violations = await validator.validate_file_async(target)

        assert len(violations) == 1
        assert violations[0].rule_id == "eval-check"
        llm.complete_async.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 4 — violation_found: false
# ---------------------------------------------------------------------------

class TestAiRuleClean:
    @pytest.mark.asyncio
    async def test_validate_ai_rule_clean(self, tmp_path: Path) -> None:
        """Mock LLM returns violation_found:false → violations=[]."""
        rule = _make_ai_rule()
        llm = _make_mock_llm(violation=False)
        validator = CustomRuleValidator([rule], llm_service=llm)

        target = tmp_path / "safe.py"
        target.write_text("x = 1 + 1\n", encoding="utf-8")

        violations = await validator.validate_file_async(target)

        assert violations == []
        llm.complete_async.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 5 — LLM exception → silent []
# ---------------------------------------------------------------------------

class TestAiRuleLlmException:
    @pytest.mark.asyncio
    async def test_validate_ai_rule_llm_exception(self, tmp_path: Path) -> None:
        """LLM raises exception → violations=[], no crash."""
        rule = _make_ai_rule()
        llm = _make_mock_llm(raise_exc=RuntimeError("LLM timeout"))
        validator = CustomRuleValidator([rule], llm_service=llm)

        target = tmp_path / "code.py"
        target.write_text("x = eval(data)\n", encoding="utf-8")

        violations = await validator.validate_file_async(target)

        assert violations == []


# ---------------------------------------------------------------------------
# Test 6 — YAML loader accepts type:ai rule (no conditions field required)
# ---------------------------------------------------------------------------

class TestYamlLoaderAcceptsAiRule:
    def test_yaml_loader_accepts_ai_type_rule(self, tmp_path: Path) -> None:
        """RulesYAMLLoader parses type:ai rule without conditions — no ValueError."""
        from warden.rules.infrastructure.yaml_loader import RulesYAMLLoader

        (tmp_path / ".warden").mkdir()
        rules_yaml = tmp_path / ".warden" / "rules.yaml"
        rules_yaml.write_text(
            """
rules:
  - id: ai-eval-check
    name: AI Eval Check
    category: security
    severity: high
    isBlocker: false
    description: Flag any eval() with user-controlled input.
    enabled: true
    type: ai
""",
            encoding="utf-8",
        )

        config = RulesYAMLLoader.load_rules_sync(tmp_path)

        assert len(config.rules) == 1
        assert config.rules[0].id == "ai-eval-check"
        assert config.rules[0].type == "ai"


# ---------------------------------------------------------------------------
# Test 7 — Generated YAML roundtrip
# ---------------------------------------------------------------------------

class TestGeneratedYamlRoundtrip:
    def test_generated_yaml_roundtrip(self, tmp_path: Path) -> None:
        """LLM YAML string → RulesYAMLLoader → CustomRule objects without error."""
        from warden.rules.infrastructure.yaml_loader import RulesYAMLLoader

        llm_output = """rules:
  - id: no-hardcoded-secret
    name: No Hardcoded Secret
    category: security
    severity: critical
    isBlocker: true
    description: Detect any hardcoded API keys, tokens, or passwords assigned to variables.
    enabled: true
    type: ai
  - id: no-debug-print
    name: No Debug Print
    category: convention
    severity: low
    isBlocker: false
    description: Flag print() statements that appear to output debug or internal state information.
    enabled: true
    type: ai
"""
        (tmp_path / ".warden").mkdir()
        rules_file = tmp_path / ".warden" / "rules.yaml"
        rules_file.write_text(llm_output, encoding="utf-8")

        config = RulesYAMLLoader.load_rules_sync(tmp_path)

        assert len(config.rules) == 2
        ids = {r.id for r in config.rules}
        assert "no-hardcoded-secret" in ids
        assert "no-debug-print" in ids
        for rule in config.rules:
            assert rule.type == "ai"
            assert rule.enabled is True


# ---------------------------------------------------------------------------
# Test 8 — generate_rules_for_project writes file with required fields
# ---------------------------------------------------------------------------

class TestRuleGeneratorWritesFile:
    @pytest.mark.asyncio
    async def test_rule_generator_writes_file(self, tmp_path: Path) -> None:
        """generate_rules_for_project → file created, required fields present in each rule."""
        from warden.rules.application.rule_generator import REQUIRED_FIELDS, generate_rules_for_project

        # Set up .warden/rules dir
        warden_rules = tmp_path / ".warden" / "rules"
        warden_rules.mkdir(parents=True)

        llm_yaml_output = yaml.dump(
            {
                "rules": [
                    {
                        "id": "no-raw-sql",
                        "name": "No Raw SQL",
                        "category": "security",
                        "severity": "critical",
                        "isBlocker": True,
                        "description": "Flag SQL built via string concatenation.",
                        "enabled": True,
                        "type": "ai",
                    }
                ]
            }
        )

        llm = AsyncMock()
        llm.complete_async = AsyncMock(return_value=llm_yaml_output)

        # Mock framework detection so no real FS scan happens
        from unittest.mock import patch

        mock_detection = MagicMock()
        mock_detection.primary_framework = None
        mock_detection.detected_frameworks = []

        with patch(
            "warden.analysis.application.discovery.framework_detector.detect_frameworks_async",
            new=AsyncMock(return_value=mock_detection),
        ):
            count = await generate_rules_for_project(tmp_path, llm, force=False)

        assert count == 1

        output_path = tmp_path / ".warden" / "rules" / "llm_generated.yml"
        assert output_path.exists()

        written = yaml.safe_load(output_path.read_text(encoding="utf-8"))
        assert "rules" in written
        rule = written["rules"][0]
        missing = REQUIRED_FIELDS - set(rule.keys())
        assert missing == set(), f"Missing fields in written rule: {missing}"


# ---------------------------------------------------------------------------
# Test 9 — CustomRule accepts optional context field
# ---------------------------------------------------------------------------

class TestCustomRuleContextField:
    def test_context_field_optional_none_by_default(self) -> None:
        """CustomRule without context → context is None."""
        rule = _make_ai_rule()
        assert rule.context is None

    def test_context_field_stored_when_provided(self) -> None:
        """CustomRule with context string → context is preserved."""
        rule = CustomRule(
            id="ctx-rule",
            name="Context Rule",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.MEDIUM,
            is_blocker=False,
            description="Some directive.",
            enabled=True,
            type="ai",
            conditions={},
            context="FastAPI project. Background workers are out of scope.",
        )
        assert rule.context == "FastAPI project. Background workers are out of scope."


# ---------------------------------------------------------------------------
# Test 10 — YAML loader reads context field
# ---------------------------------------------------------------------------

class TestYamlLoaderReadsContext:
    def test_yaml_loader_reads_context_field(self, tmp_path: Path) -> None:
        """context: field in YAML → populated on CustomRule object."""
        from warden.rules.infrastructure.yaml_loader import RulesYAMLLoader

        (tmp_path / ".warden").mkdir()
        rules_yaml = tmp_path / ".warden" / "rules.yaml"
        rules_yaml.write_text(
            """
rules:
  - id: ctx-test
    name: Context Test
    category: security
    severity: medium
    isBlocker: false
    description: "Flag insecure patterns."
    enabled: true
    type: ai
    context: "FastAPI project. Global exception handler catches FreeMCPError. Workers are out of scope."
""",
            encoding="utf-8",
        )

        config = RulesYAMLLoader.load_rules_sync(tmp_path)

        assert len(config.rules) == 1
        rule = config.rules[0]
        assert rule.context == "FastAPI project. Global exception handler catches FreeMCPError. Workers are out of scope."

    def test_yaml_loader_context_absent_is_none(self, tmp_path: Path) -> None:
        """Rule without context: field → context is None (not KeyError)."""
        from warden.rules.infrastructure.yaml_loader import RulesYAMLLoader

        (tmp_path / ".warden").mkdir()
        rules_yaml = tmp_path / ".warden" / "rules.yaml"
        rules_yaml.write_text(
            """
rules:
  - id: no-ctx
    name: No Context Rule
    category: convention
    severity: low
    isBlocker: false
    description: "Some rule."
    enabled: true
    type: ai
""",
            encoding="utf-8",
        )

        config = RulesYAMLLoader.load_rules_sync(tmp_path)
        assert config.rules[0].context is None


# ---------------------------------------------------------------------------
# Test 11 — context injected into LLM prompt when present
# ---------------------------------------------------------------------------

class TestContextInjectedIntoPrompt:
    @pytest.mark.asyncio
    async def test_context_appears_in_llm_prompt_when_set(self, tmp_path: Path) -> None:
        """Rule with context → LLM prompt contains RULE CONTEXT block."""
        rule = CustomRule(
            id="ctx-rule",
            name="Context Rule",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.HIGH,
            is_blocker=False,
            description="Flag eval() usage.",
            enabled=True,
            type="ai",
            conditions={},
            context="FastAPI project. Background workers are out of scope. Only flag HTTP handlers.",
        )
        captured_prompts: list[str] = []

        async def capture(*args, **kwargs):
            captured_prompts.append(kwargs.get("prompt") or (args[0] if args else ""))
            return json.dumps({"violation_found": False, "line_number": 0, "explanation": "", "suggestion": ""})

        llm = AsyncMock()
        llm.complete_async = AsyncMock(side_effect=capture)
        llm.config = MagicMock()
        llm.config.smart_model = None

        validator = CustomRuleValidator([rule], llm_service=llm)
        target = tmp_path / "code.py"
        target.write_text("x = 1\n", encoding="utf-8")

        await validator.validate_file_async(target)

        assert len(captured_prompts) == 1
        assert "RULE CONTEXT" in captured_prompts[0]
        assert "Background workers are out of scope" in captured_prompts[0]

    @pytest.mark.asyncio
    async def test_no_context_block_when_context_is_none(self, tmp_path: Path) -> None:
        """Rule without context → prompt does NOT contain RULE CONTEXT block."""
        rule = _make_ai_rule()
        assert rule.context is None

        captured_prompts: list[str] = []

        async def capture(*args, **kwargs):
            captured_prompts.append(kwargs.get("prompt") or (args[0] if args else ""))
            return json.dumps({"violation_found": False, "line_number": 0, "explanation": "", "suggestion": ""})

        llm = AsyncMock()
        llm.complete_async = AsyncMock(side_effect=capture)
        llm.config = MagicMock()
        llm.config.smart_model = None

        validator = CustomRuleValidator([rule], llm_service=llm)
        target = tmp_path / "code.py"
        target.write_text("x = 1\n", encoding="utf-8")

        await validator.validate_file_async(target)

        assert len(captured_prompts) == 1
        assert "RULE CONTEXT" not in captured_prompts[0]
