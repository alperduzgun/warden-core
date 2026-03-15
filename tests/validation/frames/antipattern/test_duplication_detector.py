"""
Tests for DuplicationDetector.

Covers: identical functions, similar functions, dissimilar functions,
tiny functions (below MIN_FUNCTION_LINES), single function (no pair),
JS/TS detection, and normalisation behaviour.
"""

import pytest

from warden.ast.domain.enums import CodeLanguage
from warden.validation.domain.frame import CodeFile
from warden.validation.frames.antipattern.detectors.duplication_detector import (
    DuplicationDetector,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(content: str, path: str = "example.py") -> CodeFile:
    return CodeFile(path=path, content=content, language="python")


def _detect(content: str, path: str = "example.py", language: CodeLanguage = CodeLanguage.PYTHON):
    detector = DuplicationDetector()
    code_file = CodeFile(path=path, content=content, language=language.value)
    lines = content.split("\n")
    return detector.detect_regex(code_file, language, lines)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDuplicationDetectorIdentical:
    """Two identical functions must be flagged."""

    def test_identical_python_functions_detected(self):
        code = """\
def calculate_total(items):
    result = 0
    for item in items:
        result += item.price
    return result


def compute_total(items):
    result = 0
    for item in items:
        result += item.price
    return result
"""
        violations = _detect(code)
        assert len(violations) == 1
        v = violations[0]
        assert v.pattern_id == "code-duplication"
        assert "calculate_total" in v.message
        assert "compute_total" in v.message
        # Body tokens are identical so similarity should be 100%; function
        # names are excluded from the body comparison.
        assert "100%" in v.message or int(v.message.split("are ")[1].split("%")[0]) >= 80


class TestDuplicationDetectorSimilar:
    """Functions sharing >= 80% of tokens must be flagged."""

    def test_highly_similar_functions_detected(self):
        # Functions differ only in one identifier out of many shared tokens;
        # body-only Jaccard similarity exceeds 80%.
        code = """\
def process_order_a(order, user, db, logger):
    validated = validate_input(order)
    record = db.fetch(user)
    result = apply_rules(validated, record)
    logger.info(result)
    return result


def process_order_b(order, user, db, logger):
    validated = validate_input(order)
    record = db.fetch(user)
    result = apply_rules(validated, record)
    logger.warning(result)
    return result
"""
        violations = _detect(code)
        assert len(violations) >= 1
        pattern_ids = [v.pattern_id for v in violations]
        assert "code-duplication" in pattern_ids


class TestDuplicationDetectorDissimilar:
    """Completely different functions must NOT be flagged."""

    def test_different_functions_not_detected(self):
        code = """\
def send_email(recipient, subject, body):
    smtp = connect_smtp()
    message = build_message(recipient, subject, body)
    smtp.send(message)
    smtp.close()
    return True


def parse_config(filepath):
    with open(filepath) as fh:
        raw = fh.read()
    data = json.loads(raw)
    validate_schema(data)
    return data
"""
        violations = _detect(code)
        dup_violations = [v for v in violations if v.pattern_id == "code-duplication"]
        assert len(dup_violations) == 0


class TestDuplicationDetectorMinLines:
    """Functions shorter than MIN_FUNCTION_LINES must be skipped."""

    def test_tiny_functions_skipped(self):
        # Each function body is fewer than 5 lines
        code = """\
def double(x):
    return x * 2


def triple(x):
    return x * 3
"""
        violations = _detect(code)
        dup_violations = [v for v in violations if v.pattern_id == "code-duplication"]
        assert len(dup_violations) == 0


class TestDuplicationDetectorSingleFunction:
    """A file with only one function has no pair to compare."""

    def test_single_function_no_finding(self):
        code = """\
def process_order(order_id):
    order = fetch_order(order_id)
    validate_order(order)
    charge_customer(order)
    send_confirmation(order)
    return order
"""
        violations = _detect(code)
        dup_violations = [v for v in violations if v.pattern_id == "code-duplication"]
        assert len(dup_violations) == 0


class TestDuplicationDetectorJavaScript:
    """Detector works for JavaScript function declarations."""

    def test_identical_js_functions_detected(self):
        code = """\
function calculateDiscount(price, rate) {
    const base = price * rate;
    const adjusted = base - (base * 0.1);
    const final = adjusted + (adjusted * 0.05);
    return final;
}

function computeDiscount(price, rate) {
    const base = price * rate;
    const adjusted = base - (base * 0.1);
    const final = adjusted + (adjusted * 0.05);
    return final;
}
"""
        violations = _detect(code, path="app.js", language=CodeLanguage.JAVASCRIPT)
        dup_violations = [v for v in violations if v.pattern_id == "code-duplication"]
        assert len(dup_violations) >= 1


class TestDuplicationDetectorNormalisation:
    """Comments and whitespace differences do not mask duplication."""

    def test_comment_differences_ignored(self):
        code = """\
def sum_values(numbers):
    # Calculate the total sum of all numbers
    total = 0
    for n in numbers:
        total += n
    return total


def add_values(numbers):
    # Adds all the numbers together and returns result
    total = 0
    for n in numbers:
        total += n
    return total
"""
        violations = _detect(code)
        dup_violations = [v for v in violations if v.pattern_id == "code-duplication"]
        assert len(dup_violations) == 1


class TestDuplicationDetectorViolationMetadata:
    """Violation fields are populated correctly."""

    def test_violation_fields(self):
        code = """\
def fetch_user(user_id):
    conn = get_connection()
    query = build_query(user_id)
    result = conn.execute(query)
    conn.close()
    return result


def load_user(user_id):
    conn = get_connection()
    query = build_query(user_id)
    result = conn.execute(query)
    conn.close()
    return result
"""
        violations = _detect(code, path="users/repo.py")
        assert len(violations) == 1
        v = violations[0]
        assert v.pattern_id == "code-duplication"
        assert v.file_path == "users/repo.py"
        assert v.line >= 1
        assert v.suggestion is not None
        assert "helper" in v.suggestion.lower() or "common" in v.suggestion.lower()
        assert v.is_blocker is False
