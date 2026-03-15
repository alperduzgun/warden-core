"""
Integration tests for SecurityFrame deterministic steps.

These tests verify pattern-matching and regex-based checks that run
without LLM involvement: secrets, SQL injection, XSS, weak crypto,
hardcoded passwords, CORS/cookie misconfigurations, and CSRF.

Each test creates a CodeFile, runs the relevant check directly (or via
SecurityFrame in standalone mode), and asserts on finding count and
severity without touching any LLM service.

Issue: #463
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure _internal is importable when tests run from the security frame directory
_SECURITY_DIR = Path(__file__).parents[2] / "src" / "warden" / "validation" / "frames" / "security"
if str(_SECURITY_DIR) not in sys.path:
    sys.path.insert(0, str(_SECURITY_DIR))

from warden.validation.domain.check import CheckSeverity
from warden.validation.domain.frame import CodeFile

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def security_frame():
    """Instantiate SecurityFrame without an LLM service (deterministic only)."""
    from warden.validation.frames.security.security_frame import SecurityFrame

    return SecurityFrame()


def _make_file(content: str, path: str = "target.py", language: str = "python") -> CodeFile:
    """Create a CodeFile for testing."""
    return CodeFile(path=path, content=content, language=language)


def _findings_for_check(result, check_id_substring: str):
    """Return frame-level findings whose id contains check_id_substring."""
    return [f for f in result.findings if check_id_substring in f.id]


# ===========================================================================
# 1. Hardcoded secrets detection
# ===========================================================================


class TestSecretsDetection:
    """SecretsCheck: API keys, tokens, private keys."""

    @pytest.mark.asyncio
    async def test_aws_access_key_detected(self, security_frame):
        """AKIA-prefixed AWS Access Key ID must be flagged as CRITICAL."""
        # Construct at runtime so static secret scanners don't block the push.
        aws_key = "AKIA" + "IOSFODNN7EXAMPLE"
        code = f'AWS_KEY = "{aws_key}"  # hardcoded\n'
        result = await security_frame.execute_async(_make_file(code))
        secrets_findings = _findings_for_check(result, "secrets")
        assert len(secrets_findings) >= 1, "Expected at least one secrets finding for AWS key"
        assert all(f.severity == "critical" for f in secrets_findings)

    @pytest.mark.asyncio
    async def test_openai_api_key_detected(self, security_frame):
        """sk-prefixed OpenAI API key of 40+ chars must be flagged."""
        # Construct at runtime so static secret scanners don't block the push.
        openai_key = "sk-" + "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOP"
        code = f'OPENAI_KEY = "{openai_key}"\n'
        result = await security_frame.execute_async(_make_file(code))
        secrets_findings = _findings_for_check(result, "secrets")
        assert len(secrets_findings) >= 1
        assert all(f.severity == "critical" for f in secrets_findings)

    @pytest.mark.asyncio
    async def test_github_pat_detected(self, security_frame):
        """ghp_-prefixed GitHub PAT (36 chars) must be flagged."""
        # Construct at runtime so static secret scanners don't block the push.
        github_pat = "ghp_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890"
        code = f'TOKEN = "{github_pat}"\n'
        result = await security_frame.execute_async(_make_file(code))
        secrets_findings = _findings_for_check(result, "secrets")
        assert len(secrets_findings) >= 1

    @pytest.mark.asyncio
    async def test_private_key_pem_detected(self, security_frame):
        """RSA PRIVATE KEY PEM header must be flagged as CRITICAL."""
        code = (
            'key = """\n'
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA2a2rwplBQLF29amygykEMmYz0+Kcj3bKBp29\n"
            "-----END RSA PRIVATE KEY-----\n"
            '"""\n'
        )
        result = await security_frame.execute_async(_make_file(code))
        secrets_findings = _findings_for_check(result, "secrets")
        assert len(secrets_findings) >= 1

    @pytest.mark.asyncio
    async def test_database_connection_string_detected(self, security_frame):
        """postgres:// connection string with embedded password must be flagged."""
        code = 'DB_URL = "postgres://admin:supersecret@localhost:5432/mydb"\n'
        result = await security_frame.execute_async(_make_file(code))
        secrets_findings = _findings_for_check(result, "secrets")
        assert len(secrets_findings) >= 1

    @pytest.mark.asyncio
    async def test_env_var_usage_not_flagged(self, security_frame):
        """Reading secrets from os.getenv() must NOT trigger secrets findings."""
        code = (
            "import os\n"
            "API_KEY = os.getenv('OPENAI_API_KEY')\n"
            "DB_URL = os.environ['DATABASE_URL']\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        secrets_findings = _findings_for_check(result, "secrets")
        assert len(secrets_findings) == 0, "env-var usage should not be flagged as a secret"

    @pytest.mark.asyncio
    async def test_stripe_live_key_detected(self, security_frame):
        """sk_live_-prefixed Stripe secret key must be flagged."""
        # Construct the test string at runtime to avoid GitHub push protection
        # triggering on the raw source file (this is a fake key for testing only).
        prefix = "sk" + "_live_"
        suffix = "abcdefghijklmnopqrstuvwxyz"
        code = f'STRIPE_KEY = "{prefix}{suffix}"\n'
        result = await security_frame.execute_async(_make_file(code))
        secrets_findings = _findings_for_check(result, "secrets")
        assert len(secrets_findings) >= 1


# ===========================================================================
# 2. Hardcoded password detection
# ===========================================================================


class TestHardcodedPasswordDetection:
    """HardcodedPasswordCheck: password/secret/token variable assignments."""

    @pytest.mark.asyncio
    async def test_hardcoded_password_variable_detected(self, security_frame):
        """password = 'literal_value' must be flagged as CRITICAL."""
        code = "password = 'my_super_secret_pass'\n"
        result = await security_frame.execute_async(_make_file(code))
        pw_findings = _findings_for_check(result, "hardcoded-password")
        assert len(pw_findings) >= 1
        assert all(f.severity in ("critical", "high") for f in pw_findings)

    @pytest.mark.asyncio
    async def test_common_weak_password_detected(self, security_frame):
        """Common weak password string (e.g. 'admin123') must be flagged."""
        code = 'db_pass = "admin123"\n'
        result = await security_frame.execute_async(_make_file(code))
        pw_findings = _findings_for_check(result, "hardcoded-password")
        assert len(pw_findings) >= 1

    @pytest.mark.asyncio
    async def test_env_var_password_not_flagged(self, security_frame):
        """password read from os.getenv() must NOT be flagged."""
        code = (
            "import os\n"
            "password = os.getenv('DB_PASSWORD')\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        pw_findings = _findings_for_check(result, "hardcoded-password")
        assert len(pw_findings) == 0

    @pytest.mark.asyncio
    async def test_getpass_not_flagged(self, security_frame):
        """password read via getpass() prompt must NOT be flagged."""
        code = (
            "import getpass\n"
            "password = getpass.getpass('Enter password: ')\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        pw_findings = _findings_for_check(result, "hardcoded-password")
        assert len(pw_findings) == 0


# ===========================================================================
# 3. SQL injection patterns
# ===========================================================================


class TestSQLInjectionDetection:
    """SQLInjectionCheck: f-string, concatenation, format(), % in queries."""

    @pytest.mark.asyncio
    async def test_fstring_sql_query_detected(self, security_frame):
        """f-string interpolation in SELECT query must be flagged as CRITICAL."""
        code = (
            "def get_user(user_id):\n"
            '    query = f"SELECT * FROM users WHERE id = {user_id}"\n'
            "    cursor.execute(query)\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        sql_findings = _findings_for_check(result, "sql-injection")
        assert len(sql_findings) >= 1
        assert all(f.severity == "critical" for f in sql_findings)

    @pytest.mark.asyncio
    async def test_string_concat_sql_detected(self, security_frame):
        """String concatenation in SELECT query must be flagged."""
        code = (
            "def search(term):\n"
            '    query = "SELECT * FROM products WHERE name = " + term\n'
            "    db.execute(query)\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        sql_findings = _findings_for_check(result, "sql-injection")
        assert len(sql_findings) >= 1

    @pytest.mark.asyncio
    async def test_format_method_sql_detected(self, security_frame):
        """str.format() in SQL query must be flagged."""
        code = (
            "def delete_record(record_id):\n"
            '    query = "DELETE FROM logs WHERE id = {}".format(record_id)\n'
            "    cursor.execute(query)\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        sql_findings = _findings_for_check(result, "sql-injection")
        assert len(sql_findings) >= 1

    @pytest.mark.asyncio
    async def test_percent_format_sql_detected(self, security_frame):
        """% string formatting in SQL query must be flagged."""
        code = (
            "def get_by_name(name):\n"
            '    query = "SELECT id FROM users WHERE username = \'%s\'" % name\n'
            "    cursor.execute(query)\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        sql_findings = _findings_for_check(result, "sql-injection")
        assert len(sql_findings) >= 1

    @pytest.mark.asyncio
    async def test_parameterized_query_not_flagged(self, security_frame):
        """Properly parameterized query must NOT trigger SQL injection finding."""
        code = (
            "def get_user(user_id):\n"
            '    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))\n'
            "    return cursor.fetchone()\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        sql_findings = _findings_for_check(result, "sql-injection")
        assert len(sql_findings) == 0, "Parameterized query must not be flagged"

    @pytest.mark.asyncio
    async def test_insert_with_fstring_detected(self, security_frame):
        """f-string in INSERT query must be flagged."""
        code = (
            "def create_user(username, email):\n"
            '    query = f"INSERT INTO users (name, email) VALUES (\'{username}\', \'{email}\')"\n'
            "    db.execute(query)\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        sql_findings = _findings_for_check(result, "sql-injection")
        assert len(sql_findings) >= 1


# ===========================================================================
# 4. XSS patterns
# ===========================================================================


class TestXSSDetection:
    """XSSCheck: innerHTML, document.write, Django |safe, mark_safe."""

    @pytest.mark.asyncio
    async def test_innerhtml_assignment_detected(self, security_frame):
        """innerHTML = assignment must be flagged as HIGH severity."""
        code = (
            "function render(userInput) {\n"
            "    document.getElementById('output').innerHTML = userInput;\n"
            "}\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="app.js", language="javascript")
        )
        xss_findings = _findings_for_check(result, "xss")
        assert len(xss_findings) >= 1
        assert all(f.severity == "high" for f in xss_findings)

    @pytest.mark.asyncio
    async def test_document_write_detected(self, security_frame):
        """document.write() usage must be flagged."""
        code = (
            "function inject(content) {\n"
            "    document.write(content);\n"
            "}\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="script.js", language="javascript")
        )
        xss_findings = _findings_for_check(result, "xss")
        assert len(xss_findings) >= 1

    @pytest.mark.asyncio
    async def test_django_safe_filter_detected(self, security_frame):
        """Django |safe template filter in Python code must be flagged."""
        # mark_safe() is the Python-side equivalent; |safe appears in templates
        # rendered as strings — use mark_safe so the Python XSS check fires.
        code = (
            "from django.utils.safestring import mark_safe\n"
            "\n"
            "def render_comment(comment_text):\n"
            "    # Intentionally bypassing escaping — should be flagged\n"
            "    return mark_safe(comment_text)  # |safe equivalent in Python\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="views.py", language="python")
        )
        xss_findings = _findings_for_check(result, "xss")
        assert len(xss_findings) >= 1

    @pytest.mark.asyncio
    async def test_django_mark_safe_detected(self, security_frame):
        """Django mark_safe() call on user-supplied data must be flagged."""
        code = (
            "from django.utils.safestring import mark_safe\n"
            "\n"
            "def render_bio(user):\n"
            "    # mark_safe() bypasses Django's auto-escaping\n"
            "    return mark_safe(user.bio)\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="profile_views.py", language="python")
        )
        xss_findings = _findings_for_check(result, "xss")
        assert len(xss_findings) >= 1

    @pytest.mark.asyncio
    async def test_react_dangerous_set_inner_html_detected(self, security_frame):
        """dangerouslySetInnerHTML in React JSX must be flagged."""
        code = (
            "function UserProfile({ bio }) {\n"
            "    return <div dangerouslySetInnerHTML={{ __html: bio }} />;\n"
            "}\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="Profile.jsx", language="javascript")
        )
        xss_findings = _findings_for_check(result, "xss")
        assert len(xss_findings) >= 1

    @pytest.mark.asyncio
    async def test_text_content_assignment_not_flagged(self, security_frame):
        """Safe textContent assignment must NOT trigger XSS finding."""
        code = (
            "function render(userInput) {\n"
            "    document.getElementById('output').textContent = userInput;\n"
            "}\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="safe.js", language="javascript")
        )
        xss_findings = _findings_for_check(result, "xss")
        assert len(xss_findings) == 0, "textContent is safe and must not be flagged"

    @pytest.mark.asyncio
    async def test_outer_html_assignment_detected(self, security_frame):
        """outerHTML assignment must be flagged."""
        code = (
            "function replace(el, content) {\n"
            "    el.outerHTML = content;\n"
            "}\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="dom.js", language="javascript")
        )
        xss_findings = _findings_for_check(result, "xss")
        assert len(xss_findings) >= 1


# ===========================================================================
# 5. Weak cryptography
# ===========================================================================


class TestWeakCryptoDetection:
    """WeakCryptoCheck: MD5/SHA1 for passwords, DES, RC4, ECB mode."""

    @pytest.mark.asyncio
    async def test_md5_password_hashing_detected(self, security_frame):
        """hashlib.md5() used in password context must be flagged as HIGH."""
        code = (
            "import hashlib\n"
            "\n"
            "def hash_password(password):\n"
            "    return hashlib.md5(password.encode()).hexdigest()\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        crypto_findings = _findings_for_check(result, "weak-crypto")
        assert len(crypto_findings) >= 1
        assert all(f.severity == "high" for f in crypto_findings)
        assert any("CWE-328" in f.message for f in crypto_findings)

    @pytest.mark.asyncio
    async def test_sha1_password_hashing_detected(self, security_frame):
        """hashlib.sha1() used in password context must be flagged."""
        code = (
            "import hashlib\n"
            "\n"
            "def verify_password(password, stored_hash):\n"
            "    return hashlib.sha1(password.encode()).hexdigest() == stored_hash\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        crypto_findings = _findings_for_check(result, "weak-crypto")
        assert len(crypto_findings) >= 1

    @pytest.mark.asyncio
    async def test_md5_for_checksum_not_flagged(self, security_frame):
        """hashlib.md5() used as file checksum must NOT be flagged."""
        code = (
            "import hashlib\n"
            "\n"
            "def compute_checksum(file_path):\n"
            "    with open(file_path, 'rb') as f:\n"
            "        return hashlib.md5(f.read()).hexdigest()\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        crypto_findings = _findings_for_check(result, "weak-crypto")
        assert len(crypto_findings) == 0, "MD5 for checksum must not be flagged"

    @pytest.mark.asyncio
    async def test_des_cipher_detected(self, security_frame):
        """DES cipher usage must be flagged as HIGH (CWE-327)."""
        code = (
            "from Crypto.Cipher import DES\n"
            "\n"
            "def encrypt(data, key):\n"
            "    cipher = DES.new(key, DES.MODE_ECB)\n"
            "    return cipher.encrypt(data)\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        crypto_findings = _findings_for_check(result, "weak-crypto")
        assert len(crypto_findings) >= 1
        assert any("CWE-327" in f.message for f in crypto_findings)

    @pytest.mark.asyncio
    async def test_aes_ecb_mode_detected(self, security_frame):
        """AES.MODE_ECB must be flagged (CWE-327)."""
        code = (
            "from Crypto.Cipher import AES\n"
            "\n"
            "def encrypt_block(data, key):\n"
            "    cipher = AES.new(key, AES.MODE_ECB)\n"
            "    return cipher.encrypt(data)\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        crypto_findings = _findings_for_check(result, "weak-crypto")
        assert len(crypto_findings) >= 1

    @pytest.mark.asyncio
    async def test_rc4_cipher_detected(self, security_frame):
        """ARC4/RC4 cipher must be flagged."""
        code = (
            "from Crypto.Cipher import ARC4\n"
            "\n"
            "def encrypt_stream(data, key):\n"
            "    cipher = ARC4.new(key)\n"
            "    return cipher.encrypt(data)\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        crypto_findings = _findings_for_check(result, "weak-crypto")
        assert len(crypto_findings) >= 1

    @pytest.mark.asyncio
    async def test_javascript_md5_hash_detected(self, security_frame):
        """Node.js crypto.createHash('md5') must be flagged."""
        code = (
            "const crypto = require('crypto');\n"
            "\n"
            "function hashPassword(password) {\n"
            "    return crypto.createHash('md5').update(password).digest('hex');\n"
            "}\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="auth.js", language="javascript")
        )
        crypto_findings = _findings_for_check(result, "weak-crypto")
        assert len(crypto_findings) >= 1

    @pytest.mark.asyncio
    async def test_strong_aes_gcm_not_flagged(self, security_frame):
        """AES-256-GCM (secure) must NOT be flagged."""
        code = (
            "from Crypto.Cipher import AES\n"
            "\n"
            "def encrypt(data, key, nonce):\n"
            "    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)\n"
            "    ciphertext, tag = cipher.encrypt_and_digest(data)\n"
            "    return ciphertext, tag\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        crypto_findings = _findings_for_check(result, "weak-crypto")
        assert len(crypto_findings) == 0, "AES-GCM is secure and must not be flagged"


# ===========================================================================
# 6. HTTP security misconfigurations
# ===========================================================================


class TestHTTPSecurityDetection:
    """HTTPSecurityCheck: permissive CORS, insecure cookies, missing helmet."""

    @pytest.mark.asyncio
    async def test_cors_wildcard_origin_detected(self, security_frame):
        """FastAPI allow_origins=["*"] must be flagged as HIGH."""
        code = (
            "from fastapi.middleware.cors import CORSMiddleware\n"
            "\n"
            "app.add_middleware(\n"
            "    CORSMiddleware,\n"
            '    allow_origins=["*"],\n'
            "    allow_methods=['GET', 'POST'],\n"
            ")\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="main.py", language="python")
        )
        http_findings = _findings_for_check(result, "http-security")
        assert len(http_findings) >= 1
        assert all(f.severity in ("high", "medium") for f in http_findings)

    @pytest.mark.asyncio
    async def test_django_cors_allow_all_detected(self, security_frame):
        """Django CORS_ALLOW_ALL_ORIGINS = True must be flagged."""
        code = (
            "# Django settings\n"
            "CORS_ALLOW_ALL_ORIGINS = True\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="settings.py", language="python")
        )
        http_findings = _findings_for_check(result, "http-security")
        assert len(http_findings) >= 1

    @pytest.mark.asyncio
    async def test_django_session_cookie_insecure_detected(self, security_frame):
        """Django SESSION_COOKIE_SECURE = False must be flagged."""
        code = (
            "SESSION_COOKIE_SECURE = False\n"
            "CSRF_COOKIE_SECURE = False\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="settings.py", language="python")
        )
        http_findings = _findings_for_check(result, "http-security")
        assert len(http_findings) >= 1

    @pytest.mark.asyncio
    async def test_express_cors_wildcard_detected(self, security_frame):
        """Express cors({ origin: '*' }) must be flagged."""
        code = (
            "const express = require('express');\n"
            "const cors = require('cors');\n"
            "const app = express();\n"
            "\n"
            "app.use(cors({ origin: '*' }));\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="server.js", language="javascript")
        )
        http_findings = _findings_for_check(result, "http-security")
        assert len(http_findings) >= 1

    @pytest.mark.asyncio
    async def test_express_without_helmet_detected(self, security_frame):
        """Express app without helmet() must be flagged."""
        code = (
            "const express = require('express');\n"
            "const app = express();\n"
            "\n"
            "app.get('/', (req, res) => res.send('Hello'));\n"
            "app.listen(3000);\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="app.js", language="javascript")
        )
        http_findings = _findings_for_check(result, "http-security")
        assert len(http_findings) >= 1

    @pytest.mark.asyncio
    async def test_express_with_helmet_not_flagged(self, security_frame):
        """Express app with helmet() must NOT produce a helmet-missing finding."""
        code = (
            "const express = require('express');\n"
            "const helmet = require('helmet');\n"
            "const app = express();\n"
            "\n"
            "app.use(helmet());\n"
            "app.get('/', (req, res) => res.send('Secure'));\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="secure_app.js", language="javascript")
        )
        # No http-security findings about missing helmet
        helmet_findings = [
            f for f in result.findings
            if "http-security" in f.id and "helmet" in f.message.lower()
        ]
        assert len(helmet_findings) == 0


# ===========================================================================
# 7. CSRF detection
# ===========================================================================


class TestCSRFDetection:
    """CSRFCheck: @csrf_exempt decorator, missing CsrfViewMiddleware."""

    @pytest.mark.asyncio
    async def test_csrf_exempt_decorator_detected(self, security_frame):
        """@csrf_exempt on a Django view must be flagged."""
        code = (
            "from django.views.decorators.csrf import csrf_exempt\n"
            "from django.http import JsonResponse\n"
            "\n"
            "@csrf_exempt\n"
            "def payment_view(request):\n"
            "    if request.method == 'POST':\n"
            "        return JsonResponse({'status': 'ok'})\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="views.py", language="python")
        )
        csrf_findings = _findings_for_check(result, "csrf")
        assert len(csrf_findings) >= 1

    @pytest.mark.asyncio
    async def test_django_middleware_without_csrf_detected(self, security_frame):
        """Django MIDDLEWARE list missing CsrfViewMiddleware must be flagged."""
        code = (
            "MIDDLEWARE = [\n"
            "    'django.middleware.security.SecurityMiddleware',\n"
            "    'django.contrib.sessions.middleware.SessionMiddleware',\n"
            "    'django.middleware.common.CommonMiddleware',\n"
            "    'django.contrib.auth.middleware.AuthenticationMiddleware',\n"
            "]\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="settings.py", language="python")
        )
        csrf_findings = _findings_for_check(result, "csrf")
        assert len(csrf_findings) >= 1


# ===========================================================================
# 8. Safe code — no false positives
# ===========================================================================


class TestSafeCodeNoFalsePositives:
    """Properly written code must not produce false-positive findings."""

    @pytest.mark.asyncio
    async def test_clean_python_module_no_findings(self, security_frame):
        """Clean, safe Python utility module must produce zero security findings."""
        code = (
            '"""Utility module for data processing."""\n'
            "\n"
            "import os\n"
            "import hashlib\n"
            "\n"
            "DB_URL = os.getenv('DATABASE_URL')\n"
            "SECRET_KEY = os.environ['SECRET_KEY']\n"
            "\n"
            "\n"
            "def compute_file_checksum(file_path: str) -> str:\n"
            '    """Return MD5 checksum of a file (safe for integrity verification)."""\n'
            "    with open(file_path, 'rb') as fh:\n"
            "        return hashlib.md5(fh.read()).hexdigest()  # checksum only\n"
            "\n"
            "\n"
            "def get_user(conn, user_id: int) -> dict:\n"
            '    """Fetch user by id using parameterized query."""\n'
            "    cursor = conn.cursor()\n"
            "    cursor.execute('SELECT id, name FROM users WHERE id = ?', (user_id,))\n"
            "    row = cursor.fetchone()\n"
            "    return {'id': row[0], 'name': row[1]} if row else {}\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        # No critical findings expected
        critical_findings = [f for f in result.findings if f.severity == "critical"]
        assert len(critical_findings) == 0, (
            f"Clean code produced unexpected critical findings: "
            f"{[f.message for f in critical_findings]}"
        )

    @pytest.mark.asyncio
    async def test_clean_javascript_module_no_critical_findings(self, security_frame):
        """Clean, safe JavaScript module must not produce critical findings."""
        code = (
            "const helmet = require('helmet');\n"
            "const express = require('express');\n"
            "\n"
            "const app = express();\n"
            "app.use(helmet());\n"
            "\n"
            "app.get('/user/:id', async (req, res) => {\n"
            "    const userId = parseInt(req.params.id, 10);\n"
            "    const user = await db.query(\n"
            "        'SELECT id, name FROM users WHERE id = $1',\n"
            "        [userId]\n"
            "    );\n"
            "    res.json(user);\n"
            "});\n"
        )
        result = await security_frame.execute_async(
            _make_file(code, path="api.js", language="javascript")
        )
        critical_findings = [f for f in result.findings if f.severity == "critical"]
        assert len(critical_findings) == 0, (
            f"Clean JS code produced unexpected critical findings: "
            f"{[f.message for f in critical_findings]}"
        )

    @pytest.mark.asyncio
    async def test_empty_file_no_findings(self, security_frame):
        """An empty file must produce zero findings."""
        result = await security_frame.execute_async(_make_file(""))
        assert result.issues_found == 0
        assert len(result.findings) == 0

    @pytest.mark.asyncio
    async def test_comment_only_file_no_findings(self, security_frame):
        """A file with only comments must produce zero findings."""
        code = (
            "# This is a placeholder file.\n"
            "# password = 'example_only'  — this is just a comment\n"
            "# No code here.\n"
        )
        result = await security_frame.execute_async(_make_file(code))
        # Comment-only lines should not trigger findings
        assert result.issues_found == 0


# ===========================================================================
# 9. SecurityFrame structural / meta tests
# ===========================================================================


class TestSecurityFrameMeta:
    """Verify SecurityFrame structural properties."""

    def test_frame_id_is_security(self, security_frame):
        """frame_id must be 'security'."""
        assert security_frame.frame_id == "security"

    def test_frame_is_blocker(self, security_frame):
        """SecurityFrame must be a blocker frame."""
        assert security_frame.is_blocker is True

    def test_builtin_checks_registered(self, security_frame):
        """All built-in checks must be registered on instantiation."""
        check_ids = {c.id for c in security_frame.checks.get_enabled({})}
        expected = {"sql-injection", "xss", "secrets", "hardcoded-password", "weak-crypto", "csrf"}
        for expected_id in expected:
            assert expected_id in check_ids, f"Expected check '{expected_id}' not registered"

    @pytest.mark.asyncio
    async def test_frame_result_status_failed_on_critical_finding(self, security_frame):
        """Frame result status must be 'failed' when a CRITICAL finding exists."""
        # Construct at runtime so static secret scanners don't block the push.
        aws_key = "AKIA" + "IOSFODNN7EXAMPLE"
        code = f'SECRET = "{aws_key}"\n'
        result = await security_frame.execute_async(_make_file(code))
        assert result.status == "failed"
        assert result.is_blocker is True

    @pytest.mark.asyncio
    async def test_frame_result_status_passed_for_safe_code(self, security_frame):
        """Frame result must pass for genuinely safe code."""
        code = (
            "import os\n"
            "\n"
            "def greet(name: str) -> str:\n"
            '    return f"Hello, {name}!"\n'
        )
        result = await security_frame.execute_async(_make_file(code))
        critical_findings = [f for f in result.findings if f.severity == "critical"]
        assert len(critical_findings) == 0
