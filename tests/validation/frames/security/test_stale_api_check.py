"""
Tests for StaleAPICheck - Deprecated/Insecure API Detection.

Covers:
- yaml.load without Loader= flagged; yaml.load(s, Loader=...) NOT flagged
- eval() flagged; literal_eval() NOT flagged (word boundary)
- require('querystring') flagged; local variable named querystring NOT flagged
- domain. and formatter. patterns removed (no false positives)
- Python deprecated APIs: hashlib.md5/sha1, os.popen, cgi.parse, imp.load_module,
  optparse, pickle.loads
- JavaScript deprecated APIs: new Buffer(), fs.exists(), crypto.createCipher(),
  url.parse()
"""

import pytest

from warden.validation.domain.frame import CodeFile
from warden.validation.frames.security._internal.stale_api_check import StaleAPICheck


@pytest.fixture
def check():
    return StaleAPICheck()


# =========================================================================
# yaml.load — Copilot fix #1
# Pattern changed from r"yaml\.load\([^)]*\)(?!.*Loader)"
# to r"yaml\.load\((?!.*Loader)" to match the whole line
# =========================================================================

@pytest.mark.asyncio
async def test_yaml_load_without_loader_flagged(check):
    """yaml.load() without Loader kwarg must be flagged."""
    code = "data = yaml.load(stream)\n"
    code_file = CodeFile(path="config.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert not result.passed
    assert any("yaml" in f.code_snippet.lower() for f in result.findings)


@pytest.mark.asyncio
async def test_yaml_load_variable_arg_without_loader_flagged(check):
    """yaml.load called with a variable but no Loader= must be flagged."""
    code = "data = yaml.load(open('file.yml'))\n"
    code_file = CodeFile(path="config.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert not result.passed


@pytest.mark.asyncio
async def test_yaml_load_with_safe_loader_not_flagged(check):
    """yaml.load(s, Loader=yaml.SafeLoader) must NOT be flagged."""
    code = "data = yaml.load(stream, Loader=yaml.SafeLoader)\n"
    code_file = CodeFile(path="config.py", content=code, language="python")
    result = await check.execute_async(code_file)
    yaml_findings = [f for f in result.findings if "yaml" in f.code_snippet.lower()]
    assert len(yaml_findings) == 0, "yaml.load with SafeLoader should not be flagged"


@pytest.mark.asyncio
async def test_yaml_load_with_full_loader_not_flagged(check):
    """yaml.load(s, Loader=yaml.FullLoader) must NOT be flagged."""
    code = "data = yaml.load(content, Loader=yaml.FullLoader)\n"
    code_file = CodeFile(path="config.py", content=code, language="python")
    result = await check.execute_async(code_file)
    yaml_findings = [f for f in result.findings if "yaml" in f.code_snippet.lower()]
    assert len(yaml_findings) == 0


@pytest.mark.asyncio
async def test_yaml_safe_load_not_flagged(check):
    """yaml.safe_load() must never be flagged."""
    code = "data = yaml.safe_load(stream)\n"
    code_file = CodeFile(path="config.py", content=code, language="python")
    result = await check.execute_async(code_file)
    yaml_findings = [f for f in result.findings if "yaml" in f.code_snippet.lower()]
    assert len(yaml_findings) == 0


# =========================================================================
# eval() — Copilot fix #4 (word boundary (?<!\w))
# =========================================================================

@pytest.mark.asyncio
async def test_eval_flagged(check):
    """Bare eval() call must be flagged."""
    code = "result = eval(user_input)\n"
    code_file = CodeFile(path="utils.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert not result.passed
    assert any("eval" in f.code_snippet for f in result.findings)


@pytest.mark.asyncio
async def test_literal_eval_not_flagged(check):
    """ast.literal_eval() must NOT be flagged (word boundary guard)."""
    code = "import ast\nresult = ast.literal_eval(user_input)\n"
    code_file = CodeFile(path="utils.py", content=code, language="python")
    result = await check.execute_async(code_file)
    eval_findings = [
        f for f in result.findings
        if "literal_eval" in f.code_snippet
    ]
    assert len(eval_findings) == 0, "literal_eval should not be flagged"


# =========================================================================
# querystring — Copilot fix #2
# Pattern changed from r"querystring\." to r"require\(['\"]\querystring['\"]\)"
# =========================================================================

@pytest.mark.asyncio
async def test_require_querystring_double_quotes_flagged(check):
    """require("querystring") import must be flagged."""
    code = 'const qs = require("querystring");\n'
    code_file = CodeFile(path="routes.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    assert not result.passed
    assert any("querystring" in f.code_snippet for f in result.findings)


@pytest.mark.asyncio
async def test_require_querystring_single_quotes_flagged(check):
    """require('querystring') with single quotes must also be flagged."""
    code = "const qs = require('querystring');\n"
    code_file = CodeFile(path="routes.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    assert not result.passed


@pytest.mark.asyncio
async def test_querystring_local_variable_not_flagged(check):
    """A local variable named querystring must NOT trigger the check."""
    code = "const querystring = {};\nquerystring.key = 'value';\n"
    code_file = CodeFile(path="routes.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    qs_findings = [f for f in result.findings if "querystring" in f.code_snippet]
    assert len(qs_findings) == 0, "local querystring variable should not be flagged"


@pytest.mark.asyncio
async def test_querystring_method_call_not_flagged(check):
    """querystring.stringify(...) on a local var must NOT be flagged."""
    code = "const result = querystring.stringify(params);\n"
    code_file = CodeFile(path="api.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    qs_findings = [f for f in result.findings if "querystring" in f.code_snippet]
    assert len(qs_findings) == 0, "querystring.stringify should not be flagged"


# =========================================================================
# domain module removed — Copilot fix #3 (pattern too broad, YAGNI)
# =========================================================================

@pytest.mark.asyncio
async def test_domain_module_usage_not_flagged(check):
    """domain module usage must NOT be flagged (pattern removed as overbroad)."""
    code = "const domain = require('domain');\ndomain.create();\n"
    code_file = CodeFile(path="server.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    domain_findings = [f for f in result.findings if "domain" in f.code_snippet]
    assert len(domain_findings) == 0, "domain pattern was removed; should not flag"


# =========================================================================
# formatter module removed — Copilot fix #3 (pattern too broad, YAGNI)
# =========================================================================

@pytest.mark.asyncio
async def test_formatter_logging_not_flagged(check):
    """logging.Formatter usage must NOT be flagged (formatter. pattern removed)."""
    code = "import logging\nformatter = logging.Formatter('%(message)s')\n"
    code_file = CodeFile(path="log_setup.py", content=code, language="python")
    result = await check.execute_async(code_file)
    fmt_findings = [f for f in result.findings if "formatter" in f.code_snippet]
    assert len(fmt_findings) == 0, "formatter pattern removed; should not flag"


# =========================================================================
# Core patterns still detected after fixes
# =========================================================================

@pytest.mark.asyncio
async def test_hashlib_md5_flagged(check):
    """hashlib.md5() usage must still be flagged."""
    code = "digest = hashlib.md5(data).hexdigest()\n"
    code_file = CodeFile(path="utils.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert not result.passed
    assert any("MD5" in f.message for f in result.findings)


@pytest.mark.asyncio
async def test_hashlib_sha1_flagged(check):
    """hashlib.sha1() usage must still be flagged."""
    code = "digest = hashlib.sha1(data).hexdigest()\n"
    code_file = CodeFile(path="utils.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert not result.passed


@pytest.mark.asyncio
async def test_os_popen_flagged(check):
    """os.popen() must still be flagged."""
    code = "out = os.popen('ls -la').read()\n"
    code_file = CodeFile(path="runner.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert not result.passed


@pytest.mark.asyncio
async def test_pickle_loads_flagged(check):
    """pickle.loads() must still be flagged."""
    code = "obj = pickle.loads(user_data)\n"
    code_file = CodeFile(path="api.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert not result.passed
    assert any("CWE-502" in f.message for f in result.findings)


@pytest.mark.asyncio
async def test_new_buffer_flagged(check):
    """new Buffer() must still be flagged in JS."""
    code = "const buf = new Buffer(userInput);\n"
    code_file = CodeFile(path="server.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    assert not result.passed


@pytest.mark.asyncio
async def test_crypto_create_cipher_flagged(check):
    """crypto.createCipher() must still be flagged."""
    code = "const cipher = crypto.createCipher('aes-256-cbc', key);\n"
    code_file = CodeFile(path="crypto.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    assert not result.passed


@pytest.mark.asyncio
async def test_fs_exists_flagged(check):
    """fs.exists() must still be flagged in JS."""
    code = "fs.exists(filePath, (exists) => {});\n"
    code_file = CodeFile(path="files.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    assert not result.passed


@pytest.mark.asyncio
async def test_url_parse_flagged(check):
    """url.parse() must still be flagged in JS."""
    code = "const parsed = url.parse(rawUrl);\n"
    code_file = CodeFile(path="routes.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    assert not result.passed


# =========================================================================
# Clean code / false-positive guards
# =========================================================================

@pytest.mark.asyncio
async def test_clean_python_passes(check):
    """Modern Python code with no deprecated APIs must pass."""
    code = (
        "import hashlib\n"
        "import ast\n"
        "import subprocess\n"
        "digest = hashlib.sha256(data).hexdigest()\n"
        "safe = ast.literal_eval(user_input)\n"
        "data = yaml.safe_load(stream)\n"
        "subprocess.run(['ls'], check=True)\n"
    )
    code_file = CodeFile(path="clean.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert result.passed


@pytest.mark.asyncio
async def test_language_mismatch_skips_python_patterns(check):
    """Python patterns must not fire on JavaScript files."""
    code = "const x = os.popen('ls');\n"
    code_file = CodeFile(path="app.js", content=code, language="javascript")
    result = await check.execute_async(code_file)
    popen_findings = [f for f in result.findings if "os.popen" in f.code_snippet]
    assert len(popen_findings) == 0, "Python os.popen should not fire on JS files"


@pytest.mark.asyncio
async def test_language_mismatch_skips_js_patterns(check):
    """JavaScript patterns must not fire on Python files."""
    code = "# Python file\nbuf = new_buffer(data)\n"
    code_file = CodeFile(path="utils.py", content=code, language="python")
    result = await check.execute_async(code_file)
    buffer_findings = [f for f in result.findings if "Buffer" in f.message]
    assert len(buffer_findings) == 0
