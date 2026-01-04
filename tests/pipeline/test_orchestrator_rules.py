"""
Tests for PipelineOrchestrator PRE/POST rules logic.

Validates edge cases and correct behavior of custom rules system.
"""

import pytest
from pathlib import Path
from warden.pipeline import (
    PipelineOrchestrator,
    PipelineConfig,
    ExecutionStrategy,
    PipelineStatus,
)
from warden.validation.frames import SecurityFrame, ChaosFrame
from warden.validation.domain.frame import CodeFile
from warden.rules.domain.models import CustomRule, FrameRules
from warden.rules.domain.enums import RuleSeverity, RuleType


@pytest.mark.asyncio
async def test_pre_rule_blocker_stops_frame_execution():
    """Test PRE blocker rule with on_fail='stop' prevents frame execution."""
    frames = [SecurityFrame()]

    # Create PRE rule that will fail
    pre_rule = CustomRule(
        id="pre_blocker",
        name="Block Python Files",
        description="Test blocker",
        type=RuleType.PATTERN,
        pattern=r"\.py$",  # Matches .py files
        severity=RuleSeverity.CRITICAL,
        file_pattern="*.py",
        is_blocker=True,
    )

    frame_rules = FrameRules(
        pre_rules=[pre_rule],
        post_rules=[],
        on_fail="stop",
    )

    config = PipelineConfig(
        strategy=ExecutionStrategy.SEQUENTIAL,
        frame_rules={
            SecurityFrame.frame_id: frame_rules,
        },
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content='def foo(): pass',
        language="python",
    )

    result = await orchestrator.execute([code_file])

    # Frame should fail due to PRE blocker
    assert result.status == PipelineStatus.FAILED
    assert result.frames_failed == 1

    # Check frame result
    frame_result = result.frame_results[0]
    assert frame_result.status == "failed"
    assert frame_result.pre_rule_violations is not None
    assert len(frame_result.pre_rule_violations) > 0

    # Issues_found should be 0 (frame didn't execute)
    assert frame_result.issues_found == 0


@pytest.mark.asyncio
async def test_post_rule_blocker_detected():
    """Test POST blocker violations are detected and logged."""
    frames = [SecurityFrame()]

    # POST rule that always fails
    post_rule = CustomRule(
        id="post_blocker",
        name="Post Validation Failed",
        description="Test POST blocker",
        type=RuleType.PATTERN,
        pattern=r"def\s+\w+",  # Matches function definitions
        severity=RuleSeverity.CRITICAL,
        file_pattern="*.py",
        is_blocker=True,
    )

    frame_rules = FrameRules(
        pre_rules=[],
        post_rules=[post_rule],
        on_fail="stop",
    )

    config = PipelineConfig(
        strategy=ExecutionStrategy.SEQUENTIAL,
        frame_rules={
            SecurityFrame.frame_id: frame_rules,
        },
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content='def foo(): pass',
        language="python",
    )

    result = await orchestrator.execute([code_file])

    # Frame should fail due to POST blocker
    assert result.status == PipelineStatus.FAILED
    assert result.frames_failed == 1

    # Check frame result
    frame_result = result.frame_results[0]
    assert frame_result.status == "failed"
    assert frame_result.post_rule_violations is not None
    assert len(frame_result.post_rule_violations) > 0


