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


# =========================================================================
# Dunder / prototype-pollution subscript pattern — taint-context awareness
#
# The pattern  ^\s*\w+[key] = \w  is deliberately broad so it catches the
# canonical deep-merge write.  To avoid flooding projects with false
# positives on safe internal dict iteration the pattern is only reported
# when a user-input taint source (request.json, request.form, …) appears
# within ±10 lines.
# =========================================================================

def _dunder_findings(result):
    """Return findings that come from the dunder-subscript-assign pattern."""
    return [f for f in result.findings if "CWE-915" in f.message]


@pytest.mark.asyncio
async def test_dunder_subscript_safe_internal_dict_not_flagged(check):
    """Internal dict iteration with no user-input source must NOT be flagged."""
    code = (
        "field_map = {'total': 'sum', 'count': 'count'}\n"
        "agg = {}\n"
        "for key, col in field_map.items():\n"
        "    agg[key] = sum(col)\n"  # safe — key from hardcoded dict
    )
    code_file = CodeFile(path="analytics.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert len(_dunder_findings(result)) == 0, (
        "Safe internal dict iteration must not be flagged"
    )


@pytest.mark.asyncio
async def test_dunder_subscript_request_json_flagged(check):
    """Dict assignment where request.json is the loop source must be flagged."""
    code = (
        "from flask import request\n"
        "payload = request.json\n"
        "for key, value in payload.items():\n"
        "    obj[key] = value\n"  # tainted — key from request.json
    )
    code_file = CodeFile(path="api.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert len(_dunder_findings(result)) > 0, (
        "request.json loop should be flagged"
    )


@pytest.mark.asyncio
async def test_dunder_subscript_request_form_flagged(check):
    """Dict assignment where request.form is nearby must be flagged."""
    code = (
        "from flask import request\n"
        "data = request.form\n"
        "for name, val in data.items():\n"
        "    config[name] = val\n"  # tainted — name from request.form
    )
    code_file = CodeFile(path="form_handler.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert len(_dunder_findings(result)) > 0, (
        "request.form loop should be flagged"
    )


@pytest.mark.asyncio
async def test_dunder_subscript_request_args_flagged(check):
    """Dict assignment where request.args is nearby must be flagged."""
    code = (
        "from flask import request\n"
        "filters = request.args\n"
        "for field, val in filters.items():\n"
        "    query[field] = val\n"  # tainted — field from request.args
    )
    code_file = CodeFile(path="query.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert len(_dunder_findings(result)) > 0, (
        "request.args loop should be flagged"
    )


@pytest.mark.asyncio
async def test_dunder_subscript_taint_outside_window_not_flagged(check):
    """Taint source more than 10 lines away must NOT trigger the finding."""
    # Put request.json 12 lines above the assignment (outside the ±10 window)
    code = (
        "payload = request.json\n"           # line 1  — taint source
        "a = 1\n"                            # line 2
        "b = 2\n"                            # line 3
        "c = 3\n"                            # line 4
        "d = 4\n"                            # line 5
        "e = 5\n"                            # line 6
        "f = 6\n"                            # line 7
        "g = 7\n"                            # line 8
        "h = 8\n"                            # line 9
        "i = 9\n"                            # line 10
        "j = 10\n"                           # line 11
        "k = 11\n"                           # line 12
        "field_map = {'x': 1}\n"             # line 13
        "for key, col in field_map.items():\n"  # line 14
        "    agg[key] = col\n"               # line 15 — match; taint is 14 lines away
    )
    code_file = CodeFile(path="safe.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert len(_dunder_findings(result)) == 0, (
        "Taint source outside ±10-line window must not trigger the finding"
    )


@pytest.mark.asyncio
async def test_dunder_subscript_taint_comment_only_not_flagged(check):
    """A taint keyword inside a comment must not count as a taint source."""
    code = (
        "# This function does NOT use request.json or request.form\n"
        "field_map = {'total': 'sum'}\n"
        "for key, col in field_map.items():\n"
        "    agg[key] = col\n"
    )
    code_file = CodeFile(path="clean.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert len(_dunder_findings(result)) == 0, (
        "Taint keyword inside a comment must not trigger the finding"
    )


@pytest.mark.asyncio
async def test_dunder_subscript_sys_argv_taint_flagged(check):
    """sys.argv as the source of keys must be treated as tainted."""
    code = (
        "import sys\n"
        "args = dict(arg.split('=') for arg in sys.argv[1:])\n"
        "for key, val in args.items():\n"
        "    config[key] = val\n"
    )
    code_file = CodeFile(path="cli.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert len(_dunder_findings(result)) > 0, (
        "sys.argv-derived keys should be flagged"
    )


@pytest.mark.asyncio
async def test_dunder_subscript_get_json_taint_flagged(check):
    """request.get_json() must count as a taint source."""
    code = (
        "from flask import request\n"
        "body = request.get_json()\n"
        "for attr, v in body.items():\n"
        "    obj[attr] = v\n"
    )
    code_file = CodeFile(path="patch.py", content=code, language="python")
    result = await check.execute_async(code_file)
    assert len(_dunder_findings(result)) > 0, (
        "request.get_json() loop should be flagged"
    )


# =========================================================================
# _is_taint_context unit tests (called directly on the check instance)
# =========================================================================

def test_is_taint_context_returns_true_for_request_json(check):
    """_is_taint_context must return True when request.json is in the window."""
    lines = [
        "payload = request.json",
        "for key, value in payload.items():",
        "    obj[key] = value",
    ]
    # match is on line index 2
    assert check._is_taint_context(lines, match_line_index=2) is True


def test_is_taint_context_returns_false_for_internal_dict(check):
    """_is_taint_context must return False for hardcoded dict iteration."""
    lines = [
        "field_map = {'total': 'sum', 'count': 'count'}",
        "for key, col in field_map.items():",
        "    agg[key] = sum(col)",
    ]
    assert check._is_taint_context(lines, match_line_index=2) is False


def test_is_taint_context_ignores_taint_in_comments(check):
    """_is_taint_context must not count taint keywords inside comment lines."""
    lines = [
        "# we do NOT use request.json here",
        "field_map = {'a': 1}",
        "for key, col in field_map.items():",
        "    agg[key] = col",
    ]
    assert check._is_taint_context(lines, match_line_index=3) is False


def test_is_taint_context_respects_window_boundary(check):
    """_is_taint_context must not fire when taint is beyond the window."""
    # 15 filler lines then the match
    lines = ["payload = request.json"] + ["x = 1\n"] * 14 + ["    agg[key] = col"]
    match_index = len(lines) - 1  # last line
    # default window=10 — taint source is 15 lines away → out of range
    assert check._is_taint_context(lines, match_line_index=match_index, window=10) is False


def test_is_taint_context_returns_true_within_custom_window(check):
    """_is_taint_context with a larger window must find the taint source."""
    lines = ["payload = request.json"] + ["x = 1\n"] * 14 + ["    agg[key] = col"]
    match_index = len(lines) - 1
    assert check._is_taint_context(lines, match_line_index=match_index, window=20) is True


def test_is_taint_context_empty_lines(check):
    """_is_taint_context must return False on an empty file."""
    assert check._is_taint_context([], match_line_index=0) is False
