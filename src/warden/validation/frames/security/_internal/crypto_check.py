"""
Weak Cryptography Detection Check.

Detects use of weak or insecure cryptographic algorithms and modes:
- MD5/SHA1 used for password hashing (CWE-328)
- DES, RC4 cipher usage (CWE-327)
- ECB cipher mode (CWE-327)

References:
- https://cwe.mitre.org/data/definitions/327.html
- https://cwe.mitre.org/data/definitions/328.html
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


class WeakCryptoCheck(ValidationCheck):
    """
    Detects weak cryptographic algorithms and insecure cipher modes.

    Patterns detected:
    - Python: hashlib.md5() / hashlib.sha1() for password hashing
    - Python: DES / RC4 / ECB mode in PyCryptodome / cryptography lib
    - JavaScript: crypto.createHash('md5') / crypto.createHash('sha1')
    - JavaScript: crypto.createCipher('des', ...) / crypto.createCipher('rc4', ...)
    - General: AES.MODE_ECB / AES-ECB references

    Severity: HIGH (weak crypto can lead to credential compromise)
    """

    id = "weak-crypto"
    name = "Weak Cryptography Detection"
    description = "Detects weak hashing algorithms and insecure cipher modes"
    severity = CheckSeverity.HIGH
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    # --- Password-context heuristics ---
    # Variable/function names that indicate password hashing context
    PASSWORD_CONTEXT_KEYWORDS = [
        "password",
        "passwd",
        "pwd",
        "credential",
        "auth",
        "login",
        "signup",
        "register",
        "hash_password",
        "check_password",
        "verify_password",
        "encrypt_password",
    ]

    # Non-password contexts where MD5/SHA1 are acceptable.
    # These are matched as whole words (word-boundary patterns) to avoid
    # false matches on method names like .hexdigest().
    SAFE_CONTEXT_KEYWORDS = [
        r"\bchecksum\b",
        r"\bcache[_-]?key\b",
        r"\bcache\b",
        r"\betag\b",
        r"\bfingerprint\b",
        r"\bfile_hash\b",
        r"\bcontent_hash\b",
        r"\bmd5sum\b",
        r"\bsha1sum\b",
        r"\bintegrity\b",
        r"\bfile_digest\b",
        r"\bmessage_digest\b",
    ]

    # --- Weak hash patterns ---
    WEAK_HASH_PATTERNS = [
        # Python: hashlib.md5( / hashlib.sha1(
        (
            r"hashlib\.md5\s*\(",
            "hashlib.md5() used for hashing",
            "python",
        ),
        (
            r"hashlib\.sha1\s*\(",
            "hashlib.sha1() used for hashing",
            "python",
        ),
        # JavaScript: crypto.createHash('md5') / crypto.createHash("md5")
        (
            r"crypto\.createHash\s*\(\s*['\"]md5['\"]\s*\)",
            "crypto.createHash('md5') weak hash",
            "javascript",
        ),
        (
            r"crypto\.createHash\s*\(\s*['\"]sha1['\"]\s*\)",
            "crypto.createHash('sha1') weak hash",
            "javascript",
        ),
    ]

    # --- Weak cipher / mode patterns ---
    WEAK_CIPHER_PATTERNS = [
        # ECB mode (Python - PyCryptodome)
        (
            r"AES\.MODE_ECB",
            "AES ECB mode is insecure (no diffusion)",
            "python",
        ),
        (
            r"DES\.MODE_",
            "DES cipher is broken (56-bit key)",
            "python",
        ),
        (
            r"DES3?\.new\s*\(",
            "DES cipher usage detected",
            "python",
        ),
        (
            r"ARC4\.new\s*\(",
            "RC4 cipher is broken",
            "python",
        ),
        # Python - cryptography lib
        (
            r"algorithms\.TripleDES\s*\(",
            "3DES is deprecated and weak",
            "python",
        ),
        (
            r"modes\.ECB\s*\(",
            "ECB mode is insecure (no diffusion)",
            "python",
        ),
        # Cipher.new(key, AES.MODE_ECB)
        (
            r"Cipher\.new\s*\([^)]*MODE_ECB",
            "Cipher initialized with insecure ECB mode",
            "python",
        ),
        # JavaScript: crypto.createCipher / crypto.createCipheriv with weak algos
        (
            r"crypto\.createCipher(?:iv)?\s*\(\s*['\"]des['\"]",
            "DES cipher is broken (56-bit key)",
            "javascript",
        ),
        (
            r"crypto\.createCipher(?:iv)?\s*\(\s*['\"]rc4['\"]",
            "RC4 cipher is broken",
            "javascript",
        ),
        (
            r"crypto\.createCipher(?:iv)?\s*\(\s*['\"]des-ede['\"]",
            "3DES is deprecated and weak",
            "javascript",
        ),
        # Generic ECB references across languages
        (
            r"['\"]aes-\d+-ecb['\"]",
            "AES-ECB mode is insecure",
            "any",
        ),
        (
            r"['\"]ECB['\"]",
            "ECB mode reference detected",
            "any",
        ),
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize weak crypto check."""
        super().__init__(config)

        # Pre-compile weak hash patterns
        self._compiled_hash_patterns = [
            (re.compile(pattern_str, re.IGNORECASE), description, lang)
            for pattern_str, description, lang in self.WEAK_HASH_PATTERNS
        ]

        # Pre-compile weak cipher patterns
        self._compiled_cipher_patterns = [
            (re.compile(pattern_str), description, lang)
            for pattern_str, description, lang in self.WEAK_CIPHER_PATTERNS
        ]

        # Pre-compile context keywords
        self._password_context_re = re.compile(
            "|".join(self.PASSWORD_CONTEXT_KEYWORDS), re.IGNORECASE
        )
        # Safe context patterns already include word boundaries
        self._compiled_safe_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.SAFE_CONTEXT_KEYWORDS
        ]

    async def execute_async(self, code_file: CodeFile) -> CheckResult:
        """Execute weak cryptography detection."""
        findings: list[CheckFinding] = []
        lines = code_file.content.split("\n")

        # Detect weak hash usage
        findings.extend(self._check_weak_hashes(code_file, lines))

        # Detect weak cipher / mode usage
        findings.extend(self._check_weak_ciphers(code_file, lines))

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "hash_patterns_checked": len(self._compiled_hash_patterns),
                "cipher_patterns_checked": len(self._compiled_cipher_patterns),
            },
        )

    def _check_weak_hashes(
        self, code_file: CodeFile, lines: list[str]
    ) -> list[CheckFinding]:
        """
        Check for weak hash algorithms used in password context.

        MD5/SHA1 are acceptable for checksums, cache keys, and ETags,
        but not for password hashing or credential verification.
        """
        findings: list[CheckFinding] = []

        # Build a set of line numbers that are in password-related context
        # by scanning function names, variable names, and comments
        password_context_lines = self._find_password_context_lines(lines)

        for compiled_pattern, description, lang in self._compiled_hash_patterns:
            for line_num, line in enumerate(lines, start=1):
                stripped = line.strip()

                # Skip comments
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue

                match = compiled_pattern.search(line)
                if not match:
                    continue

                # Check if this line is in a safe (non-password) context
                if self._is_safe_hash_context(line, lines, line_num):
                    continue

                # If we are in a password context, this is definitely a finding
                # If not in an explicit password context, check the surrounding lines
                in_password_context = line_num in password_context_lines
                if not in_password_context:
                    # Check surrounding lines (5 lines before and after)
                    nearby_range = range(
                        max(1, line_num - 5), min(len(lines) + 1, line_num + 6)
                    )
                    in_password_context = any(
                        ln in password_context_lines for ln in nearby_range
                    )

                if not in_password_context:
                    continue

                # Check suppression
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

                findings.append(
                    CheckFinding(
                        check_id=self.id,
                        check_name=self.name,
                        severity=CheckSeverity.HIGH,
                        message=f"Weak hash for password context: {description} (CWE-328)",
                        location=f"{code_file.path}:{line_num}",
                        code_snippet=stripped,
                        suggestion=(
                            "Use a proper password hashing algorithm:\n"
                            "  GOOD: bcrypt.hashpw(password, bcrypt.gensalt())\n"
                            "  GOOD: hashlib.pbkdf2_hmac('sha256', password, salt, 100000)\n"
                            "  GOOD: argon2.hash(password)\n"
                            "  BAD:  hashlib.md5(password).hexdigest()"
                        ),
                        documentation_url="https://cwe.mitre.org/data/definitions/328.html",
                    )
                )

        return findings

    def _check_weak_ciphers(
        self, code_file: CodeFile, lines: list[str]
    ) -> list[CheckFinding]:
        """Check for weak cipher algorithms and insecure modes (DES, RC4, ECB)."""
        findings: list[CheckFinding] = []

        for compiled_pattern, description, lang in self._compiled_cipher_patterns:
            for line_num, line in enumerate(lines, start=1):
                stripped = line.strip()

                # Skip comments
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue

                match = compiled_pattern.search(line)
                if not match:
                    continue

                # Check suppression
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

                findings.append(
                    CheckFinding(
                        check_id=self.id,
                        check_name=self.name,
                        severity=CheckSeverity.HIGH,
                        message=f"Insecure cipher/mode: {description} (CWE-327)",
                        location=f"{code_file.path}:{line_num}",
                        code_snippet=stripped,
                        suggestion=(
                            "Use strong, modern cryptographic algorithms:\n"
                            "  GOOD: AES-256-GCM (authenticated encryption)\n"
                            "  GOOD: ChaCha20-Poly1305\n"
                            "  BAD:  DES, RC4, ECB mode (broken/insecure)"
                        ),
                        documentation_url="https://cwe.mitre.org/data/definitions/327.html",
                    )
                )

        return findings

    def _find_password_context_lines(self, lines: list[str]) -> set[int]:
        """
        Find line numbers that are in a password-related context.

        Scans for function definitions, variable assignments, and comments
        containing password-related keywords.
        """
        password_lines: set[int] = set()

        for line_num, line in enumerate(lines, start=1):
            if self._password_context_re.search(line):
                password_lines.add(line_num)

        return password_lines

    def _is_safe_hash_context(
        self, line: str, lines: list[str], line_num: int
    ) -> bool:
        """
        Check if the weak hash usage is in a safe (non-password) context.

        Safe contexts include: checksum calculation, cache key generation,
        ETag computation, file integrity checks.
        Uses word-boundary patterns to avoid false matches (e.g. .hexdigest()).
        """
        # Check the current line for safe context keywords
        if any(p.search(line) for p in self._compiled_safe_patterns):
            return True

        # Check nearby lines (3 before) for safe context
        start = max(0, line_num - 4)
        for nearby_line in lines[start : line_num - 1]:
            if any(p.search(nearby_line) for p in self._compiled_safe_patterns):
                return True

        return False
