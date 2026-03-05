"""
Tests for CSRFCheck.

Tests CSRF protection detection:
- Django @csrf_exempt usage
- Missing CsrfViewMiddleware in Django MIDDLEWARE
- Flask without flask-wtf CSRFProtect
- Express without csurf or equivalent
"""

import pytest
from warden.validation.domain.frame import CodeFile
from warden.validation.frames.security._internal.csrf_check import CSRFCheck


# ============================================================================
# Django CSRF Tests
# ============================================================================


@pytest.mark.asyncio
async def test_detect_django_csrf_exempt():
    """Test detection of @csrf_exempt decorator."""
    code = """
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

@csrf_exempt
def webhook_handler(request):
    if request.method == 'POST':
        data = request.body
        return JsonResponse({'status': 'ok'})
"""

    code_file = CodeFile(path="views.py", content=code, language="python")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    assert any("csrf_exempt" in f.message.lower() for f in result.findings)


@pytest.mark.asyncio
async def test_detect_django_csrf_exempt_with_function_name():
    """Test that @csrf_exempt finding includes function name."""
    code = """
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def payment_process(request):
    return JsonResponse({'status': 'ok'})
"""

    code_file = CodeFile(path="views.py", content=code, language="python")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    # Should include function name in message
    assert any("payment_process" in f.message for f in result.findings)


@pytest.mark.asyncio
async def test_detect_django_missing_csrf_middleware():
    """Test detection of missing CsrfViewMiddleware in MIDDLEWARE."""
    code = """
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]
"""

    code_file = CodeFile(path="settings.py", content=code, language="python")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    assert any("CsrfViewMiddleware" in f.message for f in result.findings)
    # Missing middleware should be CRITICAL
    assert any(f.severity.value == "critical" for f in result.findings)


@pytest.mark.asyncio
async def test_pass_django_with_csrf_middleware():
    """Test that Django settings with CsrfViewMiddleware passes."""
    code = """
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
]
"""

    code_file = CodeFile(path="settings.py", content=code, language="python")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    # Should not detect missing middleware
    middleware_findings = [f for f in result.findings if "CsrfViewMiddleware" in f.message]
    assert len(middleware_findings) == 0


@pytest.mark.asyncio
async def test_skip_csrf_exempt_in_comments():
    """Test that @csrf_exempt in comments is skipped."""
    code = """
# @csrf_exempt  -- don't use this!
# from django.views.decorators.csrf import csrf_exempt

def my_view(request):
    return JsonResponse({'status': 'ok'})
"""

    code_file = CodeFile(path="views.py", content=code, language="python")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_detect_multiple_csrf_exempt_views():
    """Test detection of multiple @csrf_exempt decorators."""
    code = """
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def api_webhook(request):
    return JsonResponse({'status': 'ok'})

@csrf_exempt
def api_callback(request):
    return JsonResponse({'status': 'ok'})
"""

    code_file = CodeFile(path="views.py", content=code, language="python")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    csrf_exempt_findings = [f for f in result.findings if "csrf_exempt" in f.message.lower()]
    assert len(csrf_exempt_findings) >= 2


# ============================================================================
# Flask CSRF Tests
# ============================================================================


@pytest.mark.asyncio
async def test_detect_flask_without_csrf():
    """Test detection of Flask app without CSRFProtect."""
    code = """
from flask import Flask

app = Flask(__name__)

@app.route('/submit', methods=['POST'])
def submit():
    return 'OK'
"""

    code_file = CodeFile(path="app.py", content=code, language="python")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    assert any("flask" in f.message.lower() and "csrf" in f.message.lower() for f in result.findings)


@pytest.mark.asyncio
async def test_pass_flask_with_csrf_protect():
    """Test that Flask app with CSRFProtect passes."""
    code = """
from flask import Flask
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
csrf = CSRFProtect(app)

@app.route('/submit', methods=['POST'])
def submit():
    return 'OK'
"""

    code_file = CodeFile(path="app.py", content=code, language="python")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    # No Flask CSRF findings
    flask_csrf_findings = [f for f in result.findings if "flask" in f.message.lower()]
    assert len(flask_csrf_findings) == 0


