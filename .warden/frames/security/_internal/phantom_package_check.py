"""
Phantom Package Detection Check.

Detects imports of non-existent packages (AI hallucinations / typos):
- Extracts import statements from Python and JavaScript files via regex
- Skips stdlib modules and well-known packages (no network call needed)
- Verifies unknown packages against PyPI (Python) or npm (JavaScript) registries
- Reports 404 responses as HIGH severity findings

References:
- https://cve.mitre.org/cgi-bin/cvekey.cgi?keyword=hallucination+package
- CWE-829: Inclusion of Functionality from Untrusted Control Sphere
"""

from __future__ import annotations

import re
import sys
from typing import Any

import httpx

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.check import (
    CheckFinding,
    CheckResult,
    CheckSeverity,
    ValidationCheck,
)
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REQUEST_TIMEOUT = 5.0  # seconds per registry lookup
_MAX_PACKAGES_PER_SCAN = 20  # cap to prevent runaway network calls

# Python standard library modules — populated from sys.stdlib_module_names
# (Python 3.10+) with a hardcoded fallback for older runtimes.
_PYTHON_STDLIB: frozenset[str] = frozenset(
    getattr(sys, "stdlib_module_names", None)
    or {
        "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio",
        "asyncore", "atexit", "audioop", "base64", "bdb", "binascii",
        "binhex", "bisect", "builtins", "bz2", "calendar", "cgi", "cgitb",
        "chunk", "cmath", "cmd", "code", "codecs", "codeop", "colorsys",
        "compileall", "concurrent", "configparser", "contextlib",
        "contextvars", "copy", "copyreg", "cProfile", "csv", "ctypes",
        "curses", "dataclasses", "datetime", "dbm", "decimal", "difflib",
        "dis", "doctest", "email", "encodings", "enum", "errno",
        "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch",
        "fractions", "ftplib", "functools", "gc", "getopt", "getpass",
        "gettext", "glob", "grp", "gzip", "hashlib", "heapq", "hmac",
        "html", "http", "idlelib", "imaplib", "imghdr", "importlib",
        "inspect", "io", "ipaddress", "itertools", "json", "keyword",
        "lib2to3", "linecache", "locale", "logging", "lzma", "mailbox",
        "marshal", "math", "mimetypes", "mmap", "modulefinder", "multiprocessing",
        "netrc", "nis", "nntplib", "numbers", "operator", "optparse",
        "os", "ossaudiodev", "pathlib", "pdb", "pickle", "pickletools",
        "pipes", "pkgutil", "platform", "plistlib", "poplib", "posix",
        "posixpath", "pprint", "profile", "pstats", "pty", "pwd", "py_compile",
        "pyclbr", "pydoc", "queue", "quopri", "random", "re", "readline",
        "reprlib", "resource", "rlcompleter", "runpy", "sched", "secrets",
        "select", "selectors", "shelve", "shlex", "shutil", "signal",
        "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver",
        "spwd", "sqlite3", "sre_compile", "sre_constants", "sre_parse",
        "ssl", "stat", "statistics", "string", "stringprep", "struct",
        "subprocess", "sunau", "symtable", "sys", "sysconfig", "syslog",
        "tabnanny", "tarfile", "telnetlib", "tempfile", "termios", "test",
        "textwrap", "threading", "time", "timeit", "tkinter", "token",
        "tokenize", "tomllib", "trace", "traceback", "tracemalloc", "tty",
        "turtle", "turtledemo", "types", "typing", "unicodedata", "unittest",
        "urllib", "uu", "uuid", "venv", "warnings", "wave", "weakref",
        "webbrowser", "wsgiref", "xdrlib", "xml", "xmlrpc", "zipapp",
        "zipfile", "zipimport", "zlib", "zoneinfo", "_thread",
    }
)

