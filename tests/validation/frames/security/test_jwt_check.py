"""
Tests for JWTMisconfigCheck - JWT Misconfiguration Detection.

Covers:
- JS jwt.sign() without expiresIn (CWE-613)
- JS jwt.verify() with algorithms: ['none'] (CWE-345)
- Python jwt.encode() without exp claim (CWE-613)
- Python jwt.decode() without algorithms parameter
- Generic algorithm 'none' detection
- Clean code (no false positives)
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


def _get_jwt_findings(findings):
    """Filter findings to only jwt-misconfiguration check results.

    Frame-level Finding objects use 'id' like 'security-jwt-misconfiguration-N'.
    We match on 'jwt-misconfiguration' substring in the finding id.
    """
    return [f for f in findings if "jwt-misconfiguration" in f.id]


# =========================================================================
# JS: jwt.sign() without expiresIn
# =========================================================================

@pytest.mark.asyncio
async def test_js_jwt_sign_no_expiry(SecurityFrame):
    """jwt.sign(payload, secret) without expiresIn should be flagged."""
    code = '''
const jwt = require('jsonwebtoken');

function generateToken(user) {
    return jwt.sign({ userId: user.id }, 'my-secret');
}
'''
    code_file = CodeFile(path="auth.js", content=code, language="javascript")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    jwt_findings = _get_jwt_findings(result.findings)
    assert len(jwt_findings) >= 1
    assert any("CWE-613" in f.message for f in jwt_findings)


@pytest.mark.asyncio
async def test_js_jwt_sign_with_expiry_not_flagged(SecurityFrame):
    """jwt.sign() with expiresIn should NOT be flagged."""
    code = '''
const jwt = require('jsonwebtoken');

function generateToken(user) {
    return jwt.sign({ userId: user.id }, 'my-secret', { expiresIn: '1h' });
}
'''
    code_file = CodeFile(path="auth.js", content=code, language="javascript")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    jwt_findings = _get_jwt_findings(result.findings)
    expiry_findings = [f for f in jwt_findings if "CWE-613" in f.message]
    assert len(expiry_findings) == 0


@pytest.mark.asyncio
async def test_js_jwt_sign_with_exp_claim_not_flagged(SecurityFrame):
    """jwt.sign() with exp in payload should NOT be flagged."""
    code = '''
const jwt = require('jsonwebtoken');

function generateToken(user) {
    const payload = {
        userId: user.id,
        exp: Math.floor(Date.now() / 1000) + 3600
    };
    return jwt.sign(payload, 'my-secret');
}
'''
    code_file = CodeFile(path="auth.js", content=code, language="javascript")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    jwt_findings = _get_jwt_findings(result.findings)
    expiry_findings = [f for f in jwt_findings if "CWE-613" in f.message]
    assert len(expiry_findings) == 0


# =========================================================================
# JS: jwt.verify() with algorithms: ['none']
# =========================================================================

@pytest.mark.asyncio
async def test_js_jwt_verify_algo_none(SecurityFrame):
    """jwt.verify() with algorithms: ['none'] should be flagged as CRITICAL."""
    code = '''
const jwt = require('jsonwebtoken');

function verifyToken(token) {
    return jwt.verify(token, '', { algorithms: ['none'] });
}
'''
    code_file = CodeFile(path="auth.js", content=code, language="javascript")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    jwt_findings = _get_jwt_findings(result.findings)
    assert len(jwt_findings) >= 1
    none_findings = [f for f in jwt_findings if "CWE-345" in f.message]
    assert len(none_findings) >= 1
    assert any(f.severity == "critical" for f in none_findings)


@pytest.mark.asyncio
async def test_js_jwt_verify_with_hs256_not_flagged(SecurityFrame):
    """jwt.verify() with algorithms: ['HS256'] should NOT flag algorithm confusion."""
    code = '''
const jwt = require('jsonwebtoken');

function verifyToken(token) {
    return jwt.verify(token, process.env.JWT_SECRET, { algorithms: ['HS256'] });
}
'''
    code_file = CodeFile(path="auth.js", content=code, language="javascript")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    jwt_findings = _get_jwt_findings(result.findings)
    none_findings = [f for f in jwt_findings if "CWE-345" in f.message]
    assert len(none_findings) == 0


# =========================================================================
# Python: jwt.encode() without exp
# =========================================================================

@pytest.mark.asyncio
async def test_py_jwt_encode_no_exp(SecurityFrame):
    """jwt.encode() without exp claim should be flagged."""
    code = '''
import jwt

def create_token(user_id):
    payload = {"sub": user_id, "name": "John"}
    return jwt.encode(payload, "secret", algorithm="HS256")
'''
    code_file = CodeFile(path="auth.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    jwt_findings = _get_jwt_findings(result.findings)
    assert len(jwt_findings) >= 1
    assert any("CWE-613" in f.message for f in jwt_findings)


@pytest.mark.asyncio
async def test_py_jwt_encode_with_exp_not_flagged(SecurityFrame):
    """jwt.encode() with exp claim should NOT be flagged."""
    code = '''
import jwt
from datetime import datetime, timedelta

def create_token(user_id):
    payload = {
        "sub": user_id,
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    return jwt.encode(payload, "secret", algorithm="HS256")
'''
    code_file = CodeFile(path="auth.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    jwt_findings = _get_jwt_findings(result.findings)
    expiry_findings = [f for f in jwt_findings if "CWE-613" in f.message]
    assert len(expiry_findings) == 0


# =========================================================================
# Python: jwt.decode() without algorithms
# =========================================================================

@pytest.mark.asyncio
async def test_py_jwt_decode_no_algorithms(SecurityFrame):
    """jwt.decode() without algorithms parameter should be flagged."""
    code = '''
import jwt

def verify_token(token):
    return jwt.decode(token, "secret")
'''
    code_file = CodeFile(path="auth.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    jwt_findings = _get_jwt_findings(result.findings)
    assert len(jwt_findings) >= 1
    assert any("algorithm enforcement" in f.message for f in jwt_findings)


@pytest.mark.asyncio
async def test_py_jwt_decode_with_algorithms_not_flagged(SecurityFrame):
    """jwt.decode() with algorithms=['HS256'] should NOT be flagged."""
    code = '''
import jwt

def verify_token(token):
    return jwt.decode(token, "secret", algorithms=["HS256"])
'''
    code_file = CodeFile(path="auth.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    jwt_findings = _get_jwt_findings(result.findings)
    algo_findings = [f for f in jwt_findings if "algorithm enforcement" in f.message]
    assert len(algo_findings) == 0


@pytest.mark.asyncio
async def test_py_jwt_decode_with_algo_none(SecurityFrame):
    """jwt.decode() with algorithms=['none'] should be flagged as CRITICAL."""
    code = '''
import jwt

def verify_token(token):
    return jwt.decode(token, "secret", algorithms=["none"])
'''
    code_file = CodeFile(path="auth.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    jwt_findings = _get_jwt_findings(result.findings)
    none_findings = [f for f in jwt_findings if "CWE-345" in f.message]
    assert len(none_findings) >= 1
    assert any(f.severity == "critical" for f in none_findings)


# =========================================================================
# Generic: algorithm 'none'
# =========================================================================

@pytest.mark.asyncio
async def test_generic_alg_none_detected(SecurityFrame):
    """Generic 'alg': 'none' in headers should be flagged."""
    code = '''
header = {"alg": "none", "typ": "JWT"}
'''
    code_file = CodeFile(path="exploit.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    jwt_findings = _get_jwt_findings(result.findings)
    assert len(jwt_findings) >= 1
    assert any("CWE-345" in f.message for f in jwt_findings)


# =========================================================================
# Check registration
# =========================================================================

@pytest.mark.asyncio
async def test_jwt_check_registered_in_frame(SecurityFrame):
    """JWT misconfiguration check should be registered in SecurityFrame."""
    frame = SecurityFrame()
    check_ids = [c.id for c in frame.checks.get_all()]
    assert "jwt-misconfiguration" in check_ids


@pytest.mark.asyncio
async def test_crypto_check_registered_in_frame(SecurityFrame):
    """Weak crypto check should be registered in SecurityFrame."""
    frame = SecurityFrame()
    check_ids = [c.id for c in frame.checks.get_all()]
    assert "weak-crypto" in check_ids