@pytest.mark.asyncio
async def test_pass_flask_with_csrf_import():
    """Test that Flask app with CSRFProtect import passes."""
    code = """
from flask import Flask
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)

# CSRFProtect initialized elsewhere
"""

    code_file = CodeFile(path="app.py", content=code, language="python")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    flask_csrf_findings = [f for f in result.findings if "flask" in f.message.lower()]
    assert len(flask_csrf_findings) == 0


# ============================================================================
# Express CSRF Tests
# ============================================================================


@pytest.mark.asyncio
async def test_detect_express_without_csrf():
    """Test detection of Express app without CSRF protection."""
    code = """
const express = require('express');
const app = express();

app.post('/api/transfer', (req, res) => {
    // Transfer money
    res.json({ success: true });
});

app.listen(3000);
"""

    code_file = CodeFile(path="server.js", content=code, language="javascript")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    assert any("csrf" in f.message.lower() for f in result.findings)


@pytest.mark.asyncio
async def test_pass_express_with_csurf():
    """Test that Express app with csurf passes."""
    code = """
const express = require('express');
const csurf = require('csurf');
const app = express();

app.use(csurf({ cookie: true }));

app.post('/api/transfer', (req, res) => {
    res.json({ success: true });
});

app.listen(3000);
"""

    code_file = CodeFile(path="server.js", content=code, language="javascript")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_pass_express_with_csrf_token():
    """Test that Express app with csrfToken usage passes."""
    code = """
const express = require('express');
const app = express();

// Custom CSRF middleware
app.use((req, res, next) => {
    const csrfToken = req.headers['x-csrf-token'];
    if (req.method === 'POST' && !csrfToken) {
        return res.status(403).json({ error: 'Missing CSRF token' });
    }
    next();
});

app.post('/api/data', (req, res) => {
    res.json({ success: true });
});
"""

    code_file = CodeFile(path="server.js", content=code, language="javascript")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    # Should pass - has CSRF token handling
    assert result.passed is True


@pytest.mark.asyncio
async def test_pass_express_get_only():
    """Test that Express app with only GET routes passes (no state change)."""
    code = """
const express = require('express');
const app = express();

app.get('/api/data', (req, res) => {
    res.json({ data: 'test' });
});

app.listen(3000);
"""

    code_file = CodeFile(path="server.js", content=code, language="javascript")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    # No CSRF findings for GET-only apps
    csrf_findings = [f for f in result.findings if "csrf" in f.message.lower()]
    assert len(csrf_findings) == 0


@pytest.mark.asyncio
async def test_detect_express_esm_without_csrf():
    """Test detection of Express ESM app without CSRF."""
    code = """
import express from 'express';
const app = express();

app.put('/api/users/:id', (req, res) => {
    res.json({ updated: true });
});

app.listen(3000);
"""

    code_file = CodeFile(path="server.mjs", content=code, language="javascript")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    csrf_findings = [f for f in result.findings if "csrf" in f.message.lower()]
    assert len(csrf_findings) >= 1


# ============================================================================
# Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_clean_code_passes():
    """Test that clean non-web code passes."""
    code = """
def calculate(a, b):
    return a + b

result = calculate(1, 2)
print(result)
"""

    code_file = CodeFile(path="utils.py", content=code, language="python")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_check_metadata():
    """Test that check has correct metadata."""
    check = CSRFCheck()

    assert check.id == "csrf"
    assert check.name == "CSRF Protection Detection"
    assert check.severity.value == "high"
    assert check.enabled_by_default is True


@pytest.mark.asyncio
async def test_non_python_non_js_passes():
    """Test that non-Python/non-JS files are not checked."""
    code = """
package main

import "net/http"

func main() {
    http.HandleFunc("/api/data", handler)
    http.ListenAndServe(":8080", nil)
}
"""

    code_file = CodeFile(path="main.go", content=code, language="go")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    assert result.passed is True
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_django_csrf_exempt_async_view():
    """Test detection of @csrf_exempt on async Django view."""
    code = """
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
async def async_webhook(request):
    if request.method == 'POST':
        return JsonResponse({'status': 'ok'})
"""

    code_file = CodeFile(path="views.py", content=code, language="python")
    check = CSRFCheck()
    result = await check.execute_async(code_file)

    assert result.passed is False
    assert len(result.findings) >= 1
    # Should detect the async function name
    assert any("async_webhook" in f.message for f in result.findings)
