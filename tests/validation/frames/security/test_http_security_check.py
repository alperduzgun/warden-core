"""
Tests for HTTPSecurityCheck.

Tests HTTP security misconfiguration detection:
- CORS wildcard/permissive configurations
- Insecure cookie settings
- Missing helmet middleware
"""

import pytest
from warden.validation.domain.frame import CodeFile
from warden.validation.frames.security._internal.http_security_check import (
    HTTPSecurityCheck,
)


# ============================================================================
# CORS Detection Tests
# ============================================================================


@pytest.mark.asyncio
async def test_detect_express_cors_wildcard_origin():
    """Test detection of cors({ origin: '*' }) in Express."""
    code = """
const express = require('express');
const cors = require('cors');
const app = express();

app.use(cors({ origin: '*' }));

app.get('/api/data', (req, res) => {
    res.json({ data: 'test' });
});
"""

    code_file = CodeFile(path="server.js", content=code, language="javascript")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    cors_findings = [f for f in result.findings if "CORS" in f.message]
    assert len(cors_findings) >= 1
    assert "wildcard" in cors_findings[0].message.lower()


@pytest.mark.asyncio
async def test_detect_express_cors_no_config():
    """Test detection of app.use(cors()) without configuration."""
    code = """
const express = require('express');
const cors = require('cors');
const app = express();

app.use(cors());

app.get('/api/data', (req, res) => {
    res.json({ data: 'test' });
});
"""

    code_file = CodeFile(path="server.js", content=code, language="javascript")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    cors_findings = [f for f in result.findings if "CORS" in f.message]
    assert len(cors_findings) >= 1
    assert "without configuration" in cors_findings[0].message


@pytest.mark.asyncio
async def test_detect_django_cors_allow_all():
    """Test detection of CORS_ALLOW_ALL_ORIGINS = True in Django."""
    code = """
# Django settings
INSTALLED_APPS = [
    'django.contrib.admin',
    'corsheaders',
]

CORS_ALLOW_ALL_ORIGINS = True

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
]
"""

    code_file = CodeFile(path="settings.py", content=code, language="python")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    cors_findings = [f for f in result.findings if "CORS" in f.message]
    assert len(cors_findings) >= 1
    assert "all origins" in cors_findings[0].message.lower()


@pytest.mark.asyncio
async def test_detect_django_cors_legacy_setting():
    """Test detection of CORS_ORIGIN_ALLOW_ALL = True (legacy)."""
    code = """
CORS_ORIGIN_ALLOW_ALL = True
"""

    code_file = CodeFile(path="settings.py", content=code, language="python")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    cors_findings = [f for f in result.findings if "CORS" in f.message]
    assert len(cors_findings) >= 1


@pytest.mark.asyncio
async def test_detect_fastapi_cors_wildcard():
    """Test detection of allow_origins=["*"] in FastAPI."""
    code = """
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
"""

    code_file = CodeFile(path="main.py", content=code, language="python")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    cors_findings = [f for f in result.findings if "CORS" in f.message]
    assert len(cors_findings) >= 1
    assert "wildcard" in cors_findings[0].message.lower()


@pytest.mark.asyncio
async def test_pass_cors_specific_origins():
    """Test that specific CORS origins pass validation."""
    code = """
const express = require('express');
const cors = require('cors');
const app = express();

app.use(cors({ origin: ['https://myapp.com', 'https://admin.myapp.com'] }));

app.get('/api/data', (req, res) => {
    res.json({ data: 'test' });
});
"""

    code_file = CodeFile(path="server.js", content=code, language="javascript")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    # Should pass - no CORS findings (may have helmet findings)
    cors_findings = [f for f in result.findings if "CORS" in f.message]
    assert len(cors_findings) == 0


@pytest.mark.asyncio
async def test_skip_cors_in_comments():
    """Test that CORS patterns in comments are skipped."""
    code = """
# CORS_ALLOW_ALL_ORIGINS = True  # Don't do this!
// app.use(cors());  -- bad practice
"""

    code_file = CodeFile(path="notes.py", content=code, language="python")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is True
    assert len(result.findings) == 0


# ============================================================================
# Cookie Security Tests
# ============================================================================


@pytest.mark.asyncio
async def test_detect_django_session_cookie_insecure():
    """Test detection of SESSION_COOKIE_SECURE = False."""
    code = """
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_HTTPONLY = False
"""

    code_file = CodeFile(path="settings.py", content=code, language="python")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    cookie_findings = [f for f in result.findings if "cookie" in f.message.lower()]
    assert len(cookie_findings) >= 2


@pytest.mark.asyncio
async def test_detect_express_cookie_missing_flags():
    """Test detection of Express cookie without security flags."""
    code = """
const express = require('express');
const app = express();

app.get('/login', (req, res) => {
    res.cookie('session', 'abc123');
    res.send('OK');
});
"""

    code_file = CodeFile(path="server.js", content=code, language="javascript")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    cookie_findings = [f for f in result.findings if "cookie" in f.message.lower() or "Cookie" in f.message]
    assert len(cookie_findings) >= 1
    # Should detect missing secure, httpOnly, sameSite
    assert any("secure" in f.message.lower() for f in cookie_findings)