# Well-known packages by ecosystem — skip network lookup for these.
# Must be lowercase with hyphens (normalised form).
_KNOWN_PYTHON_PACKAGES: frozenset[str] = frozenset({
    "flask", "django", "fastapi", "requests", "numpy", "pandas", "scipy",
    "matplotlib", "pillow", "sqlalchemy", "psycopg2", "pymongo", "redis",
    "celery", "pytest", "hypothesis", "click", "typer", "rich", "tqdm",
    "pydantic", "attrs", "httpx", "aiohttp", "uvicorn", "gunicorn",
    "starlette", "tornado", "boto3", "botocore", "cryptography", "pyjwt",
    "bcrypt", "passlib", "lxml", "beautifulsoup4", "jinja2", "werkzeug",
    "itsdangerous", "markupsafe", "six", "setuptools", "wheel", "pip",
    "black", "ruff", "flake8", "pylint", "mypy", "isort", "bandit",
    "python-dotenv", "pyyaml", "toml", "packaging", "typing-extensions",
    "python-dateutil", "pytz", "arrow", "pendulum", "chardet",
    "charset-normalizer", "idna", "certifi", "urllib3", "httpcore",
    "anyio", "trio", "asyncio", "twisted", "orjson", "ujson", "msgpack",
    "protobuf", "grpcio", "websockets", "paramiko", "fabric", "ansible",
    "docker", "kubernetes", "scikit-learn", "tensorflow", "torch", "keras",
    "xgboost", "lightgbm", "transformers", "datasets", "diffusers",
    "opencv-python", "imageio", "seaborn", "plotly", "bokeh", "statsmodels",
    "nltk", "spacy", "tokenizers", "accelerate", "alembic", "asyncpg",
    "motor", "peewee", "tortoise-orm", "databases", "coverage", "tox",
    "nox", "factory-boy", "faker", "responses", "pytest-asyncio",
    "pytest-cov", "pytest-mock", "pyopenssl", "feedparser", "xmltodict",
    "filelock", "watchdog", "schedule", "apscheduler", "colorama",
    "marshmallow", "cerberus", "dataclasses-json",
})

_KNOWN_JS_PACKAGES: frozenset[str] = frozenset({
    "react", "vue", "angular", "svelte", "next", "nuxt", "gatsby", "remix",
    "astro", "solid-js", "preact", "lit", "typescript", "webpack", "vite",
    "esbuild", "rollup", "parcel", "babel", "swc", "turbo", "nx",
    "express", "fastify", "koa", "hapi", "nestjs", "hono", "redux",
    "mobx", "zustand", "jotai", "recoil", "pinia", "vuex", "jest",
    "mocha", "chai", "vitest", "cypress", "playwright", "puppeteer",
    "testing-library", "sinon", "nyc", "axios", "node-fetch", "got",
    "superagent", "undici", "socket.io", "ws", "mongoose", "sequelize",
    "knex", "prisma", "typeorm", "drizzle-orm", "pg", "mysql2", "ioredis",
    "tailwindcss", "bootstrap", "material-ui", "antd", "chakra-ui",
    "styled-components", "emotion", "lodash", "underscore", "ramda",
    "date-fns", "moment", "dayjs", "uuid", "nanoid", "chalk", "debug",
    "dotenv", "commander", "yargs", "inquirer", "ora", "glob", "fs-extra",
    "rimraf", "mkdirp", "cross-env", "semver", "minimist", "yaml",
    "zod", "yup", "joi", "ajv", "class-validator", "jsonwebtoken",
    "passport", "bcrypt", "argon2", "eslint", "prettier", "stylelint",
    "rxjs", "graphql", "apollo-server", "cors", "body-parser",
    "cookie-parser", "multer", "morgan", "helmet", "compression",
    "concurrently", "nodemon", "pm2", "ts-node", "tsup",
})

# Regex patterns for import extraction
_PY_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    re.MULTILINE,
)
_JS_IMPORT_RE = re.compile(
    r"""(?:import\s+.*?\s+from\s+|require\s*\(\s*)['"]([^'"./][^'"]*?)['"]""",
    re.MULTILINE,
)