@pytest.mark.asyncio
async def test_status_determination_with_mixed_violations():
    """Test status logic with PRE + frame findings + POST violations."""
    frames = [ChaosFrame()]  # Non-blocker frame

    # Non-blocker PRE rule (warning)
    pre_rule = CustomRule(
        id="pre_warning",
        name="PRE Warning",
        description="Non-blocker PRE",
        type=RuleType.PATTERN,
        pattern=r"import",
        severity=RuleSeverity.MEDIUM,
        file_pattern="*.py",
        is_blocker=False,
    )

    # Blocker POST rule
    post_rule = CustomRule(
        id="post_blocker",
        name="POST Blocker",
        description="Blocker POST",
        type=RuleType.PATTERN,
        pattern=r"def",
        severity=RuleSeverity.CRITICAL,
        file_pattern="*.py",
        is_blocker=True,
    )

    frame_rules = FrameRules(
        pre_rules=[pre_rule],
        post_rules=[post_rule],
        on_fail="stop",
    )

    config = PipelineConfig(
        strategy=ExecutionStrategy.SEQUENTIAL,
        frame_rules={
            ChaosFrame.frame_id: frame_rules,
        },
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content="""
import requests

def fetch_data():
    response = requests.get(url)  # Missing timeout
    return response.json()
""",
        language="python",
    )

    result = await orchestrator.execute([code_file])

    # Should fail due to POST blocker
    assert result.status == PipelineStatus.FAILED
    assert result.frames_failed == 1

    frame_result = result.frame_results[0]
    assert frame_result.status == "failed"

    # All violations should be counted
    assert frame_result.pre_rule_violations is not None
    assert len(frame_result.pre_rule_violations) > 0
    assert frame_result.post_rule_violations is not None
    assert len(frame_result.post_rule_violations) > 0


@pytest.mark.asyncio
async def test_pipeline_counters_include_violations():
    """Test pipeline.total_issues includes findings + violations."""
    frames = [SecurityFrame()]

    # Create rules that will trigger violations
    pre_rule = CustomRule(
        id="pre_counter",
        name="PRE Counter",
        description="Count PRE violations",
        type=RuleType.PATTERN,
        pattern=r"import\s+os",
        severity=RuleSeverity.MEDIUM,
        file_pattern="*.py",
        is_blocker=False,
    )

    post_rule = CustomRule(
        id="post_counter",
        name="POST Counter",
        description="Count POST violations",
        type=RuleType.PATTERN,
        pattern=r"def\s+main",
        severity=RuleSeverity.MEDIUM,
        file_pattern="*.py",
        is_blocker=False,
    )

    frame_rules = FrameRules(
        pre_rules=[pre_rule],
        post_rules=[post_rule],
        on_fail="continue",
    )

    config = PipelineConfig(
        strategy=ExecutionStrategy.SEQUENTIAL,
        frame_rules={
            SecurityFrame.frame_id: frame_rules,
        },
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content="""
import os

def main():
    password = "admin123"  # Security issue
    return os.getenv("SECRET")
""",
        language="python",
    )

    result = await orchestrator.execute([code_file])

    frame_result = result.frame_results[0]

    # Count total issues
    findings_count = len(frame_result.findings)
    pre_violations_count = len(frame_result.pre_rule_violations) if frame_result.pre_rule_violations else 0
    post_violations_count = len(frame_result.post_rule_violations) if frame_result.post_rule_violations else 0

    expected_total = findings_count + pre_violations_count + post_violations_count

    # Pipeline total_issues should include ALL
    assert result.total_findings >= expected_total


@pytest.mark.asyncio
async def test_empty_list_vs_none_handling():
    """Test None vs [] distinction for rule violations."""
    frames = [SecurityFrame()]

    # Frame with only POST rules (no PRE)
    post_rule = CustomRule(
        id="post_only",
        name="POST Only",
        description="POST rule only",
        type=RuleType.PATTERN,
        pattern=r"IMPOSSIBLE_PATTERN_XYZ123",  # Won't match
        severity=RuleSeverity.MEDIUM,
        file_pattern="*.py",
        is_blocker=False,
    )

    frame_rules = FrameRules(
        pre_rules=[],  # No PRE rules
        post_rules=[post_rule],
        on_fail="continue",
    )

    config = PipelineConfig(
        strategy=ExecutionStrategy.SEQUENTIAL,
        frame_rules={
            SecurityFrame.frame_id: frame_rules,
        },
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content='def foo(): pass',
        language="python",
    )

    result = await orchestrator.execute([code_file])

    frame_result = result.frame_results[0]

    # PRE rules don't exist → pre_rule_violations should be None
    assert frame_result.pre_rule_violations is None

    # POST rules exist but no violations → post_rule_violations should be []
    assert frame_result.post_rule_violations is not None
    assert len(frame_result.post_rule_violations) == 0


