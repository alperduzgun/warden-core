"""
Cross-File Taint Detection Check.

Detects security issues that span multiple files:
- Sensitive constants imported from other modules being logged/used in sinks
- User-input functions imported and used without sanitization
- Config values with security implications imported and used unsafely

This check requires CrossFileCheckContext to be available (injected by SecurityFrame).
Without cross-file context, it is a no-op (zero findings).
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

# Logging sinks — same set as sensitive_logging_check
_LOG_SINK = re.compile(
    r"\b(logging\.(debug|info|warning|error|critical|exception)"
    r"|logger\.(debug|info|warning|error|critical|exception|warn)"
    r"|print"
    r"|console\.(log|error|warn|debug|info)"
    r"|log\.(Print|Printf|Println))\s*\(",
    re.IGNORECASE,
)

# File operation sinks — same set as path_traversal_check
_FILE_SINK = re.compile(
    r"\bopen\s*\("
    r"|\bos\.(open|stat|listdir|makedirs|remove|unlink)\s*\("
    r"|\bpathlib\.Path\s*\("
    r"|\bfs\.(readFile|writeFile|readFileSync|writeFileSync)\s*\(",
)

# SQL sinks
_SQL_SINK = re.compile(
    r"\bcursor\.(execute|executemany)\s*\("
    r"|\bconn\.(execute|cursor)\s*\("
    r"|\bsession\.(execute|query)\s*\(",
    re.IGNORECASE,
)

# HTTP header / response sinks
_HTTP_SINK = re.compile(
    r"headers\s*\["
    r"|\.set_header\s*\("
    r"|response\.headers\s*\["
    r"|add_header\s*\(",
    re.IGNORECASE,
)

# Patterns that indicate a security-relevant config flag being disabled
_SECURITY_FLAG_DISABLED = re.compile(
    r"\b(enable_dns_rebinding_protection|allow_cors|debug|ssl_verify"
    r"|verify_ssl|check_hostname|csrf_protect|auth_required"
    r"|require_auth|enforce_https)\s*=\s*(False|0|\"false\"|'false')",
    re.IGNORECASE,
)

# Known sanitizers (suppress if present on same/adjacent line)
_SANITIZERS = re.compile(
    r"\b(mask|redact|sanitize|scrub|hash|hmac|os\.path\.basename"
    r"|filepath\.Clean|re\.sub)\s*\(",
    re.IGNORECASE,
)


def _lines_around(lines: list[str], idx: int, window: int = 2) -> str:
    start = max(0, idx - window)
    end = min(len(lines), idx + window + 1)
    return "\n".join(lines[start:end])


class CrossFileTaintCheck(ValidationCheck):
    """
    Detects security issues that require cross-file context.

    Patterns detected (only when CrossFileCheckContext is available):
    1. Imported sensitive constant used in logging sink
       (e.g., config.py defines API_KEY = "sk-..." and app.py logs it)
    2. Imported sensitive constant used in SQL query (injection risk)
    3. Imported sensitive constant written to HTTP response header
    4. Security-disabling config flags (enable_dns_rebinding_protection=False)
       detected regardless of import context

    Severity: HIGH (cross-file issues are harder to spot in code review)
    """

    id = "cross-file-taint"
    name = "Cross-File Taint Detection"
    description = "Detects sensitive imported values used in security sinks across files"
    severity = CheckSeverity.HIGH
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    async def execute_async(self, code_file: CodeFile, context=None) -> CheckResult:
        """Execute cross-file taint detection."""
        findings: list[CheckFinding] = []
        lines = code_file.content.split("\n")

        # --- Pass 1: Security-disabling flags (no context required) ---
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*", "/*")):
                continue

            m = _SECURITY_FLAG_DISABLED.search(line)
            if not m:
                continue

            suppression_matcher = self._get_suppression_matcher(code_file.path)
            if suppression_matcher and suppression_matcher.is_suppressed(
                line=idx + 1,
                rule=self.id,
                file_path=str(code_file.path),
                code=code_file.content,
            ):
                continue

            flag_name = m.group(1)
            flag_value = m.group(2)
            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=CheckSeverity.HIGH,
                    message=(
                        f"Security flag disabled: '{flag_name}' set to {flag_value} — "
                        "disabling this protection may expose the service to attacks"
                    ),
                    location=f"{code_file.path}:{idx + 1}",
                    code_snippet=stripped,
                    suggestion=(
                        "Only disable security flags in clearly documented, intentional contexts:\n"
                        "✅ GOOD: enable_dns_rebinding_protection=True  # keep enabled\n"
                        "❌ BAD:  enable_dns_rebinding_protection=False  # exposes to DNS rebinding"
                    ),
                    documentation_url="https://owasp.org/www-community/attacks/DNS_Rebinding",
                )
            )

        # --- Pass 2: Imported sensitive values in sinks (requires context) ---
        if context is None:
            logger.debug("cross_file_taint_no_context", file=code_file.path)
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=len(findings) == 0,
                findings=findings,
            )

        # Extract sensitive imported names from CrossFileCheckContext
        try:
            from warden.analysis.services.cross_file_analyzer import CrossFileCheckContext

            if isinstance(context, CrossFileCheckContext):
                sensitive_names = context.imported_sensitive_names
                resolved = context.resolved_imports
            else:
                # Fallback: check if context has cross_file_context attr
                cfc = getattr(context, "cross_file_context", None)
                if cfc is None:
                    return CheckResult(
                        check_id=self.id,
                        check_name=self.name,
                        passed=len(findings) == 0,
                        findings=findings,
                    )
                cfc_ctx = CrossFileCheckContext.from_cross_file_ctx(cfc, code_file.path)
                sensitive_names = cfc_ctx.imported_sensitive_names
                resolved = cfc_ctx.resolved_imports
        except Exception as e:
            logger.debug("cross_file_ctx_extract_failed", error=str(e))
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=len(findings) == 0,
                findings=findings,
            )

        if not sensitive_names:
            logger.debug(
                "cross_file_taint_no_sensitive_imports",
                file=code_file.path,
                resolved_count=len(resolved),
            )
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=len(findings) == 0,
                findings=findings,
            )

        logger.debug(
            "cross_file_taint_sensitive_imports_found",
            file=code_file.path,
            names=list(sensitive_names),
        )

        # Build regex to match any of the sensitive imported names
        escaped = [re.escape(n) for n in sensitive_names]
        sensitive_re = re.compile(r"\b(" + "|".join(escaped) + r")\b")

        for idx, line in enumerate(lines):
            line_num = idx + 1
            stripped = line.strip()

            if stripped.startswith(("#", "//", "*", "/*")):
                continue

            if not sensitive_re.search(line):
                continue

            # Determine which sensitive name is present
            match = sensitive_re.search(line)
            found_name = match.group(1) if match else "sensitive_value"
            source_file = resolved.get(found_name, None)
            source_info = f" (imported from {source_file.file_path})" if source_file else ""

            context_window = _lines_around(lines, idx, window=2)
            if _SANITIZERS.search(context_window):
                continue

            # Identify the sink
            sink_label = None
            if _LOG_SINK.search(line):
                sink_label = "logging sink"
                cwe = "CWE-532"
                doc_url = "https://cwe.mitre.org/data/definitions/532.html"
                suggestion = (
                    "Mask sensitive imported values before logging:\n"
                    "✅ GOOD: logger.info('auth ok', user=user_id)  # no secret\n"
                    "❌ BAD:  logger.info(f'key={API_KEY}')          # leaks secret from import"
                )
            elif _SQL_SINK.search(line):
                sink_label = "SQL sink"
                cwe = "CWE-89"
                doc_url = "https://owasp.org/www-community/attacks/SQL_Injection"
                suggestion = (
                    "Use parameterized queries; do not concatenate imported values into SQL:\n"
                    "✅ GOOD: cursor.execute('SELECT ... WHERE x = ?', (val,))\n"
                    "❌ BAD:  cursor.execute(f'SELECT ... WHERE x = {IMPORTED_VAL}')"
                )
            elif _HTTP_SINK.search(line):
                sink_label = "HTTP response header"
                cwe = "CWE-201"
                doc_url = "https://cwe.mitre.org/data/definitions/201.html"
                suggestion = (
                    "Never expose sensitive imported values in HTTP headers:\n"
                    "❌ BAD:  headers['Authorization'] = f'Bearer {PRIVATE_KEY}'"
                )
            else:
                continue

            suppression_matcher = self._get_suppression_matcher(code_file.path)
            if suppression_matcher and suppression_matcher.is_suppressed(
                line=line_num,
                rule=self.id,
                file_path=str(code_file.path),
                code=code_file.content,
            ):
                continue

            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=self.severity,
                    message=(
                        f"Cross-file taint: imported sensitive value '{found_name}'{source_info} "
                        f"reaches {sink_label} ({cwe})"
                    ),
                    location=f"{code_file.path}:{line_num}",
                    code_snippet=stripped,
                    suggestion=suggestion,
                    documentation_url=doc_url,
                )
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
        )
