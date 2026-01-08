"""
Tests for SecurityFrame and its built-in checks.

Demonstrates the two-level plugin system in action.
"""

import pytest
from warden.validation.domain.frame import CodeFile

@pytest.fixture
def SecurityFrame():
    from warden.validation.infrastructure.frame_registry import FrameRegistry
    registry = FrameRegistry()
    registry.discover_all()
    cls = registry.get_frame_by_id("security")
    if not cls:
        pytest.skip("SecurityFrame not found in registry")
    return cls


@pytest.mark.asyncio
async def test_security_frame_sql_injection_detection(SecurityFrame):
    """Test SecurityFrame detects SQL injection."""
    code = '''
import sqlite3

def get_user(user_id):
    # BAD: SQL injection vulnerability
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
    return cursor.fetchone()
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = SecurityFrame()
    result = await frame.execute(code_file)

    # Should detect SQL injection
    assert result.status == "failed"  # Critical issue
    assert result.is_blocker is True  # Should block PR
    assert result.issues_found > 0

    # Should have SQL injection finding
    sql_findings = [f for f in result.findings if "SQL injection" in f.message]
    assert len(sql_findings) > 0
    assert sql_findings[0].severity == "critical"


@pytest.mark.asyncio
async def test_security_frame_secrets_detection(SecurityFrame):
    """Test SecurityFrame detects hardcoded secrets."""
    code = '''
import openai

# BAD: Hardcoded API key
OPENAI_API_KEY = "sk-1234567890abcdefghijklmnopqrstuvwxyz123456789012"

def call_api():
    client = openai.Client(api_key=OPENAI_API_KEY)
    return client.chat.completions.create(...)
'''

    code_file = CodeFile(
        path="api.py",
        content=code,
        language="python",
    )

    frame = SecurityFrame()
    result = await frame.execute(code_file)

    # Should detect secret
    assert result.status == "failed"
    assert result.is_blocker is True
    assert result.issues_found > 0

    # Should have secrets finding
    secret_findings = [f for f in result.findings if "secret" in f.message.lower()]
    assert len(secret_findings) > 0


@pytest.mark.asyncio
async def test_security_frame_xss_detection(SecurityFrame):
    """Test SecurityFrame detects XSS vulnerabilities."""
    code = '''
// BAD: XSS vulnerability
function displayMessage(message) {
    document.getElementById('output').innerHTML = message;  // XSS risk!
}

// User input goes directly into HTML
displayMessage(userInput);
'''

    code_file = CodeFile(
        path="app.js",
        content=code,
        language="javascript",
    )

    frame = SecurityFrame()
    result = await frame.execute(code_file)

    # Should detect XSS
    assert result.status in ["failed", "warning"]  # High severity
    assert result.issues_found > 0

    # Should have XSS finding
    xss_findings = [f for f in result.findings if "XSS" in f.message or "innerHTML" in f.message]
    assert len(xss_findings) > 0


@pytest.mark.asyncio
async def test_security_frame_hardcoded_password_detection(SecurityFrame):
    """Test SecurityFrame detects hardcoded passwords."""
    code = '''
class DatabaseConfig:
    def __init__(self):
        # BAD: Hardcoded password
        self.password = "admin123"
        self.username = "root"
        self.host = "localhost"
'''

    code_file = CodeFile(
        path="config.py",
        content=code,
        language="python",
    )

    frame = SecurityFrame()
    result = await frame.execute(code_file)

    # Should detect hardcoded password
    assert result.status == "failed"
    assert result.is_blocker is True
    assert result.issues_found > 0


@pytest.mark.asyncio
async def test_security_frame_passes_clean_code(SecurityFrame):
    """Test SecurityFrame passes clean, secure code."""
    code = '''
import os
import sqlite3

def get_user(user_id: str):
    # GOOD: Parameterized query (no SQL injection)
    query = "SELECT * FROM users WHERE id = ?"
    cursor.execute(query, (user_id,))
    return cursor.fetchone()

def get_api_key():
    # GOOD: Secret from environment variable
    return os.getenv("OPENAI_API_KEY")

def display_message(message: str):
    # GOOD: textContent is safe (no XSS)
    element = document.getElementById('output')
    element.textContent = message
'''

    code_file = CodeFile(
        path="secure.py",
        content=code,
        language="python",
    )

    frame = SecurityFrame()
    result = await frame.execute(code_file)

    # Should pass all checks
    assert result.status == "passed"
    assert result.is_blocker is False
    assert result.issues_found == 0


@pytest.mark.asyncio
async def test_security_frame_check_registry(SecurityFrame):
    """Test SecurityFrame has all built-in checks registered."""
    frame = SecurityFrame()

    # Should have 4 built-in checks
    all_checks = frame.checks.get_all()
    assert len(all_checks) >= 4

    # Check IDs should be present
    check_ids = [check.id for check in all_checks]
    assert "sql-injection" in check_ids
    assert "xss" in check_ids
    assert "secrets" in check_ids
    assert "hardcoded-password" in check_ids


@pytest.mark.asyncio
async def test_security_frame_metadata(SecurityFrame):
    """Test SecurityFrame has correct metadata."""
    frame = SecurityFrame()

    assert frame.name == "Security Analysis"
    assert frame.frame_id == "security"
    assert frame.is_blocker is True
    assert frame.priority.value == 1  # CRITICAL = 1


@pytest.mark.asyncio
async def test_security_frame_result_structure(SecurityFrame):
    """Test SecurityFrame result has correct structure (Panel compatibility)."""
    code = '''
password = "admin123"  # Hardcoded password
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = SecurityFrame()
    result = await frame.execute(code_file)

    # Test Panel JSON compatibility
    json_data = result.to_json()

    # Check required Panel fields (camelCase)
    assert "frameId" in json_data
    assert "frameName" in json_data
    assert "status" in json_data
    assert "duration" in json_data
    assert "issuesFound" in json_data
    assert "isBlocker" in json_data
    assert "findings" in json_data
    assert "metadata" in json_data

    # Check metadata contains check results
    assert "check_results" in json_data["metadata"]
    assert isinstance(json_data["metadata"]["check_results"], list)