# Session-level registry cache: "pypi:pkg" or "npm:pkg" → bool (exists)
_REGISTRY_CACHE: dict[str, bool] = {}


def _normalize_python_pkg(name: str) -> str:
    """Normalise Python package name: lowercase, hyphens for underscores."""
    return name.lower().replace("_", "-")


def _extract_python_imports(content: str) -> list[str]:
    """Return top-level module names from Python import statements."""
    names: list[str] = []
    for match in _PY_IMPORT_RE.finditer(content):
        pkg = match.group(1).split(".")[0]
        names.append(pkg)
    return names


def _extract_js_imports(content: str) -> list[str]:
    """Return package names from JS import/require statements."""
    names: list[str] = []
    for match in _JS_IMPORT_RE.finditer(content):
        raw = match.group(1)
        if raw.startswith("@"):
            # Scoped package: @scope/pkg/subpath → keep only @scope/pkg
            parts = raw.split("/")
            pkg = "/".join(parts[:2])
        else:
            # Unscoped: strip any subpath (pkg/subpath → pkg)
            pkg = raw.split("/")[0]
        names.append(pkg)
    return names


async def _package_exists(ecosystem: str, package: str) -> bool:
    """
    Check whether a package exists in PyPI or npm.

    Results are cached in _REGISTRY_CACHE for the session.

    Args:
        ecosystem: "pypi" or "npm"
        package:   Package name (already normalised)

    Returns:
        True if the registry returns 200, False on 404.
        Raises on non-404 errors or timeout so callers can handle gracefully.
    """
    cache_key = f"{ecosystem}:{package}"
    if cache_key in _REGISTRY_CACHE:
        return _REGISTRY_CACHE[cache_key]

    if ecosystem == "pypi":
        url = f"https://pypi.org/pypi/{package}/json"
    else:
        url = f"https://registry.npmjs.org/{package}"

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.head(url)

    if response.status_code == 404:
        _REGISTRY_CACHE[cache_key] = False
        return False
    if response.status_code == 200:
        _REGISTRY_CACHE[cache_key] = True
        return True
    # Other status codes (429, 500, etc.) — don't cache, assume exists
    return True


