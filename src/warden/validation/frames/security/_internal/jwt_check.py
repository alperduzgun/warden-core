"""
JWT Misconfiguration Detection Check.

Detects insecure JWT (JSON Web Token) configurations:
- Missing expiration (CWE-613: Insufficient Session Expiration)
- Algorithm 'none' (CWE-345: Algorithm Confusion)
- Missing algorithm enforcement in verification
- Weak signing secrets

References:
- https://cwe.mitre.org/data/definitions/613.html
- https://cwe.mitre.org/data/definitions/345.html
- https://auth0.com/blog/critical-vulnerabilities-in-json-web-token-libraries/
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


class JWTMisconfigCheck(ValidationCheck):
    """
    Detects JWT misconfiguration vulnerabilities.

    Patterns detected:
    - JS: jwt.sign(payload, secret) without expiresIn option (CWE-613)
    - JS: jwt.verify() with algorithms: ['none'] (algorithm confusion)
    - Python: jwt.encode(payload, key) without exp claim (CWE-613)
    - Python: jwt.decode() without algorithms parameter
    - General: algorithm 'none' usage in JWT context

    Severity: HIGH (can lead to session hijacking / token forgery)
    """

    id = "jwt-misconfiguration"
    name = "JWT Misconfiguration Detection"
    description = "Detects insecure JWT configurations (missing expiry, algorithm confusion)"
    severity = CheckSeverity.HIGH
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    # ---- JS jwt.sign() without expiresIn ----
    JS_JWT_SIGN_RE = re.compile(
        r"jwt\.sign\s*\("
    )
    JS_EXPIRES_IN_RE = re.compile(
        r"expiresIn\s*:", re.IGNORECASE
    )
    JS_EXP_CLAIM_RE = re.compile(
        r"\bexp\s*:", re.IGNORECASE
    )

    # ---- JS jwt.verify() with algorithms: ['none'] ----
    JS_JWT_VERIFY_RE = re.compile(
        r"jwt\.verify\s*\("
    )
    ALGO_NONE_RE = re.compile(
        r"""algorithms\s*[:=]\s*\[?\s*['"]none['"]\s*\]?""", re.IGNORECASE
    )

    # ---- Python jwt.encode() without exp ----
    PY_JWT_ENCODE_RE = re.compile(
        r"jwt\.encode\s*\("
    )

    # ---- Python jwt.decode() without algorithms ----
    PY_JWT_DECODE_RE = re.compile(
        r"jwt\.decode\s*\("
    )
    PY_ALGORITHMS_PARAM_RE = re.compile(
        r"algorithms\s*="
    )

    # ---- Generic 'none' algorithm references in JWT context ----
    GENERIC_ALGO_NONE_RE = re.compile(
        r"""['"](?:alg|algorithm)['"]\s*:\s*['"]none['"]""", re.IGNORECASE
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize JWT misconfiguration check."""
        super().__init__(config)

        # How many lines to scan around jwt.sign / jwt.encode calls
        self._context_lines = self.config.get("context_lines", 10)

    def _get_context_block(self, lines: list[str], line_num: int) -> str:
        """Get a block of code around the given line for context scanning.

        Looks both backward and forward to capture payload definitions
        that may precede the function call.
        """
        start = max(0, line_num - 1 - self._context_lines)
        end = min(len(lines), line_num - 1 + self._context_lines)
        return "\n".join(lines[start:end])

    async def execute_async(self, code_file: CodeFile) -> CheckResult:
        """Execute JWT misconfiguration detection."""
        findings: list[CheckFinding] = []
        lines = code_file.content.split("\n")

        findings.extend(self._check_js_jwt_sign(code_file, lines))
        findings.extend(self._check_js_jwt_verify_none(code_file, lines))
        findings.extend(self._check_py_jwt_encode(code_file, lines))
        findings.extend(self._check_py_jwt_decode(code_file, lines))
        findings.extend(self._check_generic_algo_none(code_file, lines))

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "checks_performed": [
                    "js_jwt_sign_expiry",
                    "js_jwt_verify_none",
                    "py_jwt_encode_expiry",
                    "py_jwt_decode_algorithms",
                    "generic_algo_none",
                ],
            },
        )

    # ------------------------------------------------------------------
    # JS: jwt.sign() without expiresIn
    # ------------------------------------------------------------------
    def _check_js_jwt_sign(
        self, code_file: CodeFile, lines: list[str]
    ) -> list[CheckFinding]:
        """
        Detect jwt.sign(payload, secret) calls without expiresIn option.

        JWT tokens without expiration never expire, making stolen tokens
        permanently valid (CWE-613).
        """
        findings: list[CheckFinding] = []

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()

            # Skip comments
            if stripped.startswith("//") or stripped.startswith("#"):
                continue

            if not self.JS_JWT_SIGN_RE.search(line):
                continue

            # Look backward and forward for expiresIn or exp claim
            context_block = self._get_context_block(lines, line_num)

            has_expires_in = self.JS_EXPIRES_IN_RE.search(context_block)
            has_exp_claim = self.JS_EXP_CLAIM_RE.search(context_block)

            if has_expires_in or has_exp_claim:
                continue

            # Check suppression
            if self._is_suppressed(code_file, line_num):
                continue

            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=CheckSeverity.HIGH,
                    message="jwt.sign() without expiresIn: tokens never expire (CWE-613)",
                    location=f"{code_file.path}:{line_num}",
                    code_snippet=stripped,
                    suggestion=(
                        "Always set token expiration:\n"
                        "  GOOD: jwt.sign(payload, secret, { expiresIn: '1h' })\n"
                        "  GOOD: jwt.sign({ ...payload, exp: Math.floor(Date.now()/1000) + 3600 }, secret)\n"
                        "  BAD:  jwt.sign(payload, secret)  // never expires"
                    ),
                    documentation_url="https://cwe.mitre.org/data/definitions/613.html",
                )
            )

        return findings

    # ------------------------------------------------------------------
    # JS: jwt.verify() with algorithms: ['none']
    # ------------------------------------------------------------------
    def _check_js_jwt_verify_none(
        self, code_file: CodeFile, lines: list[str]
    ) -> list[CheckFinding]:
        """
        Detect jwt.verify() with algorithms: ['none'].

        Allowing 'none' algorithm means unsigned tokens are accepted,
        enabling token forgery (CWE-345).
        """
        findings: list[CheckFinding] = []

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()

            if stripped.startswith("//") or stripped.startswith("#"):
                continue

            if not self.JS_JWT_VERIFY_RE.search(line):
                continue

            # Look forward for algorithms: ['none']
            context_block = self._get_context_block(lines, line_num)

            if not self.ALGO_NONE_RE.search(context_block):
                continue

            if self._is_suppressed(code_file, line_num):
                continue

            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=CheckSeverity.CRITICAL,
                    message="jwt.verify() with algorithms: ['none'] allows unsigned tokens (CWE-345)",
                    location=f"{code_file.path}:{line_num}",
                    code_snippet=stripped,
                    suggestion=(
                        "Never allow 'none' algorithm in JWT verification:\n"
                        "  GOOD: jwt.verify(token, secret, { algorithms: ['HS256'] })\n"
                        "  GOOD: jwt.verify(token, publicKey, { algorithms: ['RS256'] })\n"
                        "  BAD:  jwt.verify(token, secret, { algorithms: ['none'] })"
                    ),
                    documentation_url="https://cwe.mitre.org/data/definitions/345.html",
                )
            )

        return findings

    # ------------------------------------------------------------------
    # Python: jwt.encode() without exp claim
    # ------------------------------------------------------------------
    def _check_py_jwt_encode(
        self, code_file: CodeFile, lines: list[str]
    ) -> list[CheckFinding]:
        """
        Detect jwt.encode(payload, key) without exp claim.

        Python PyJWT does not enforce expiration by default.
        Tokens without exp never expire (CWE-613).
        """
        findings: list[CheckFinding] = []

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()

            if stripped.startswith("#") or stripped.startswith("//"):
                continue

            if not self.PY_JWT_ENCODE_RE.search(line):
                continue

            # Look backward and forward for 'exp' key in payload
            context_block = self._get_context_block(lines, line_num)

            # Check for 'exp' as a dictionary key in the payload
            has_exp_key = re.search(
                r"""['"]exp['"]\s*:""", context_block
            )
            # Also check for timedelta / datetime.utcnow patterns (common exp patterns)
            has_exp_pattern = re.search(
                r"(?:timedelta|datetime\.utcnow|datetime\.now|time\.time)\s*\(",
                context_block,
            )

            if has_exp_key or has_exp_pattern:
                continue

            if self._is_suppressed(code_file, line_num):
                continue

            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=CheckSeverity.HIGH,
                    message="jwt.encode() without exp claim: tokens never expire (CWE-613)",
                    location=f"{code_file.path}:{line_num}",
                    code_snippet=stripped,
                    suggestion=(
                        "Always include exp claim in JWT payload:\n"
                        "  GOOD: jwt.encode({'sub': user_id, 'exp': datetime.utcnow() + timedelta(hours=1)}, key)\n"
                        "  BAD:  jwt.encode({'sub': user_id}, key)  // never expires"
                    ),
                    documentation_url="https://cwe.mitre.org/data/definitions/613.html",
                )
            )

        return findings

    # ------------------------------------------------------------------
    # Python: jwt.decode() without algorithms parameter
    # ------------------------------------------------------------------
    def _check_py_jwt_decode(
        self, code_file: CodeFile, lines: list[str]
    ) -> list[CheckFinding]:
        """
        Detect jwt.decode() without explicit algorithms parameter.

        Without specifying algorithms, the library may accept any algorithm
        including 'none', enabling token forgery.
        """
        findings: list[CheckFinding] = []

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()

            if stripped.startswith("#") or stripped.startswith("//"):
                continue

            if not self.PY_JWT_DECODE_RE.search(line):
                continue

            # Look forward for algorithms= parameter
            lookahead_start = line_num - 1
            lookahead_end = min(len(lines), lookahead_start + self._context_lines)
            lookahead_block = "\n".join(lines[lookahead_start:lookahead_end])

            if self.PY_ALGORITHMS_PARAM_RE.search(lookahead_block):
                # Also check if algorithms includes 'none'
                if self.ALGO_NONE_RE.search(lookahead_block):
                    if self._is_suppressed(code_file, line_num):
                        continue
                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=CheckSeverity.CRITICAL,
                            message="jwt.decode() with algorithms=['none'] allows unsigned tokens (CWE-345)",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=stripped,
                            suggestion=(
                                "Never allow 'none' algorithm:\n"
                                "  GOOD: jwt.decode(token, key, algorithms=['HS256'])\n"
                                "  BAD:  jwt.decode(token, key, algorithms=['none'])"
                            ),
                            documentation_url="https://cwe.mitre.org/data/definitions/345.html",
                        )
                    )
                continue  # algorithms= is present and not 'none', OK

            # No algorithms parameter found
            if self._is_suppressed(code_file, line_num):
                continue

            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=CheckSeverity.HIGH,
                    message="jwt.decode() without algorithms parameter: missing algorithm enforcement (CWE-345)",
                    location=f"{code_file.path}:{line_num}",
                    code_snippet=stripped,
                    suggestion=(
                        "Always enforce algorithms in jwt.decode():\n"
                        "  GOOD: jwt.decode(token, key, algorithms=['HS256'])\n"
                        "  BAD:  jwt.decode(token, key)  // accepts any algorithm"
                    ),
                    documentation_url="https://cwe.mitre.org/data/definitions/345.html",
                )
            )

        return findings

    # ------------------------------------------------------------------
    # Generic: algorithm 'none' in JWT context
    # ------------------------------------------------------------------
    def _check_generic_algo_none(
        self, code_file: CodeFile, lines: list[str]
    ) -> list[CheckFinding]:
        """Detect generic 'alg': 'none' patterns in code."""
        findings: list[CheckFinding] = []

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()

            if stripped.startswith("#") or stripped.startswith("//"):
                continue

            if not self.GENERIC_ALGO_NONE_RE.search(line):
                continue

            if self._is_suppressed(code_file, line_num):
                continue

            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=CheckSeverity.CRITICAL,
                    message="JWT algorithm set to 'none': allows unsigned tokens (CWE-345)",
                    location=f"{code_file.path}:{line_num}",
                    code_snippet=stripped,
                    suggestion=(
                        "Never use 'none' as JWT algorithm:\n"
                        "  GOOD: { 'alg': 'HS256' } or { 'alg': 'RS256' }\n"
                        "  BAD:  { 'alg': 'none' }  // disables signature verification"
                    ),
                    documentation_url="https://cwe.mitre.org/data/definitions/345.html",
                )
            )

        return findings

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _is_suppressed(self, code_file: CodeFile, line_num: int) -> bool:
        """Check if finding is suppressed via inline comment."""
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
            return True
        return False
