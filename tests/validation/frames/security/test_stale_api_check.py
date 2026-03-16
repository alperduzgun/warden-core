"""
Tests for StaleAPICheck - Deprecated API Detection.

Covers:
- Python deprecated APIs: hashlib.md5, pickle.loads, eval, yaml.load
- JavaScript deprecated APIs: new Buffer, fs.exists, crypto.createCipher
- Clean code with no findings (no false positives)
- Language isolation: Python patterns don't fire on JS files and vice versa
- Regex precision: eval word-boundary, yaml.load lookahead, removed overbroad patterns
"""

import pytest

from warden.validation.domain.frame import CodeFile
from warden.validation.frames.security._internal.stale_api_check import StaleAPICheck


@pytest.fixture
def check() -> StaleAPICheck:
    """Return a fresh StaleAPICheck instance."""
    return StaleAPICheck()


def _stale_findings(result):
    """Return all findings from a StaleAPICheck result."""
    return result.findings


# =============================================================================
# Python deprecated APIs
# =============================================================================


@pytest.mark.asyncio
async def test_python_hashlib_md5_detected(check):
    """hashlib.md5() in Python should be flagged as deprecated."""
    code = """
import hashlib

def hash_token(token):
    return hashlib.md5(token.encode()).hexdigest()
"""
    code_file = CodeFile(path="utils.py", content=code, language="python")
    result = await check.execute_async(code_file)
    findings = _stale_findings(result)
    assert len(findings) >= 1
    assert any("MD5" in f.message for f in findings)


@pytest.mark.asyncio
async def test_python_pickle_loads_detected(check):
    """pickle.loads() in Python should be flagged due to RCE risk."""
    code = """
import pickle

def deserialize(data):
    return pickle.loads(data)
"""
    code_file = CodeFile(path="serializer.py", content=code, language="python")
    result = await check.execute_async(code_file)
    findings = _stale_findings(result)
    assert len(findings) >= 1
    assert any("pickle" in f.message.lower() or "CWE-502" in f.message for f in findings)


@pytest.mark.asyncio
async def test_python_eval_detected(check):
    """eval() in Python should be flagged as dangerous."""
    code = """
def process_input(user_input):
    result = eval(user_input)
    return result
"""
    code_file = CodeFile(path="processor.py", content=code, language="python")
    result = await check.execute_async(code_file)
    findings = _stale_findings(result)
    assert len(findings) >= 1
    assert any("eval" in f.message.lower() or "CWE-95" in f.message for f in findings)


@pytest.mark.asyncio
async def test_python_yaml_load_without_loader_detected(check):
    """yaml.load() without SafeLoader should be flagged."""
    code = """
import yaml

def parse_config(config_str):
    return yaml.load(config_str)
"""
    code_file = CodeFile(path="config.py", content=code, language="python")
    result = await check.execute_async(code_file)
    findings = _stale_findings(result)
    assert len(findings) >= 1
    assert any("yaml" in f.message.lower() or "SafeLoader" in f.message for f in findings)


@pytest.mark.asyncio
async def test_python_os_popen_detected(check):
    """os.popen() should be flagged as deprecated since Python 3.0."""
    code = """
import os

def run_command(cmd):
    output = os.popen(cmd).read()
    return output
"""
    code_file = CodeFile(path="runner.py", content=code, language="python")
    result = await check.execute_async(code_file)
    findings = _stale_findings(result)
    assert len(findings) >= 1
    assert any("popen" in f.message.lower() or "deprecated" in f.message.lower() for f in findings)


# =============================================================================
# JavaScript / Node.js deprecated APIs
# =============================================================================