@pytest.mark.asyncio
async def test_pass_express_cookie_with_flags():
    """Test that Express cookie with all security flags passes."""
    code = """
const express = require('express');
const helmet = require('helmet');
const app = express();
app.use(helmet());

app.get('/login', (req, res) => {
    res.cookie('session', 'abc123', {
        secure: true,
        httpOnly: true,
        sameSite: 'strict'
    });
    res.send('OK');
});
"""

    code_file = CodeFile(path="server.js", content=code, language="javascript")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    # Cookie findings should be empty (all flags present)
    cookie_findings = [f for f in result.findings if "Cookie" in f.message or "cookie" in f.message.lower()]
    assert len(cookie_findings) == 0


@pytest.mark.asyncio
async def test_detect_python_set_cookie_missing_flags():
    """Test detection of set_cookie without security flags."""
    code = """
from flask import Flask, make_response

app = Flask(__name__)

@app.route('/login')
def login():
    response = make_response('OK')
    response.set_cookie('session', 'abc123')
    return response
"""

    code_file = CodeFile(path="app.py", content=code, language="python")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    cookie_findings = [f for f in result.findings if "cookie" in f.message.lower() or "Cookie" in f.message]
    assert len(cookie_findings) >= 1


@pytest.mark.asyncio
async def test_detect_django_session_cookie_samesite_none():
    """Test detection of SESSION_COOKIE_SAMESITE = None."""
    code = """
SESSION_COOKIE_SAMESITE = None
"""

    code_file = CodeFile(path="settings.py", content=code, language="python")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    cookie_findings = [f for f in result.findings if "SameSite" in f.message]
    assert len(cookie_findings) >= 1


# ============================================================================
# Missing Helmet Tests
# ============================================================================


@pytest.mark.asyncio
async def test_detect_express_without_helmet():
    """Test detection of Express app without helmet middleware."""
    code = """
const express = require('express');
const app = express();

app.get('/api/data', (req, res) => {
    res.json({ data: 'test' });
});

app.listen(3000);
"""

    code_file = CodeFile(path="server.js", content=code, language="javascript")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    helmet_findings = [f for f in result.findings if "helmet" in f.message.lower()]
    assert len(helmet_findings) >= 1


@pytest.mark.asyncio
async def test_pass_express_with_helmet():
    """Test that Express app with helmet passes."""
    code = """
const express = require('express');
const helmet = require('helmet');
const app = express();

app.use(helmet());

app.get('/api/data', (req, res) => {
    res.json({ data: 'test' });
});

app.listen(3000);
"""

    code_file = CodeFile(path="server.js", content=code, language="javascript")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    # No helmet findings
    helmet_findings = [f for f in result.findings if "helmet" in f.message.lower()]
    assert len(helmet_findings) == 0


@pytest.mark.asyncio
async def test_skip_helmet_check_non_express():
    """Test that helmet check is skipped for non-Express files."""
    code = """
from fastapi import FastAPI

app = FastAPI()

@app.get('/api/data')
async def get_data():
    return {"data": "test"}
"""

    code_file = CodeFile(path="main.py", content=code, language="python")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    # No helmet findings for Python
    helmet_findings = [f for f in result.findings if "helmet" in f.message.lower()]
    assert len(helmet_findings) == 0


@pytest.mark.asyncio
async def test_detect_express_esm_without_helmet():
    """Test detection of Express ESM import without helmet."""
    code = """
import express from 'express';
const app = express();

app.get('/api/data', (req, res) => {
    res.json({ data: 'test' });
});

app.listen(3000);
"""

    code_file = CodeFile(path="server.mjs", content=code, language="javascript")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    helmet_findings = [f for f in result.findings if "helmet" in f.message.lower()]
    assert len(helmet_findings) >= 1


# ============================================================================
# Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_clean_code_passes():
    """Test that clean code with no HTTP security issues passes."""
    code = """
def calculate(a, b):
    return a + b

result = calculate(1, 2)
print(result)
"""

    code_file = CodeFile(path="utils.py", content=code, language="python")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_check_metadata():
    """Test that check has correct metadata."""
    check = HTTPSecurityCheck()

    assert check.id == "http-security"
    assert check.name == "HTTP Security Misconfiguration Detection"
    assert check.severity.value == "high"
    assert check.enabled_by_default is True


@pytest.mark.asyncio
async def test_detect_access_control_allow_origin_wildcard():
    """Test detection of Access-Control-Allow-Origin: * header."""
    code = """
from flask import Flask

app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response
"""

    code_file = CodeFile(path="app.py", content=code, language="python")
    check = HTTPSecurityCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    cors_findings = [f for f in result.findings if "CORS" in f.message or "Access-Control" in f.message]
    assert len(cors_findings) >= 1
