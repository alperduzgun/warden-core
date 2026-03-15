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
    - formatter module (deprecated since Python 3.4)
    - pickle.loads on untrusted data (RCE risk)
    - yaml.load without SafeLoader (code execution risk)
    - eval() on untrusted input (code execution risk)

    Patterns detected (JavaScript/Node.js):
    - new Buffer() (deprecated since Node.js 6.0)
    - fs.exists() (deprecated since Node.js 4.0)
    - crypto.createCipher() (use createCipheriv instead)
    - url.parse() (deprecated since Node.js 11.0)
    - querystring module (deprecated since Node.js 14.0)
    - domain module (deprecated since Node.js 4.0)

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
            "pattern": r"formatter\.",
            "replacement": "custom formatter",
            "language": "python",
            "severity": "low",
            "reason": "formatter module deprecated since Python 3.4",
        },
        {
            "pattern": r"pickle\.loads?\(",
            "replacement": "json.loads() or restricted unpickler",
            "language": "python",
            "severity": "high",
            "reason": "pickle.loads on untrusted data = RCE risk (CWE-502)",
        },
        {
            "pattern": r"yaml\.load\([^)]*\)(?!.*Loader)",
            "replacement": "yaml.safe_load()",
            "language": "python",
            "severity": "high",
            "reason": "yaml.load without SafeLoader = code execution risk",
        },
        {
            "pattern": r"eval\(",
            "replacement": "ast.literal_eval() or JSON parsing",
            "language": "python",
            "severity": "high",
            "reason": "eval() on untrusted input = code execution (CWE-95)",
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
            "pattern": r"querystring\.",
            "replacement": "URLSearchParams",
            "language": "javascript",
            "severity": "low",
            "reason": "querystring deprecated since Node.js 14.0",
        },
        {
            "pattern": r"domain\.",
            "replacement": "async_hooks or try/catch",
            "language": "javascript",
            "severity": "medium",
            "reason": "domain module deprecated since Node.js 4.0",
        },
    ]

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

    async def execute_async(self, code_file: CodeFile) -> CheckResult:
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
                if not compiled_pattern.search(line):
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