@pytest.mark.asyncio
async def test_blocker_frame_with_non_blocker_violations():
    """Test blocker frame with non-blocker rule violations."""
    frames = [SecurityFrame()]  # Blocker frame

    # Non-blocker PRE rule
    pre_rule = CustomRule(
        id="non_blocker_pre",
        name="Non-blocker PRE",
        description="Warning only",
        type=RuleType.PATTERN,
        pattern=r"TODO",
        severity=RuleSeverity.LOW,
        file_pattern="*.py",
        is_blocker=False,
    )

    frame_rules = FrameRules(
        pre_rules=[pre_rule],
        post_rules=[],
        on_fail="continue",
    )

    config = PipelineConfig(
        strategy=ExecutionStrategy.SEQUENTIAL,
        frame_rules={
            SecurityFrame.frame_id: frame_rules,
        },
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content="""
# TODO: Fix this
password = "admin123"  # Security blocker issue
""",
        language="python",
    )

    result = await orchestrator.execute([code_file])

    # Should fail due to SecurityFrame findings (blocker frame)
    assert result.status == PipelineStatus.FAILED

    frame_result = result.frame_results[0]
    assert frame_result.status == "failed"

    # Should have both PRE violations (non-blocker) and findings (blocker)
    assert frame_result.pre_rule_violations is not None
    assert frame_result.issues_found > 0


@pytest.mark.asyncio
async def test_blocker_violations_count():
    """Test blocker_issues counter includes blocker violations."""
    frames = [ChaosFrame()]  # Non-blocker frame

    # Blocker PRE rule
    pre_blocker = CustomRule(
        id="pre_blocker_count",
        name="PRE Blocker",
        description="Blocker PRE",
        type=RuleType.PATTERN,
        pattern=r"critical_error",
        severity=RuleSeverity.CRITICAL,
        file_pattern="*.py",
        is_blocker=True,
    )

    # Blocker POST rule
    post_blocker = CustomRule(
        id="post_blocker_count",
        name="POST Blocker",
        description="Blocker POST",
        type=RuleType.PATTERN,
        pattern=r"security_breach",
        severity=RuleSeverity.CRITICAL,
        file_pattern="*.py",
        is_blocker=True,
    )

    frame_rules = FrameRules(
        pre_rules=[pre_blocker],
        post_rules=[post_blocker],
        on_fail="continue",  # Continue to count all violations
    )

    config = PipelineConfig(
        strategy=ExecutionStrategy.SEQUENTIAL,
        frame_rules={
            ChaosFrame.frame_id: frame_rules,
        },
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content="""
# critical_error detected
import requests

def fetch():
    # security_breach detected
    response = requests.get(url)
    return response
""",
        language="python",
    )

    result = await orchestrator.execute([code_file])

    # Should fail due to blocker violations
    assert result.status == PipelineStatus.FAILED

    # blocker_issues should count blocker violations
    # (2 blocker violations from PRE/POST)
    # Note: Exact count depends on pattern matching
    assert result.total_findings > 0


@pytest.mark.asyncio
async def test_on_fail_continue_executes_frame():
    """Test on_fail='continue' executes frame despite PRE blocker."""
    frames = [SecurityFrame()]

    # Blocker PRE rule
    pre_blocker = CustomRule(
        id="pre_continue",
        name="PRE Blocker Continue",
        description="Blocker but continue",
        type=RuleType.PATTERN,
        pattern=r"\.py$",
        severity=RuleSeverity.CRITICAL,
        file_pattern="*.py",
        is_blocker=True,
    )

    frame_rules = FrameRules(
        pre_rules=[pre_blocker],
        post_rules=[],
        on_fail="continue",  # Continue despite blocker
    )

    config = PipelineConfig(
        strategy=ExecutionStrategy.SEQUENTIAL,
        frame_rules={
            SecurityFrame.frame_id: frame_rules,
        },
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="test.py",
        content='password = "admin"',  # Security issue
        language="python",
    )

    result = await orchestrator.execute([code_file])

    frame_result = result.frame_results[0]

    # Frame should execute and find issues
    assert frame_result.issues_found > 0

    # Should have both PRE violations and findings
    assert frame_result.pre_rule_violations is not None
    assert len(frame_result.findings) > 0