class PhantomPackageCheck(ValidationCheck):
    """
    Detects imports of non-existent packages (AI hallucinations).

    Extracts import statements from Python and JavaScript files, filters
    out known-good packages (stdlib + popular set), then verifies remaining
    packages against PyPI or npm. A 404 response means the package does not
    exist in the registry and is reported as a HIGH severity finding.

    Severity: HIGH (hallucinated packages are a supply-chain risk)
    """

    id = "phantom-package"
    name = "Phantom Package Detection"
    description = "Detects imports of non-existent packages (AI hallucinations)"
    severity = CheckSeverity.HIGH
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the check with optional config."""
        super().__init__(config)
        self._extra_known: set[str] = set(self.config.get("known_packages", []))

    def _is_known_python(self, pkg: str) -> bool:
        norm = _normalize_python_pkg(pkg)
        return (
            pkg in _PYTHON_STDLIB
            or norm in _KNOWN_PYTHON_PACKAGES
            or norm in self._extra_known
        )

    def _is_known_js(self, pkg: str) -> bool:
        return pkg in _KNOWN_JS_PACKAGES or pkg in self._extra_known

    async def execute_async(self, code_file: CodeFile) -> CheckResult:
        """
        Execute phantom package detection.

        Args:
            code_file: Code file to check.

        Returns:
            CheckResult with findings.
        """
        findings: list[CheckFinding] = []
        language = (code_file.language or "").lower()

        # Only handle Python and JavaScript/TypeScript for now
        if language not in ("python", "javascript", "typescript"):
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=True,
                findings=[],
                metadata={"skipped": True, "reason": f"unsupported language: {language}"},
            )

        # Extract imports based on language
        if language == "python":
            ecosystem = "pypi"
            candidates = _extract_python_imports(code_file.content)
            is_known = self._is_known_python
        else:
            ecosystem = "npm"
            candidates = _extract_js_imports(code_file.content)
            is_known = self._is_known_js

        # Deduplicate, filter known-good packages
        seen: set[str] = set()
        to_check: list[str] = []
        for pkg in candidates:
            if not pkg or pkg in seen:
                continue
            seen.add(pkg)
            if not is_known(pkg):
                to_check.append(pkg)

        # Cap to avoid runaway network calls
        to_check = to_check[:_MAX_PACKAGES_PER_SCAN]

        checked_count = 0
        skipped_count = 0

        for pkg in to_check:
            try:
                # Normalize Python package names for PyPI lookup (underscores → hyphens)
                lookup_pkg = pkg.replace("_", "-").lower() if ecosystem == "pypi" else pkg
                exists = await _package_exists(ecosystem, lookup_pkg)
                checked_count += 1
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
                # Network issues → skip this package, do not crash the scan
                logger.warning(
                    "phantom_package_registry_timeout",
                    package=pkg,
                    ecosystem=ecosystem,
                    error=str(exc),
                )
                skipped_count += 1
                continue
            except Exception as exc:
                logger.warning(
                    "phantom_package_registry_error",
                    package=pkg,
                    ecosystem=ecosystem,
                    error=str(exc),
                )
                skipped_count += 1
                continue

            if not exists:
                # Find the line number of the first import of this package
                line_num = self._find_import_line(code_file.content, pkg)
                suppression_matcher = self._get_suppression_matcher(code_file.path)
                if suppression_matcher and suppression_matcher.is_suppressed(
                    line=line_num,
                    rule=self.id,
                    file_path=str(code_file.path),
                    code=code_file.content,
                ):
                    logger.debug(
                        "finding_suppressed_inline",
                        line=line_num,
                        rule=self.id,
                        file=code_file.path,
                    )
                    continue

                registry_url = (
                    f"https://pypi.org/project/{pkg}/"
                    if ecosystem == "pypi"
                    else f"https://www.npmjs.com/package/{pkg}"
                )
                findings.append(
                    CheckFinding(
                        check_id=self.id,
                        check_name=self.name,
                        severity=self.severity,
                        message=(
                            f"Phantom package detected: '{pkg}' does not exist on "
                            f"{ecosystem.upper()}. This may be an AI-hallucinated "
                            f"package name (slopsquatting risk)."
                        ),
                        location=f"{code_file.path}:{line_num}",
                        code_snippet=self._get_import_line(code_file.content, line_num),
                        suggestion=(
                            f"Verify the package name is correct before installing.\n"
                            f"Search: {registry_url}\n"
                            f"If you need similar functionality, look for verified "
                            f"alternatives in the {ecosystem.upper()} registry."
                        ),
                        documentation_url=(
                            "https://owasp.org/www-project-top-ten/"
                            "2021/A06_2021-Vulnerable_and_Outdated_Components"
                        ),
                    )
                )

        logger.info(
            "phantom_package_check_complete",
            file=code_file.path,
            language=language,
            checked=checked_count,
            skipped=skipped_count,
            phantoms=len(findings),
        )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "ecosystem": ecosystem,
                "packages_checked": checked_count,
                "packages_skipped": skipped_count,
                "packages_flagged": len(findings),
            },
        )

    def _find_import_line(self, content: str, package: str) -> int:
        """Return 1-based line number of first import of `package`."""
        lines = content.split("\n")
        pkg_pattern = re.compile(
            rf"^\s*(?:import\s+{re.escape(package)}(?:\s|$)|from\s+{re.escape(package)}(?:\.|\s))",
        )
        for i, line in enumerate(lines, start=1):
            if pkg_pattern.match(line):
                return i
        return 1

    def _get_import_line(self, content: str, line_num: int) -> str:
        """Return the source line at `line_num` (1-based), stripped."""
        lines = content.split("\n")
        if 1 <= line_num <= len(lines):
            return lines[line_num - 1].strip()
        return ""
