"""
Stale/Deprecated API Detection Check.

Detects usage of deprecated or insecure APIs that should be replaced
with safer, modern alternatives.
"""

import re
from typing import Any

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.check import (
    CheckFinding,
    CheckResult,
    CheckSeverity,
    ValidationCheck,
)
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)

# Map string severity labels to CheckSeverity enum
_SEVERITY_MAP: dict[str, CheckSeverity] = {
    "critical": CheckSeverity.CRITICAL,
    "high": CheckSeverity.HIGH,
    "medium": CheckSeverity.MEDIUM,
    "low": CheckSeverity.LOW,
    "info": CheckSeverity.INFO,
}

# Language normalization aliases
_LANGUAGE_ALIASES: dict[str, str] = {
    "js": "javascript",
    "ts": "javascript",
    "typescript": "javascript",
    "jsx": "javascript",
    "tsx": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "py": "python",
    "python3": "python",
}


class StaleAPICheck(ValidationCheck):
    """
    Detects usage of deprecated or insecure APIs.

    Patterns detected (Python):
    - hashlib.md5 / hashlib.sha1 for cryptographic use
    - os.popen (deprecated subprocess alternative)
    - cgi.parse (deprecated in Python 3.11)
    - imp.load_module (deprecated since Python 3.4)
    - optparse (deprecated since Python 3.2)
    - pickle.loads on untrusted data (RCE risk)
    - yaml.load without SafeLoader (code execution risk)
    - eval() on untrusted input (code execution risk)
    - requests verify=False / ssl.CERT_NONE / check_hostname=False (TLS bypass)

    Patterns detected (JavaScript/Node.js):
    - new Buffer() (deprecated since Node.js 6.0)
    - fs.exists() (deprecated since Node.js 4.0)
    - crypto.createCipher() (use createCipheriv instead)
    - url.parse() (deprecated since Node.js 11.0)
    - require('querystring') (deprecated since Node.js 14.0)

    Severity: varies per pattern (see DEPRECATED_APIS)
    """

    id = "stale-api"
    name = "Deprecated API Detection"
    description = "Detects usage of deprecated or insecure APIs that have safer replacements"
    severity = CheckSeverity.HIGH
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    # Embedded database — no YAML files, KISS principle
    DEPRECATED_APIS: list[dict[str, str]] = [
        # ----------------------------------------------------------------
        # Python
        # ----------------------------------------------------------------
        {
            "pattern": r"hashlib\.md5\(",
            "replacement": "hashlib.sha256()",
            "language": "python",
            "severity": "high",
            "reason": "MD5 is cryptographically broken",
        },
        {
            "pattern": r"hashlib\.sha1\(",
            "replacement": "hashlib.sha256()",
            "language": "python",
            "severity": "medium",
            "reason": "SHA1 is deprecated for security use",
        },
        {
            "pattern": r"os\.popen\(",
            "replacement": "subprocess.run()",
            "language": "python",
            "severity": "high",
            "reason": "os.popen is deprecated since Python 3.0",
        },
        {
            "pattern": r"cgi\.parse\(",
            "replacement": "urllib.parse",
            "language": "python",
            "severity": "medium",
            "reason": "cgi module deprecated in Python 3.11",
        },
        {
            "pattern": r"imp\.load_module\(",
            "replacement": "importlib",
            "language": "python",
            "severity": "medium",
            "reason": "imp module deprecated since Python 3.4",
        },
        {
            "pattern": r"optparse\.",
            "replacement": "argparse",
            "language": "python",
            "severity": "low",
            "reason": "optparse deprecated since Python 3.2",
        },
        {
            "pattern": r"pickle\.loads?\(",
            "replacement": "json.loads() or restricted unpickler",
            "language": "python",
            "severity": "high",
            "reason": "pickle.loads on untrusted data = RCE risk (CWE-502)",
        },
        {
            "pattern": r"yaml\.load\((?!.*Loader)",
            "replacement": "yaml.safe_load()",
            "language": "python",
            "severity": "high",
            "reason": "yaml.load without SafeLoader = code execution risk",
        },
        {
            "pattern": r"(?<!\w)eval\(",
            "replacement": "ast.literal_eval() or JSON parsing",
            "language": "python",
            "severity": "high",
            "reason": "eval() on untrusted input = code execution (CWE-95)",
        },
        {
            "pattern": r"\.from_string\(",
            "replacement": "Use pre-compiled templates from files, never from user input",
            "language": "python",
            "severity": "critical",
            "reason": "Server-Side Template Injection (SSTI) — user-controlled template string = RCE (CWE-1336)",
        },
        {
            "pattern": r"setattr\(\s*\w+,\s*(?:key|k|attr|field|name)\s*,",
            "replacement": "Use an allowlist of permitted attributes",
            "language": "python",
            "severity": "high",
            "reason": "Dynamic setattr with user-controlled key = attribute injection (CWE-915)",
        },
        {
            "pattern": r"yaml\.unsafe_load\(",
            "replacement": "yaml.safe_load()",
            "language": "python",
            "severity": "critical",
            "reason": "yaml.unsafe_load allows arbitrary object instantiation = RCE (CWE-502)",
        },
        {
            "pattern": r"traceback\.format_exc\(\)",
            "replacement": "Log the traceback server-side, return generic error to client",
            "language": "python",
            "severity": "high",
            "reason": "Returning traceback to client leaks internal details (CWE-209)",
        },
        {
            "pattern": r"subprocess\.(?:call|run|Popen)\(.*shell\s*=\s*True",
            "replacement": "subprocess.run([cmd, arg], shell=False)",
            "language": "python",
            "severity": "high",
            "reason": "shell=True enables command injection (CWE-78)",
        },
        {
            "pattern": r"app\.run\(.*debug\s*=\s*True",
            "replacement": "app.run(debug=False) or use FLASK_DEBUG env var",
            "language": "python",
            "severity": "medium",
            "reason": "Debug mode in production exposes debugger and stack traces (CWE-489)",
        },
        {
            "pattern": r"random\.randint\(|random\.choice\(|random\.random\(",
            "replacement": "secrets.token_hex() or secrets.randbelow()",
            "language": "python",
            "severity": "medium",
            "reason": "random module is not cryptographically secure (CWE-330)",
        },
        # ----------------------------------------------------------------
        # TLS / Certificate Validation (Python)
        # ----------------------------------------------------------------
        {
            "pattern": r"verify\s*=\s*False",
            "replacement": "verify=True (default) or verify='/path/to/ca-bundle.crt'",
            "language": "python",
            "severity": "high",
            "reason": "TLS certificate verification disabled — susceptible to MITM attacks (CWE-295)",
        },
        {
            "pattern": r"ssl\.CERT_NONE",
            "replacement": "ssl.CERT_REQUIRED",
            "language": "python",
            "severity": "high",
            "reason": "SSL context accepts any certificate — MITM attacks possible (CWE-295)",
        },
        {
            "pattern": r"check_hostname\s*=\s*False",
            "replacement": "ctx.check_hostname = True",
            "language": "python",
            "severity": "high",
            "reason": "Hostname verification disabled — server identity not validated (CWE-297)",
        },
        # ----------------------------------------------------------------
        # JavaScript / Node.js
        # ----------------------------------------------------------------
        {
            "pattern": r"new Buffer\(",
            "replacement": "Buffer.from() or Buffer.alloc()",
            "language": "javascript",
            "severity": "high",
            "reason": "new Buffer() deprecated since Node.js 6.0",
        },
        {
            "pattern": r"fs\.exists\(",
            "replacement": "fs.existsSync() or fs.access()",
            "language": "javascript",
            "severity": "medium",
            "reason": "fs.exists deprecated since Node.js 4.0",
        },
        {
            "pattern": r"crypto\.createCipher\(",
            "replacement": "crypto.createCipheriv()",
            "language": "javascript",
            "severity": "high",
            "reason": "createCipher deprecated, use createCipheriv with IV",
        },
        {
            "pattern": r"url\.parse\(",
            "replacement": "new URL()",
            "language": "javascript",
            "severity": "low",
            "reason": "url.parse deprecated since Node.js 11.0",
        },
        {
            "pattern": r"require\(['\"]querystring['\"]\)",
            "replacement": "URLSearchParams",
            "language": "javascript",
            "severity": "low",
            "reason": "querystring deprecated since Node.js 14.0",
        },
        # ----------------------------------------------------------------
        # Python — Dunder / Prototype-style Injection via dict iteration
        #
        # In JavaScript, "prototype pollution" mutates Object.prototype via
        # __proto__.  Python has no prototype chain, but the equivalent
        # attack targets Python's dunder attributes (__class__, __init__,
        # __globals__, __subclasses__) on objects that get merged from
        # user-controlled dicts.  Both patterns below fire on the
        # deep_merge / dict-update anti-pattern.
        # ----------------------------------------------------------------
        {
            # Pattern 1 — JS-style __proto__-only guard.
            # Filtering "__proto__" is meaningless in Python; the dangerous
            # names are __class__, __init__, __globals__, __subclasses__, etc.
            # A __proto__ check is the tell-tale sign of an incomplete port
            # from JavaScript and signals that Python dunders are unguarded.
            "pattern": r'key\s*==\s*["\']__proto__["\']',
            "replacement": (
                "Replace the JS-style __proto__ guard with a Python dunder blocklist: "
                "if isinstance(key, str) and key.startswith('__') and key.endswith('__'): continue"
            ),
            "language": "python",
            "severity": "high",
            "reason": (
                "JS-style __proto__ guard is ineffective in Python. "
                "Python dunder-injection uses __class__, __init__, __globals__, "
                "and __subclasses__ — none of which are blocked by this check. "
                "Use a dunder-key blocklist (CWE-915)."
            ),
        },
        {
            # Pattern 2 — unguarded subscript assignment using a typical loop-key variable.
            # Matches the canonical deep-merge write line:
            #   base[key] = value      (key/k/name/attr/field as the subscript index)
            # Anchoring on common loop-variable names keeps the signal tight while
            # still catching the dominant real-world spelling of this pattern.
            #
            # TAINT-AWARE: this pattern is only reported when a taint source
            # (request.json, request.form, request.args, etc.) appears within
            # ±10 lines of the match.  Internal dict iteration over hardcoded
            # data is safe and must not be flagged.  See _is_taint_context().
            "pattern": r"^\s*\w+\[(?:key|k|name|attr|field)\]\s*=\s*\w",
            "id": "dunder-subscript-assign",
            "replacement": (
                "Add a dunder-key guard before assigning: "
                "if isinstance(key, str) and key.startswith('__') and key.endswith('__'): continue"
            ),
            "language": "python",
            "severity": "high",
            "reason": (
                "Unguarded dict-key assignment inside a loop may allow Python "
                "dunder-attribute injection (__class__, __init__, __globals__, "
                "__subclasses__) leading to attribute pollution or RCE (CWE-915). "
                "Validate or blocklist dunder keys before merging user-controlled dicts."
            ),
        },
    ]

    # Regex that matches known user-input taint sources in Python code.
    # Used by _is_taint_context() to decide whether the dunder-subscript
    # pattern fires in a given context window.
    _TAINT_SOURCE_RE = re.compile(
        r"""
        request\s*\.\s*(?:json|form|args|data|values|get_json|files|cookies)
        | flask\.request
        | django\.http
        | cherrypy\.request
        | bottle\.request
        | fastapi\s*\.\s*Request
        | request\.POST
        | request\.GET
        | request\.body
        | environ\.get\s*\(
        | input\s*\(           # bare input() call
        | sys\.argv
        """,
        re.VERBOSE,
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize stale API check and pre-compile patterns."""
        super().__init__(config)

        # Pre-compile patterns grouped by language for fast lookup
        self._compiled: list[tuple[re.Pattern, dict[str, str]]] = [
            (re.compile(entry["pattern"]), entry)
            for entry in self.DEPRECATED_APIS
        ]

    def _normalize_language(self, language: str | None) -> str:
        """Normalize language string to a canonical form."""
        if not language:
            return ""
        normalized = language.lower().strip()
        return _LANGUAGE_ALIASES.get(normalized, normalized)

    def _is_taint_context(
        self,
        lines: list[str],
        match_line_index: int,
        window: int = 10,
    ) -> bool:
        """Return True when a user-input taint source appears near the match.

        Scans ``window`` lines above and below ``match_line_index`` (0-based)
        for any pattern in ``_TAINT_SOURCE_RE``.  Only lines that could
        plausibly introduce taint are considered; pure comment lines are
        excluded.

        This heuristic lets the dunder-subscript pattern skip safe internal
        dict iteration (e.g. ``for key, col in field_map.items()``) while
        still firing on user-controlled merges like
        ``for key, val in request.json.items()``.

        Args:
            lines: All source lines of the file (0-based list).
            match_line_index: 0-based index of the line that matched.
            window: Number of lines to scan above and below the match.

        Returns:
            True if at least one taint source is found in the context window.
        """
        start = max(0, match_line_index - window)
        end = min(len(lines), match_line_index + window + 1)

        for i in range(start, end):
            candidate = lines[i]
            # Skip pure comment lines — they cannot be taint sources
            if candidate.lstrip().startswith("#"):
                continue
            if self._TAINT_SOURCE_RE.search(candidate):
                return True

        return False

    async def execute_async(self, code_file: CodeFile, context=None) -> CheckResult:
        """
        Execute deprecated API detection.

        Args:
            code_file: Code file to check

        Returns:
            CheckResult with findings
        """
        findings: list[CheckFinding] = []
        file_language = self._normalize_language(code_file.language)

        lines = code_file.content.split("\n")

        for compiled_pattern, entry in self._compiled:
            entry_language = self._normalize_language(entry["language"])

            # Skip patterns that don't apply to this file's language
            if file_language and entry_language and file_language != entry_language:
                continue

            for line_num, line in enumerate(lines, start=1):
                # Skip pure comment lines to avoid false positives on
                # documentation that mentions an insecure API by name.
                if line.lstrip().startswith("#"):
                    continue

                if not compiled_pattern.search(line):
                    continue

                # Taint-context guard for the dunder-subscript pattern.
                # Because `^\s*\w+[key] = \w` matches ANY dict assignment with
                # those variable names (including safe internal iteration), we
                # only report it when a user-input taint source appears within
                # ±10 lines.  If no taint source is nearby the code is
                # considered safe and we skip the finding.
                if entry.get("id") == "dunder-subscript-assign":
                    line_index = line_num - 1  # convert to 0-based
                    if not self._is_taint_context(lines, line_index):
                        logger.debug(
                            "dunder_subscript_suppressed_no_taint",
                            line=line_num,
                            file=code_file.path,
                        )
                        continue

                # Respect inline suppressions
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

                severity = _SEVERITY_MAP.get(entry["severity"], CheckSeverity.MEDIUM)

                findings.append(
                    CheckFinding(
                        check_id=self.id,
                        check_name=self.name,
                        severity=severity,
                        message=(
                            f"Deprecated API: {entry['reason']}"
                        ),
                        location=f"{code_file.path}:{line_num}",
                        code_snippet=line.strip(),
                        suggestion=(
                            f"Replace with: {entry['replacement']}\n"
                            f"Reason: {entry['reason']}"
                        ),
                        documentation_url="https://owasp.org/www-project-top-ten/",
                    )
                )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "patterns_checked": len(self._compiled),
                "file_language": file_language,
            },
        )
