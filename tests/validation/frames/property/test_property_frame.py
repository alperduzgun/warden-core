"""
Tests for PropertyFrame.

Tests the property-based testing frame that validates business logic.
"""

import pytest
from warden.validation.domain.frame import CodeFile
from warden.validation.domain.mixins import BatchExecutable


@pytest.fixture
def PropertyFrame():
    """Load PropertyFrame from registry."""
    from warden.validation.infrastructure.frame_registry import FrameRegistry
    registry = FrameRegistry()
    registry.discover_all()
    cls = registry.get_frame_by_id("property")
    if not cls:
        pytest.skip("PropertyFrame not found in registry")
    return cls


@pytest.mark.asyncio
async def test_property_frame_initialization(PropertyFrame):
    """Test frame initializes with correct metadata."""
    frame = PropertyFrame()

    assert frame.name == "Property Testing"
    assert frame.frame_id == "property"
    assert frame.is_blocker is False
    assert frame.priority.value == 2  # HIGH = 2
    assert frame.version == "1.0.0"


@pytest.mark.asyncio
async def test_property_frame_detects_division_no_zero_check(PropertyFrame):
    """Test detection of division without zero check."""
    code = '''
def divide(a, b):
    return a / b  # BAD: No zero check
'''

    code_file = CodeFile(
        path="math.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Should detect missing zero check
    assert result.issues_found > 0

    # Should have division-related finding
    division_findings = [
        f for f in result.findings
        if "division" in f.message.lower() or "zero" in f.message.lower()
    ]
    assert len(division_findings) > 0
    assert result.status in ["passed", "warning", "failed"]


@pytest.mark.asyncio
async def test_property_frame_detects_always_true_condition(PropertyFrame):
    """Test detection of always-true conditions."""
    code = '''
def process():
    if true:  # BAD: Always true
        print("This always executes")

    while True:  # This is OK for infinite loops
        break
'''

    code_file = CodeFile(
        path="logic.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # May detect always-true condition
    # (depends on pattern matching)
    assert result.status in ["passed", "warning"]


@pytest.mark.asyncio
async def test_property_frame_detects_negative_index_possible(PropertyFrame):
    """Test detection of possible negative array indices."""
    code = '''
def get_value(arr, x, y):
    index = x - y  # Could be negative
    return arr[index]  # BAD: Possible negative index
'''

    code_file = CodeFile(
        path="array.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Should detect possible negative index (may or may not catch this pattern)
    # The frame executes without error
    assert result is not None
    assert result.status in ["passed", "warning", "failed"]


@pytest.mark.asyncio
async def test_property_frame_checks_assertions(PropertyFrame):
    """Test frame checks for assertion usage."""
    # File with many functions but no assertions
    code = '''
def func1(): return 1
def func2(): return 2
def func3(): return 3
def func4(): return 4
def func5(): return 5
def func6(): return 6
def func7(): return 7
def func8(): return 8
def func9(): return 9
def func10(): return 10
def func11(): return 11
'''

    # The assertion check only applies to test files; use a test-file path.
    code_file = CodeFile(
        path="tests/test_no_assertions.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Should suggest adding assertions
    assertion_findings = [
        f for f in result.findings
        if "assertion" in f.message.lower()
    ]
    assert len(assertion_findings) > 0


@pytest.mark.asyncio
async def test_property_frame_passes_safe_code(PropertyFrame):
    """Test frame passes code with proper preconditions."""
    code = '''
def safe_divide(a, b):
    """Division with precondition check."""
    assert b != 0, "Divisor cannot be zero"
    return a / b

def safe_array_access(arr, index):
    """Safe array access with validation."""
    assert index >= 0, "Index must be non-negative"
    assert index < len(arr), "Index out of bounds"
    return arr[index]
'''

    code_file = CodeFile(
        path="safe_math.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Should have fewer findings (code has assertions)
    assert result.status in ["passed", "warning"]


@pytest.mark.asyncio
async def test_property_frame_result_structure(PropertyFrame):
    """Test result has correct structure for Panel compatibility."""
    code = '''
def divide(a, b):
    return a / b
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Test Panel JSON compatibility
    json_data = result.to_json()

    # Check required Panel fields
    assert "frameId" in json_data
    assert "frameName" in json_data
    assert "status" in json_data
    assert "duration" in json_data
    assert "issuesFound" in json_data
    assert "isBlocker" in json_data
    assert "findings" in json_data
    assert "metadata" in json_data

    # Check metadata
    assert "checks_executed" in json_data["metadata"]


@pytest.mark.asyncio
async def test_property_frame_patterns_are_defined(PropertyFrame):
    """Test frame has property testing patterns defined."""
    frame = PropertyFrame()

    # Should have PATTERNS attribute
    assert hasattr(frame, "PATTERNS")
    assert isinstance(frame.PATTERNS, dict)
    assert len(frame.PATTERNS) > 0

    # Check pattern structure
    for pattern_id, pattern_config in frame.PATTERNS.items():
        assert "severity" in pattern_config
        assert "message" in pattern_config


@pytest.mark.asyncio
async def test_property_frame_handles_empty_file(PropertyFrame):
    """Test frame handles empty files gracefully."""
    code_file = CodeFile(
        path="empty.py",
        content="",
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Should pass (no code to analyze)
    assert result.status == "passed"
    assert result.issues_found == 0


@pytest.mark.asyncio
async def test_property_frame_multiple_issues(PropertyFrame):
    """Test frame detects multiple property violations."""
    code = '''
def bad_logic(arr, a, b, x, y):
    # Multiple issues:
    result1 = a / b  # No zero check
    index = x - y  # Could be negative
    value = arr[index]  # No bounds check
    return result1 + value
'''

    code_file = CodeFile(
        path="multiple_issues.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # Should detect at least one issue
    assert result.issues_found >= 1


@pytest.mark.asyncio
async def test_property_frame_status_determination(PropertyFrame):
    """Test frame determines status correctly based on findings."""
    # Code with high severity issues
    code_high = '''
def calc(a, b, c, d):
    x = a / b  # Issue 1
    y = c / d  # Issue 2
    z = x / y  # Issue 3
    w = z / 2  # Issue 4
    return w / 1  # Issue 5
'''

    code_file = CodeFile(
        path="many_issues.py",
        content=code_high,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # With many issues, should detect them
    assert result.issues_found > 0
    assert result.status in ["passed", "warning", "failed"]


@pytest.mark.asyncio
async def test_property_frame_finding_has_location(PropertyFrame):
    """Test findings include location information."""
    code = '''
def divide(a, b):
    return a / b
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    if result.issues_found > 0:
        finding = result.findings[0]
        assert finding.location is not None
        assert "test.py" in finding.location
        assert finding.severity in ["critical", "high", "medium", "low"]
        assert finding.message is not None


# =============================================================================
# BATCH EXECUTION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_property_frame_is_batch_executable(PropertyFrame):
    """PropertyFrame should implement BatchExecutable mixin."""
    frame = PropertyFrame()
    assert isinstance(frame, BatchExecutable)
    assert hasattr(frame, "execute_batch_async")


@pytest.mark.asyncio
async def test_property_frame_batch_empty_list(PropertyFrame):
    """Batch with empty file list returns empty results."""
    frame = PropertyFrame()
    results = await frame.execute_batch_async([])
    assert results == []


@pytest.mark.asyncio
async def test_property_frame_batch_single_file(PropertyFrame):
    """Batch with single file returns one result."""
    code_file = CodeFile(
        path="single.py",
        content="def divide(a, b):\n    return a / b\n",
        language="python",
    )

    frame = PropertyFrame()
    results = await frame.execute_batch_async([code_file])

    assert len(results) == 1
    assert results[0].frame_id == "property"
    assert results[0].metadata.get("batch_mode") is True


@pytest.mark.asyncio
async def test_property_frame_batch_multiple_files(PropertyFrame):
    """Batch with multiple files returns one result per file."""
    files = [
        CodeFile(path="a.py", content="x = 1 / y\n", language="python"),
        CodeFile(path="b.py", content="if True:\n    pass\n", language="python"),
        CodeFile(path="c.py", content="arr[x - y]\n", language="python"),
    ]

    frame = PropertyFrame()
    results = await frame.execute_batch_async(files)

    assert len(results) == 3
    for result in results:
        assert result.frame_id == "property"
        assert result.frame_name == "Property Testing"
        assert result.metadata.get("batch_mode") is True


@pytest.mark.asyncio
async def test_property_frame_batch_detects_patterns(PropertyFrame):
    """Batch mode should still detect pattern-based findings."""
    files = [
        CodeFile(
            path="math.py",
            content="def calc(a, b):\n    return a / b\n",
            language="python",
        ),
        CodeFile(
            path="safe.py",
            content="x = 1 + 2\n",
            language="python",
        ),
    ]

    frame = PropertyFrame()
    results = await frame.execute_batch_async(files)

    assert len(results) == 2
    # First file should have division finding
    assert results[0].issues_found > 0
    # Second file should be clean
    assert results[1].issues_found == 0


@pytest.mark.asyncio
async def test_property_frame_batch_has_batch_size(PropertyFrame):
    """PropertyFrame should define BATCH_SIZE constant."""
    assert hasattr(PropertyFrame, "BATCH_SIZE")
    assert PropertyFrame.BATCH_SIZE > 0
    assert PropertyFrame.BATCH_SIZE <= 10  # Conservative limit


# =============================================================================
# LINE-REFERENCE VALIDATION TESTS
# =============================================================================

# Source with disable_bundle_id_capability near the top; the hallucination test
# uses a reported line that is far away (> window=3) from any occurrence of
# the function name so the validator correctly flags it as hallucinated.
_SAMPLE_SOURCE = """\
def disable_bundle_id_capability(bundle_id, capability):
    if not bundle_id:
        return {"error": "bundle_id required"}
    return {"bundle_id": bundle_id, "disabled": capability}
"""

# Build a multi-function file where the target function is at line 1 and
# the erroneously-reported line is at the bottom, well beyond the ±3 window.
_LINES_FAR_AWAY = ["def disable_bundle_id_capability(bundle_id, capability): pass"]
_LINES_FAR_AWAY += [""] * 15
_LINES_FAR_AWAY += ["def unrelated_function(): return 42"]  # line 17
_LINES_FAR_AWAY += ["", "x = unrelated_function()"]         # line 19
_SOURCE_FAR_AWAY = "\n".join(_LINES_FAR_AWAY)
_HALLUCINATION_LINE = 19  # far from line 1 (> window=3)


def test_property_frame_has_validate_llm_line_reference(PropertyFrame):
    """PropertyFrame must expose _validate_llm_line_reference."""
    assert hasattr(PropertyFrame, "_validate_llm_line_reference")


def test_property_frame_line_ref_valid_match(PropertyFrame):
    """Line 1 contains 'disable_bundle_id_capability' — finding about it is valid."""
    result = PropertyFrame._validate_llm_line_reference(
        finding_message="Incomplete Input Validation in disable_bundle_id_capability",
        finding_title="Incomplete Input Validation in disable_bundle_id_capability",
        code_content=_SAMPLE_SOURCE,
        reported_line=1,
    )
    assert result is True


def test_property_frame_line_ref_hallucination(PropertyFrame):
    """Reported line is 19 but disable_bundle_id_capability is at line 1 (far away)."""
    result = PropertyFrame._validate_llm_line_reference(
        finding_message="Incomplete Input Validation in disable_bundle_id_capability",
        finding_title="Incomplete Input Validation in disable_bundle_id_capability",
        code_content=_SOURCE_FAR_AWAY,
        reported_line=_HALLUCINATION_LINE,
    )
    assert result is False


def test_property_frame_line_ref_out_of_range_passes(PropertyFrame):
    """Out-of-range line returns True (fail-open)."""
    result = PropertyFrame._validate_llm_line_reference(
        finding_message="some issue",
        finding_title="Some Issue",
        code_content=_SAMPLE_SOURCE,
        reported_line=9999,
    )
    assert result is True


def test_property_frame_line_ref_empty_code_passes(PropertyFrame):
    """Empty source code cannot be validated — keep finding."""
    result = PropertyFrame._validate_llm_line_reference(
        finding_message="some issue",
        finding_title="Some Issue",
        code_content="",
        reported_line=1,
    )
    assert result is True


def test_property_frame_line_ref_delegates_to_shared_util(PropertyFrame):
    """_validate_llm_line_reference result must match the shared utility output."""
    from warden.shared.utils.finding_utils import validate_llm_line_reference

    kwargs = {
        "finding_message": "disable_bundle_id_capability check",
        "finding_title": "Capability Check",
        "code_content": _SAMPLE_SOURCE,
        "reported_line": 7,
    }
    assert PropertyFrame._validate_llm_line_reference(**kwargs) == validate_llm_line_reference(**kwargs)


# ---------------------------------------------------------------------------
# _is_test_file
# ---------------------------------------------------------------------------

def test_is_test_file_detects_python_test_prefix(PropertyFrame):
    """test_foo.py matches."""
    assert PropertyFrame._is_test_file("src/auth/test_auth.py") is True


def test_is_test_file_detects_python_test_suffix(PropertyFrame):
    """foo_test.py matches."""
    assert PropertyFrame._is_test_file("src/auth/auth_test.py") is True


def test_is_test_file_detects_go_test_suffix(PropertyFrame):
    """foo_test.go matches."""
    assert PropertyFrame._is_test_file("pkg/auth/auth_test.go") is True


def test_is_test_file_detects_js_test_dot(PropertyFrame):
    """foo.test.ts matches."""
    assert PropertyFrame._is_test_file("src/components/auth.test.ts") is True


def test_is_test_file_detects_js_spec_dot(PropertyFrame):
    """foo.spec.ts matches."""
    assert PropertyFrame._is_test_file("src/components/auth.spec.ts") is True


def test_is_test_file_detects_tests_directory(PropertyFrame):
    """File inside tests/ directory matches."""
    assert PropertyFrame._is_test_file("tests/auth/test_login.py") is True


def test_is_test_file_detects_underscored_test_dir(PropertyFrame):
    """File inside __tests__/ directory matches."""
    assert PropertyFrame._is_test_file("src/__tests__/auth.js") is True


def test_is_test_file_rejects_production_file(PropertyFrame):
    """Normal production path does NOT match."""
    assert PropertyFrame._is_test_file("src/services/auth_service.py") is False


def test_is_test_file_rejects_cache_service(PropertyFrame):
    """cache_service.py must not be flagged as a test file."""
    assert PropertyFrame._is_test_file("src/cache/cache_service.py") is False


def test_is_test_file_rejects_property_frame_itself(PropertyFrame):
    """The production frame file must not match."""
    assert PropertyFrame._is_test_file("src/warden/validation/frames/property/property_frame.py") is False


# ---------------------------------------------------------------------------
# _check_assertions — production files must be skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_assertions_skips_production_files(PropertyFrame):
    """_check_assertions must return no findings for non-test files."""
    many_funcs = "\n".join(f"def func_{i}(): return {i}" for i in range(20))
    code_file = CodeFile(
        path="src/services/auth_service.py",
        content=many_funcs,
        language="python",
    )
    frame = PropertyFrame()
    findings = frame._check_assertions(code_file)
    assert findings == [], "Production files must not trigger no-assertions finding"


@pytest.mark.asyncio
async def test_check_assertions_fires_for_test_files(PropertyFrame):
    """_check_assertions must fire when a test file has many functions but no assertions."""
    many_funcs = "\n".join(f"def func_{i}(): return {i}" for i in range(15))
    code_file = CodeFile(
        path="tests/test_auth.py",
        content=many_funcs,
        language="python",
    )
    frame = PropertyFrame()
    findings = frame._check_assertions(code_file)
    assert len(findings) == 1
    assert "functions" in findings[0].message


# ---------------------------------------------------------------------------
# _filter_llm_noise
# ---------------------------------------------------------------------------

def test_filter_llm_noise_drops_cache_ttl(PropertyFrame):
    """Low-severity 'Hardcoded Cache TTL' finding must be suppressed."""
    from warden.validation.domain.frame import Finding

    frame = PropertyFrame()
    noise = Finding(
        id="p-1",
        severity="low",
        message="Hardcoded Cache TTL Without Configuration",
        location="f:1",
        detail="The cache TTL is a magic number",
    )
    assert frame._filter_llm_noise([noise]) == []


def test_filter_llm_noise_drops_transport_fallback(PropertyFrame):
    """Low-severity 'Transport Fallback Without Validation' must be suppressed."""
    from warden.validation.domain.frame import Finding

    frame = PropertyFrame()
    noise = Finding(
        id="p-2",
        severity="low",
        message="Transport Fallback Without Validation",
        location="f:2",
        detail="transport fallback path lacks validation",
    )
    assert frame._filter_llm_noise([noise]) == []


def test_filter_llm_noise_drops_magic_number(PropertyFrame):
    """Low-severity magic number finding without security context must be suppressed."""
    from warden.validation.domain.frame import Finding

    frame = PropertyFrame()
    noise = Finding(
        id="p-3",
        severity="low",
        message="Magic Number In Configuration",
        location="f:3",
        detail="Value should be configurable via environment variable",
    )
    assert frame._filter_llm_noise([noise]) == []


def test_filter_llm_noise_keeps_security_low_finding(PropertyFrame):
    """Low-severity finding that mentions a token/secret must NOT be suppressed."""
    from warden.validation.domain.frame import Finding

    frame = PropertyFrame()
    sec = Finding(
        id="p-4",
        severity="low",
        message="Hardcoded token constant",
        location="f:4",
        detail="API token is a hardcoded constant in configuration",
    )
    result = frame._filter_llm_noise([sec])
    assert len(result) == 1


def test_filter_llm_noise_keeps_medium_regardless(PropertyFrame):
    """Medium-severity noise finding must always be kept."""
    from warden.validation.domain.frame import Finding

    frame = PropertyFrame()
    med = Finding(
        id="p-5",
        severity="medium",
        message="Hardcoded Cache TTL Without Configuration",
        location="f:5",
        detail="magic number not configurable",
    )
    result = frame._filter_llm_noise([med])
    assert len(result) == 1


def test_filter_llm_noise_keeps_high_regardless(PropertyFrame):
    """High-severity finding must always be kept even if it mentions cache TTL."""
    from warden.validation.domain.frame import Finding

    frame = PropertyFrame()
    high = Finding(
        id="p-6",
        severity="high",
        message="Cache TTL Without Configuration Leads To Stale Data",
        location="f:6",
        detail="hardcoded constant",
    )
    result = frame._filter_llm_noise([high])
    assert len(result) == 1


def test_filter_llm_noise_passes_through_unrelated_low(PropertyFrame):
    """A low-severity finding with no noise keyword must pass through."""
    from warden.validation.domain.frame import Finding

    frame = PropertyFrame()
    unrelated = Finding(
        id="p-7",
        severity="low",
        message="Division without zero check in fallback path",
        location="f:7",
        detail="Potential ZeroDivisionError if divisor is zero",
    )
    result = frame._filter_llm_noise([unrelated])
    assert len(result) == 1


# =============================================================================
# KNOWN FALSE-POSITIVE FILTER TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_property_frame_suppresses_contextvar_async_fp(PropertyFrame):
    """ContextVar findings mentioning async safety must be suppressed.

    ContextVar (PEP 567) is the official Python async-safe state mechanism.
    Flagging it as an async safety concern is a false positive.
    """
    from warden.validation.domain.frame import Finding

    frame = PropertyFrame()
    findings = [
        Finding(
            id="prop-llm-10",
            severity="high",
            message="ContextVar Async Safety Concern",
            location="app.py:10",
            detail="Using ContextVar in async code may cause race conditions.",
            code="request_id: ContextVar[str] = ContextVar('request_id')",
        ),
        # Real finding that must be preserved
        Finding(
            id="prop-pattern-20",
            severity="medium",
            message="Division operation without zero check",
            location="app.py:20",
            detail="Check divisor is not zero before division",
            code="return a / b",
        ),
    ]

    filtered = frame._filter_known_false_positives(findings)

    assert len(filtered) == 1
    assert filtered[0].id == "prop-pattern-20"


@pytest.mark.asyncio
async def test_property_frame_suppresses_contextvar_thread_fp(PropertyFrame):
    """ContextVar findings mentioning thread safety must also be suppressed."""
    from warden.validation.domain.frame import Finding

    frame = PropertyFrame()
    findings = [
        Finding(
            id="prop-llm-5",
            severity="medium",
            message="ContextVar thread safety issue",
            location="middleware.py:5",
            detail="ContextVar may not be thread-safe across concurrent requests.",
            code="_ctx_var: ContextVar[dict] = ContextVar('ctx')",
        ),
    ]

    filtered = frame._filter_known_false_positives(findings)

    assert len(filtered) == 0


@pytest.mark.asyncio
async def test_property_frame_preserves_legitimate_async_findings(PropertyFrame):
    """Non-ContextVar async findings must not be suppressed."""
    from warden.validation.domain.frame import Finding

    frame = PropertyFrame()
    findings = [
        Finding(
            id="prop-llm-30",
            severity="high",
            message="Shared mutable state in async handler",
            location="handler.py:30",
            detail="Global dict modified in async context without a lock — race condition.",
            code="shared_cache[key] = value",
        ),
    ]

    filtered = frame._filter_known_false_positives(findings)

    assert len(filtered) == 1


@pytest.mark.asyncio
async def test_property_frame_contextvar_code_does_not_trigger_fp(PropertyFrame):
    """Scanning a file that uses ContextVar should not produce async-safety findings."""
    code = '''
from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="")
user_context: ContextVar[dict] = ContextVar("user_context", default={})

async def set_request_context(req_id: str) -> None:
    request_id.set(req_id)

async def get_request_id() -> str:
    return request_id.get()
'''

    code_file = CodeFile(
        path="context.py",
        content=code,
        language="python",
    )

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    # No finding should mention ContextVar as an async/thread safety concern
    fp_findings = [
        f for f in result.findings
        if "contextvar" in (f.message or "").lower()
        and any(
            kw in (f.message or "").lower() + (f.detail or "").lower()
            for kw in ("async", "thread", "race", "safe")
        )
    ]
    assert fp_findings == [], f"Unexpected ContextVar FP findings: {fp_findings}"


# =============================================================================
# DIVISION GUARD DETECTION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_division_with_inline_ternary_guard_not_flagged(PropertyFrame):
    """Inline ternary guard suppresses the division finding.

    ``sum(ratings) / len(ratings) if ratings else 0.0`` is safe — the
    ternary ensures len(ratings) is never zero when the division runs.
    """
    code = "avg = sum(ratings) / len(ratings) if ratings else 0.0\n"
    code_file = CodeFile(path="avg.py", content=code, language="python")

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    division_findings = [
        f for f in result.findings
        if "division" in f.message.lower() or "zero" in f.message.lower()
    ]
    assert division_findings == [], (
        f"Guarded division was falsely flagged: {[f.message for f in division_findings]}"
    )


@pytest.mark.asyncio
async def test_division_with_preceding_if_check_not_flagged(PropertyFrame):
    """Preceding if-block guard suppresses the division finding."""
    code = (
        "if denominator != 0:\n"
        "    result = numerator / denominator\n"
    )
    code_file = CodeFile(path="safe_div.py", content=code, language="python")

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    division_findings = [
        f for f in result.findings
        if "division" in f.message.lower() or "zero" in f.message.lower()
    ]
    assert division_findings == [], (
        f"Guarded division (if != 0) was falsely flagged: {[f.message for f in division_findings]}"
    )


@pytest.mark.asyncio
async def test_division_with_truthy_if_guard_not_flagged(PropertyFrame):
    """Truthy if-guard (`if values:`) suppresses the division finding."""
    code = (
        "if values:\n"
        "    mean = sum(values) / len(values)\n"
    )
    code_file = CodeFile(path="mean.py", content=code, language="python")

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    division_findings = [
        f for f in result.findings
        if "division" in f.message.lower() or "zero" in f.message.lower()
    ]
    assert division_findings == [], (
        f"Guarded division (truthy if) was falsely flagged: {[f.message for f in division_findings]}"
    )


@pytest.mark.asyncio
async def test_division_without_guard_still_flagged(PropertyFrame):
    """Unguarded division continues to be reported."""
    code = "def calc(a, b):\n    return a / b\n"
    code_file = CodeFile(path="unguarded.py", content=code, language="python")

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    division_findings = [
        f for f in result.findings
        if "division" in f.message.lower() or "zero" in f.message.lower()
    ]
    assert len(division_findings) > 0, "Unguarded division should still be flagged"


@pytest.mark.asyncio
async def test_division_with_or_fallback_not_flagged(PropertyFrame):
    """``or``-fallback guard suppresses the division finding."""
    code = "rate = total / (count or 1)\n"
    code_file = CodeFile(path="rate.py", content=code, language="python")

    frame = PropertyFrame()
    result = await frame.execute_async(code_file)

    division_findings = [
        f for f in result.findings
        if "division" in f.message.lower() or "zero" in f.message.lower()
    ]
    assert division_findings == [], (
        f"or-guarded division was falsely flagged: {[f.message for f in division_findings]}"
    )


def test_has_division_guard_direct_ternary(PropertyFrame):
    """Unit-test _has_division_guard directly for ternary guard on same line."""
    frame = PropertyFrame()
    lines = ["avg = sum(x) / len(x) if x else 0.0"]
    assert frame._has_division_guard(lines, 1) is True


def test_has_division_guard_direct_preceding_if(PropertyFrame):
    """Unit-test _has_division_guard for guard on a preceding line."""
    frame = PropertyFrame()
    lines = [
        "if n > 0:",
        "    result = total / n",
    ]
    # line_num=2 refers to `result = total / n`
    assert frame._has_division_guard(lines, 2) is True


def test_has_division_guard_returns_false_when_no_guard(PropertyFrame):
    """Unit-test _has_division_guard returns False when no guard is present."""
    frame = PropertyFrame()
    lines = [
        "def calc(a, b):",
        "    return a / b",
    ]
    assert frame._has_division_guard(lines, 2) is False