@pytest.mark.asyncio
async def test_js_new_buffer_detected(check):
    """new Buffer() in Node.js should be flagged as deprecated."""
    code = """
function createBuffer(data) {
    const buf = new Buffer(data);
    return buf;
}
"""
    code_file = CodeFile(path="buffer_util.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    findings = _stale_findings(result)
    assert len(findings) >= 1
    assert any("Buffer" in f.message for f in findings)


@pytest.mark.asyncio
async def test_js_fs_exists_detected(check):
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
    result = await check.execute_async(code_file)
    findings = _stale_findings(result)
    assert len(findings) >= 1
    assert any("exists" in f.message.lower() or "deprecated" in f.message.lower() for f in findings)


@pytest.mark.asyncio
async def test_js_crypto_create_cipher_detected(check):
    """crypto.createCipher() in Node.js should be flagged as deprecated."""
    code = """
const crypto = require('crypto');

function encrypt(key, data) {
    const cipher = crypto.createCipher('aes-256-cbc', key);
    return cipher.update(data, 'utf8', 'hex') + cipher.final('hex');
}
"""
    code_file = CodeFile(path="crypto_util.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    findings = _stale_findings(result)
    assert len(findings) >= 1
    assert any("createCipher" in f.message or "IV" in f.message for f in findings)


# =============================================================================
# Clean code — no false positives
# =============================================================================


@pytest.mark.asyncio
async def test_clean_python_code_no_findings(check):
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
    result = await check.execute_async(code_file)
    assert len(_stale_findings(result)) == 0


@pytest.mark.asyncio
async def test_clean_js_code_no_findings(check):
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
    result = await check.execute_async(code_file)
    assert len(_stale_findings(result)) == 0


# =============================================================================
# Language isolation — patterns must not bleed across languages
# =============================================================================


@pytest.mark.asyncio
async def test_python_patterns_dont_match_js_files(check):
    """Python-specific patterns (hashlib.md5) must not fire on JS files."""
    code = """
// This is JavaScript — hashlib.md5 is a Python API, not JS
// The string hashlib.md5( appears in a comment only
function hashValue(val) {
    return val.toString();
}
"""
    code_file = CodeFile(path="helpers.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    findings = _stale_findings(result)
    python_md5_findings = [f for f in findings if "MD5" in f.message]
    assert len(python_md5_findings) == 0


@pytest.mark.asyncio
async def test_js_patterns_dont_match_python_files(check):
    """JS-specific patterns (new Buffer) must not fire on Python files."""
    code = """
# Python file — 'new Buffer(' is a Node.js API
# Mentioning new Buffer( in a comment should not fire
def process(data):
    return data
"""
    code_file = CodeFile(path="processor.py", content=code, language="python")
    result = await check.execute_async(code_file)
    findings = _stale_findings(result)
    buffer_findings = [f for f in findings if "Buffer" in f.message]
    assert len(buffer_findings) == 0


# =============================================================================
# Regex precision — Copilot review fixes
# =============================================================================


@pytest.mark.asyncio
async def test_yaml_load_with_loader_not_flagged(check):
    """yaml.load(data, Loader=yaml.SafeLoader) must NOT be flagged."""
    code = """
import yaml

def parse_safe(data):
    return yaml.load(data, Loader=yaml.SafeLoader)
"""
    code_file = CodeFile(path="safe_config.py", content=code, language="python")
    result = await check.execute_async(code_file)
    yaml_findings = [f for f in _stale_findings(result) if "yaml" in f.message.lower()]
    assert len(yaml_findings) == 0, (
        "yaml.load with Loader= should not be flagged"
    )


@pytest.mark.asyncio
async def test_yaml_load_without_loader_multiword_args_flagged(check):
    """yaml.load(stream, encoding='utf-8') without Loader should still be flagged."""
    code = """
import yaml

def parse_config(stream):
    return yaml.load(stream, encoding='utf-8')
"""
    code_file = CodeFile(path="config.py", content=code, language="python")
    result = await check.execute_async(code_file)
    yaml_findings = [f for f in _stale_findings(result) if "yaml" in f.message.lower()]
    assert len(yaml_findings) >= 1, (
        "yaml.load without Loader= should be flagged even with other args"
    )


@pytest.mark.asyncio
async def test_literal_eval_not_flagged(check):
    """ast.literal_eval() must NOT be flagged — word boundary prevents it."""
    code = """
import ast

def safe_parse(expr):
    return ast.literal_eval(expr)
"""
    code_file = CodeFile(path="parser.py", content=code, language="python")
    result = await check.execute_async(code_file)
    eval_findings = [f for f in _stale_findings(result) if "eval" in f.message.lower()]
    assert len(eval_findings) == 0, (
        "ast.literal_eval should not be flagged by eval pattern"
    )


@pytest.mark.asyncio
async def test_bare_eval_flagged(check):
    """Bare eval() call must still be flagged after word-boundary fix."""
    code = """
def dangerous(user_input):
    return eval(user_input)
"""
    code_file = CodeFile(path="bad.py", content=code, language="python")
    result = await check.execute_async(code_file)
    eval_findings = [f for f in _stale_findings(result) if "eval" in f.message.lower()]
    assert len(eval_findings) >= 1


@pytest.mark.asyncio
async def test_querystring_local_var_no_false_positive(check):
    """Local variable named querystring must NOT be flagged (pattern removed)."""
    code = """
function buildUrl(querystring) {
    return '/api?' + querystring;
}

const querystring = 'foo=bar';
console.log(buildUrl(querystring));
"""
    code_file = CodeFile(path="url_builder.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    qs_findings = [f for f in _stale_findings(result) if "querystring" in f.message.lower()]
    assert len(qs_findings) == 0, (
        "querystring pattern was removed to prevent false positives on local variables"
    )


@pytest.mark.asyncio
async def test_domain_local_var_no_false_positive(check):
    """Local variable 'domain' or 'domain.example.com' must NOT be flagged (pattern removed)."""
    code = """
const domain = 'example.com';
const url = `https://${domain}/api/v1`;
console.log(domain.toUpperCase());
"""
    code_file = CodeFile(path="config.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    domain_findings = [f for f in _stale_findings(result) if "domain" in f.message.lower()]
    assert len(domain_findings) == 0, (
        "domain pattern was removed to prevent false positives"
    )


@pytest.mark.asyncio
async def test_formatter_attribute_no_false_positive(check):
    """logging.Formatter or any .formatter attribute must NOT be flagged (pattern removed)."""
    code = """
import logging

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler = logging.StreamHandler()
handler.setFormatter(formatter)
"""
    code_file = CodeFile(path="logging_setup.py", content=code, language="python")
    result = await check.execute_async(code_file)
    fmt_findings = [f for f in _stale_findings(result) if "formatter" in f.message.lower()]
    assert len(fmt_findings) == 0, (
        "formatter pattern was removed to prevent false positives with logging.Formatter"
    )


@pytest.mark.asyncio
async def test_pattern_count():
    """Sanity check: exactly 14 patterns after removals."""
    check = StaleAPICheck()
    assert len(check.DEPRECATED_APIS) == 14, (
        f"Expected 14 patterns after removing formatter, querystring, domain; got {len(check.DEPRECATED_APIS)}"
    )
