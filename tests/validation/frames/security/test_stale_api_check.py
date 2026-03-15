"""
Tests for StaleAPICheck - Deprecated API Detection.

Covers:
- Python deprecated APIs: hashlib.md5, pickle.loads, eval, yaml.load
- JavaScript deprecated APIs: new Buffer, fs.exists, crypto.createCipher
- Clean code with no findings (no false positives)
- Language isolation: Python patterns don't fire on JS files and vice versa
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


def _get_stale_findings(findings):
    """Filter findings to only stale-api check results."""
    return [f for f in findings if "stale-api" in f.id]


# =============================================================================
# Python deprecated APIs
# =============================================================================


@pytest.mark.asyncio
async def test_python_hashlib_md5_detected(SecurityFrame):
    """hashlib.md5() in Python should be flagged as deprecated."""
    code = """
import hashlib

def hash_token(token):
    return hashlib.md5(token.encode()).hexdigest()
"""
    code_file = CodeFile(path="utils.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    stale = _get_stale_findings(result.findings)
    assert len(stale) >= 1
    assert any("MD5" in f.message for f in stale)


@pytest.mark.asyncio
async def test_python_pickle_loads_detected(SecurityFrame):
    """pickle.loads() in Python should be flagged due to RCE risk."""
    code = """
import pickle

def deserialize(data):
    return pickle.loads(data)
"""
    code_file = CodeFile(path="serializer.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    stale = _get_stale_findings(result.findings)
    assert len(stale) >= 1
    assert any("pickle" in f.message.lower() or "CWE-502" in f.message for f in stale)


@pytest.mark.asyncio
async def test_python_eval_detected(SecurityFrame):
    """eval() in Python should be flagged as dangerous."""
    code = """
def process_input(user_input):
    result = eval(user_input)
    return result
"""
    code_file = CodeFile(path="processor.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    stale = _get_stale_findings(result.findings)
    assert len(stale) >= 1
    assert any("eval" in f.message.lower() or "CWE-95" in f.message for f in stale)


@pytest.mark.asyncio
async def test_python_yaml_load_without_loader_detected(SecurityFrame):
    """yaml.load() without SafeLoader should be flagged."""
    code = """
import yaml

def parse_config(config_str):
    return yaml.load(config_str)
"""
    code_file = CodeFile(path="config.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    stale = _get_stale_findings(result.findings)
    assert len(stale) >= 1
    assert any("yaml" in f.message.lower() or "SafeLoader" in f.message for f in stale)


@pytest.mark.asyncio
async def test_python_os_popen_detected(SecurityFrame):
    """os.popen() should be flagged as deprecated since Python 3.0."""
    code = """
import os

def run_command(cmd):
    output = os.popen(cmd).read()
    return output
"""
    code_file = CodeFile(path="runner.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    stale = _get_stale_findings(result.findings)
    assert len(stale) >= 1
    assert any("popen" in f.message.lower() or "deprecated" in f.message.lower() for f in stale)


# =============================================================================
# JavaScript / Node.js deprecated APIs
# =============================================================================


@pytest.mark.asyncio
async def test_js_new_buffer_detected(SecurityFrame):
    """new Buffer() in Node.js should be flagged as deprecated."""
    code = """
function createBuffer(data) {
    const buf = new Buffer(data);
    return buf;
}
"""
    code_file = CodeFile(path="buffer_util.js", content=code, language="javascript")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    stale = _get_stale_findings(result.findings)
    assert len(stale) >= 1
    assert any("Buffer" in f.message for f in stale)


@pytest.mark.asyncio
async def test_js_fs_exists_detected(SecurityFrame):
    """fs.exists() in Node.js should be flagged as deprecated."""
    code = """
const fs = require('fs');

function checkFile(path) {
    fs.exists(path, (exists) => {
        console.log(exists);
    });
}
"""
    code_file = CodeFile(path="file_util.js", content=code, language="javascript")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    stale = _get_stale_findings(result.findings)
    assert len(stale) >= 1
    assert any("exists" in f.message.lower() or "deprecated" in f.message.lower() for f in stale)


@pytest.mark.asyncio
async def test_js_crypto_create_cipher_detected(SecurityFrame):
    """crypto.createCipher() in Node.js should be flagged as deprecated."""
    code = """
const crypto = require('crypto');

function encrypt(key, data) {
    const cipher = crypto.createCipher('aes-256-cbc', key);
    return cipher.update(data, 'utf8', 'hex') + cipher.final('hex');
}
"""
    code_file = CodeFile(path="crypto_util.js", content=code, language="javascript")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    stale = _get_stale_findings(result.findings)
    assert len(stale) >= 1
    assert any("createCipher" in f.message or "IV" in f.message for f in stale)


# =============================================================================
# Clean code — no false positives
# =============================================================================


@pytest.mark.asyncio
async def test_clean_python_code_no_findings(SecurityFrame):
    """Modern Python code should produce no stale-api findings."""
    code = """
import hashlib
import json
import subprocess

def hash_data(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()

def parse_safe(raw: str):
    return json.loads(raw)

def run_cmd(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout
"""
    code_file = CodeFile(path="modern_utils.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    stale = _get_stale_findings(result.findings)
    assert len(stale) == 0


@pytest.mark.asyncio
async def test_clean_js_code_no_findings(SecurityFrame):
    """Modern JavaScript code should produce no stale-api findings."""
    code = """
const crypto = require('crypto');
const { URL } = require('url');
const { URLSearchParams } = require('url');

function encrypt(key, iv, data) {
    const cipher = crypto.createCipheriv('aes-256-cbc', key, iv);
    return cipher.update(data, 'utf8', 'hex') + cipher.final('hex');
}

function parseUrl(rawUrl) {
    return new URL(rawUrl);
}

function buildQuery(params) {
    return new URLSearchParams(params).toString();
}
"""
    code_file = CodeFile(path="modern_crypto.js", content=code, language="javascript")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    stale = _get_stale_findings(result.findings)
    assert len(stale) == 0


# =============================================================================
# Language isolation — patterns must not bleed across languages
# =============================================================================


@pytest.mark.asyncio
async def test_python_patterns_dont_match_js_files(SecurityFrame):
    """Python-specific patterns (hashlib.md5) must not fire on JS files."""
    code = """
// This is JavaScript — hashlib.md5 is a Python API, not JS
// The string hashlib.md5( appears in a comment only
function hashValue(val) {
    return val.toString();
}
"""
    code_file = CodeFile(path="helpers.js", content=code, language="javascript")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    stale = _get_stale_findings(result.findings)
    # Comments aside, JS file should not trigger Python-only patterns
    # (comment text could match regex, but language filter prevents it)
    python_md5_findings = [f for f in stale if "MD5" in f.message and "hashlib" in (f.code_snippet or "")]
    assert len(python_md5_findings) == 0


@pytest.mark.asyncio
async def test_js_patterns_dont_match_python_files(SecurityFrame):
    """JS-specific patterns (new Buffer) must not fire on Python files."""
    code = """
# Python file — 'new Buffer(' is a Node.js API
# Mentioning new Buffer( in a comment should not fire
def process(data):
    return data
"""
    code_file = CodeFile(path="processor.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    stale = _get_stale_findings(result.findings)
    buffer_findings = [f for f in stale if "Buffer" in f.message]
    assert len(buffer_findings) == 0
