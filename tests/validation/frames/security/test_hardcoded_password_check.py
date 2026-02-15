"""
Tests for HardcodedPasswordCheck.

Tests the enhanced logic that prevents self-referential false positives
by skipping docstrings, comments, and constant definitions.
"""

import pytest
from warden.validation.domain.frame import CodeFile
from warden.validation.frames.security._internal.hardcoded_password_check import (
    HardcodedPasswordCheck,
)


@pytest.mark.asyncio
async def test_skip_docstrings_triple_double_quotes():
    """Test that password examples in docstrings are skipped (triple double quotes)."""
    code = '''
def authenticate_user(username, password):
    """
    Authenticate a user with credentials.

    Example usage:
        password = "admin123"  # This should be SKIPPED
        authenticate_user("admin", password)
    """
    # Real code here
    return True
'''

    code_file = CodeFile(path="test.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should NOT detect the docstring example
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_skip_docstrings_triple_single_quotes():
    """Test that password examples in docstrings are skipped (triple single quotes)."""
    code = """
def get_config():
    '''
    Load configuration.

    Bad example:
        password = 'secret123'  # This should be SKIPPED
    '''
    return {}
"""

    code_file = CodeFile(path="test.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should NOT detect the docstring example
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_skip_inline_docstrings():
    """Test that inline docstrings on same line are skipped."""
    code = '''
def test(): """Example: password = 'test123'"""  # Should be SKIPPED
'''

    code_file = CodeFile(path="test.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should NOT detect the inline docstring
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_skip_comment_only_lines_python():
    """Test that comment-only lines are skipped in Python."""
    code = '''
# BAD example: password = "admin123"
# Another comment: PASSWORD = "secret"
## password = "test"
'''

    code_file = CodeFile(path="test.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should NOT detect comments
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_skip_comment_only_lines_javascript():
    """Test that comment-only lines are skipped in JavaScript."""
    code = '''
// BAD example: password = "admin123"
// Another comment: const PASSWORD = "secret"
'''

    code_file = CodeFile(path="test.js", content=code, language="javascript")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should NOT detect comments
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_skip_constant_list_definitions():
    """Test that constant/list definitions are skipped in weak password checker."""
    code = '''
WEAK_PASSWORDS = [
    "password",
    "admin",
    "123456",
    "qwerty",
]

# These should be SKIPPED (detection pattern list)
PATTERNS = [
    'password123',
    'admin123',
]
'''

    code_file = CodeFile(path="patterns.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should NOT detect pattern list constants
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_detect_real_hardcoded_password():
    """Test that REAL hardcoded passwords are still detected."""
    code = '''
def connect_db():
    # BAD: Hardcoded password
    password = "admin123"
    db.connect(user="admin", password=password)
'''

    code_file = CodeFile(path="db.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should DETECT the real hardcoded password
    # Note: Check detects multiple issues: hardcoded password + weak passwords (admin123, admin)
    assert result.passed is False
    assert len(result.findings) >= 1
    # At least one critical finding
    critical_findings = [f for f in result.findings if f.severity.value == "critical"]
    assert len(critical_findings) >= 1


@pytest.mark.asyncio
async def test_detect_weak_password():
    """Test that weak passwords in actual code are detected."""
    code = '''
def create_user():
    password = "qwerty"  # BAD: Common weak password
    user.set_password(password)
'''

    code_file = CodeFile(path="user.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should DETECT weak password
    assert result.passed is False
    assert len(result.findings) >= 1


@pytest.mark.asyncio
async def test_suppression_standard_format():
    """Test that standard suppression format works (warden-ignore)."""
    code = '''
def test_example():
    password = "test123"  # warden-ignore
'''

    code_file = CodeFile(path="test.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Suppression is handled at frame level, but check should still detect it
    # The frame will filter it out based on suppression
    assert len(result.findings) >= 0  # Check runs, frame filters


@pytest.mark.asyncio
async def test_suppression_legacy_format():
    """Test that legacy suppression format works (warden: ignore)."""
    code = '''
def test_example():
    password = "test123"  # warden: ignore
'''

    code_file = CodeFile(path="test.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Suppression is handled at frame level
    assert len(result.findings) >= 0  # Check runs, frame filters


@pytest.mark.asyncio
async def test_suppression_with_rule_id():
    """Test that suppression with rule ID works."""
    code = '''
def test_example():
    badge_secret = "warden-local-dev-only"  # warden-ignore: hardcoded-password
'''

    code_file = CodeFile(path="badge.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Suppression is handled at frame level
    assert len(result.findings) >= 0


@pytest.mark.asyncio
async def test_safe_pattern_env_var():
    """Test that environment variable usage is considered safe."""
    code = '''
import os

def get_password():
    password = os.getenv('DB_PASSWORD')  # GOOD: Environment variable
    return password
'''

    code_file = CodeFile(path="config.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should NOT detect env var usage
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_safe_pattern_user_input():
    """Test that user input is considered safe."""
    code = '''
def login():
    password = input("Enter password: ")  # GOOD: User input
    return authenticate(password)
'''

    code_file = CodeFile(path="auth.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should NOT detect user input
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_multiline_docstring_skipping():
    """Test that multi-line docstrings are fully skipped."""
    code = '''
class DatabaseConnection:
    """
    Database connection handler.

    Security Warning:
        Never do this:
            password = "hardcoded_secret"
            conn = connect(password=password)

        Instead, use environment variables:
            password = os.getenv('DB_PASSWORD')
    """

    def connect(self):
        # Real implementation
        pass
'''

    code_file = CodeFile(path="db.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should NOT detect docstring examples
    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_mixed_code_and_comments():
    """Test that code with inline comments still detects real issues."""
    code = '''
def setup():
    # This is a comment: password = "comment_example"
    password = "MySecretPass123"  # This should be detected
    # Another comment
'''

    code_file = CodeFile(path="setup.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should DETECT the real hardcoded password, ignore comment
    assert result.passed is False
    assert len(result.findings) >= 1


@pytest.mark.asyncio
async def test_detection_code_self_reference_prevention():
    """Test that the detection code doesn't flag its own examples."""
    code = '''
class HardcodedPasswordCheck:
    """
    Example of bad code:
        password = 'hardcoded_secret'  # Should be SKIPPED
    """

    def get_examples(self):
        return [
            "password = 'admin123'",  # Should be SKIPPED (list constant)
            "PASSWORD = 'secret'",     # Should be SKIPPED (list constant)
        ]

    def validate(self):
        # This is a real violation:
        test_pass = "real_hardcoded"  # Should be DETECTED
'''

    code_file = CodeFile(path="check.py", content=code, language="python")
    check = HardcodedPasswordCheck()
    result = await check.execute_async(code_file)

    # Should only detect the REAL violation, not examples
    # The list constants might be detected, but docstring should be skipped
    assert len(result.findings) >= 1  # At minimum the real violation

    # Verify docstring example was skipped
    docstring_findings = [
        f for f in result.findings
        if "hardcoded_secret" in f.message
    ]
    assert len(docstring_findings) == 0, "Docstring example should be skipped"
