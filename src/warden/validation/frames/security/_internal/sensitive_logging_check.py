"""
Sensitive Data in Logs Detection Check (CWE-532).

Detects cases where passwords, tokens, secrets, or PII are passed
directly to logging functions without masking/redaction.
"""

import re

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.check import (
    CheckFinding,
    CheckResult,
    CheckSeverity,
    ValidationCheck,
)
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)

# Sensitive variable/parameter name fragments (case-insensitive)
_SENSITIVE_NAMES = re.compile(
    r"\b(password|passwd|pwd|secret|api_key|apikey|token|auth_token|"
    r"access_token|refresh_token|private_key|privkey|credential|credit_card|"
    r"card_number|cvv|ssn|social_security|dob|date_of_birth|"
    r"bearer|authorization|x-api-key)\b",
    re.IGNORECASE,
)

# Logging sink patterns — Python, JS/TS, Go, Java
_LOG_SINK_PATTERNS = [
    # Python standard logging + print
    re.compile(
        r"\b(logging\.(debug|info|warning|error|critical|exception)"
        r"|logger\.(debug|info|warning|error|critical|exception|warn)"
        r"|print)\s*\(",
        re.IGNORECASE,
    ),
    # JavaScript / TypeScript
    re.compile(
        r"\b(console\.(log|error|warn|debug|info|trace)"
        r"|logger\.(debug|info|warning|error|warn))\s*\(",
        re.IGNORECASE,
    ),
    # Go
    re.compile(
        r"\b(log\.(Print|Printf|Println|Fatal|Fatalf|Fatalln|Panic|Panicf)"
        r"|fmt\.(Print|Printf|Println|Fprintf|Errorf))\s*\(",
    ),
    # Java / Android
    re.compile(
        r"\b(System\.out\.print(ln|f)?"
        r"|System\.err\.print(ln|f)?"
        r"|Log\.(d|i|e|w|v)\s*\("
        r"|logger\.(debug|info|warn|error)\s*\()",
        re.IGNORECASE,
    ),
]

# Known sanitizers / redactors — suppress finding if present nearby
_SANITIZERS = re.compile(
    r"\b(mask|redact|sanitize|scrub|anonymize|obfuscat|PIIMask|"
    r"mask_sensitive|mask_pii|re\.sub|replace\(.*\*+|hash\(|hmac\()",
    re.IGNORECASE,
)

# f-string / format / concatenation patterns that include a sensitive name
# These are used to detect `f"...{password}..."` or `"..." + token`
_FSTRING_SENSITIVE = re.compile(
    r'\{[^}]*'
    r'(password|passwd|pwd|secret|api_key|apikey|token|auth_token|'
    r'access_token|refresh_token|private_key|credential|credit_card|'
    r'card_number|cvv|ssn|bearer|authorization)[^}]*\}',
    re.IGNORECASE,
)


class SensitiveLoggingCheck(ValidationCheck):
    """
    Detects sensitive data (passwords, tokens, secrets) logged in plaintext.

    Patterns detected:
    - logging.info(f"Password: {password}")
    - console.log("token:", token)
    - logger.debug(f"API key: {api_key}")
    - print(f"secret={secret}")

    Severity: MEDIUM (PII/credential exposure via log files)
    """

    id = "sensitive-logging"
    name = "Sensitive Data in Logs"
    description = "Detects passwords, tokens, and secrets logged in plaintext (CWE-532)"
    severity = CheckSeverity.MEDIUM
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    async def execute_async(self, code_file: CodeFile, context=None) -> CheckResult:
        """Execute sensitive logging detection."""
        findings: list[CheckFinding] = []
        lines = code_file.content.split("\n")

        for idx, line in enumerate(lines):
            line_num = idx + 1

            # Skip comment lines
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*", "/*")):
                continue

            # Must be a logging call
            is_log_sink = any(pat.search(line) for pat in _LOG_SINK_PATTERNS)
            if not is_log_sink:
                continue

            # Strip inline comment before checking for sensitive names
            # so that  logger.info("ok")  # no secret  doesn't false-positive.
            code_part = line.split("  #")[0].split(" //")[0]

            # Detect sensitive name in:
            # (a) f-string interpolation: f"{password}"
            # (b) direct argument: logger.info(password) — sensitive name as bare word
            has_fstring = bool(_FSTRING_SENSITIVE.search(code_part))
            has_direct = bool(_SENSITIVE_NAMES.search(code_part))

            if not has_fstring and not has_direct:
                continue

            # Suppress if sanitizer is visible in the code part of the line
            if _SANITIZERS.search(code_part):
                continue

            # Check inline suppression
            suppression_matcher = self._get_suppression_matcher(code_file.path)
            if suppression_matcher and suppression_matcher.is_suppressed(
                line=line_num,
                rule=self.id,
                file_path=str(code_file.path),
                code=code_file.content,
            ):
                continue

            # Extract the sensitive name for the message
            match = _SENSITIVE_NAMES.search(code_part)
            sensitive_name = match.group(0) if match else "sensitive value"

            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=self.severity,
                    message=f"Sensitive data in log: '{sensitive_name}' logged in plaintext",
                    location=f"{code_file.path}:{line_num}",
                    code_snippet=line.strip(),
                    suggestion=(
                        "Mask or redact sensitive values before logging:\n"
                        "✅ GOOD: logger.info('Login attempt', user=user_id)  # no secret\n"
                        "✅ GOOD: logger.debug('token=%s', mask(token))        # masked\n"
                        "❌ BAD:  logger.info(f'token={token}')                # plaintext"
                    ),
                    documentation_url="https://cwe.mitre.org/data/definitions/532.html",
                )
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
        )
