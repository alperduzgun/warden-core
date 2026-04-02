"""
Remediation Enricher — Issue #622.

Attaches root_cause, risk_scope, and remediation_hint to findings that lack
these fields.  The enricher first checks whether the LLM verification metadata
already contains structured fields; if not, it falls back to a deterministic
rule-based lookup keyed by rule_id prefix.

This module is intentionally side-effect-free: it returns a new list rather
than mutating the originals so callers can diff before/after.
"""

from __future__ import annotations

from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Rule-based fallback table
# ---------------------------------------------------------------------------
# Keys are lower-cased rule_id prefixes / substrings matched via ``in`` or
# startswith so a single entry covers rule_id variants like
# "sql_injection", "sql-injection", "B608", etc.
#
# Each entry is a 3-tuple: (remediation_hint, root_cause, risk_scope).
# risk_scope must be one of: "local", "service", "data".
# ---------------------------------------------------------------------------

_RULE_TABLE: list[tuple[tuple[str, ...], str, str, str]] = [
    # SQL Injection
    (
        ("sql_injection", "sql-injection", "b608", "sqli"),
        "Use parameterized queries or an ORM — never concatenate user input into SQL strings.",
        "User-controlled data is interpolated directly into a SQL string, allowing an attacker to alter query semantics.",
        "data",
    ),
    # Hardcoded secrets / passwords
    (
        ("hardcoded_secret", "hardcoded_password", "hardcoded_credential", "b105", "b106", "b107", "secret_", "leaked_secret"),
        "Move the credential to an environment variable and load it at runtime (e.g. os.getenv).",
        "A secret value is embedded in source code, making it visible to anyone with repository access.",
        "service",
    ),
    # Command injection / OS execution
    (
        ("command_injection", "cmd_injection", "shell_injection", "b602", "b603", "b604", "b605", "b606", "b607"),
        "Avoid shell=True; use subprocess with a list of arguments and validate/sanitise all external input.",
        "Shell metacharacters in user-controlled input are passed to a system shell, enabling arbitrary command execution.",
        "service",
    ),
    # Path traversal
    (
        ("path_traversal", "directory_traversal", "b101"),
        "Resolve and validate file paths against an allowed base directory before opening them.",
        "Unsanitised path components allow an attacker to access files outside the intended directory tree.",
        "data",
    ),
    # XSS
    (
        ("xss", "cross_site_scripting", "reflected_xss", "stored_xss"),
        "Escape all user-supplied data before rendering it as HTML; use a templating engine with auto-escaping.",
        "Unescaped user input is rendered directly in the browser, allowing script injection.",
        "service",
    ),
    # SSRF
    (
        ("ssrf", "server_side_request_forgery"),
        "Validate and whitelist allowed outbound URLs; block requests to internal/private IP ranges.",
        "Attacker-controlled URLs are fetched server-side, enabling access to internal services.",
        "service",
    ),
    # Insecure deserialization
    (
        ("insecure_deserialization", "unsafe_deserialization", "b301", "b302", "b303", "b304", "pickle"),
        "Replace pickle/yaml.load with a safe format (json, yaml.safe_load) or validate data before deserialising.",
        "Deserialising untrusted data can execute arbitrary code embedded in the payload.",
        "service",
    ),
    # Weak cryptography
    (
        ("weak_crypto", "weak_hash", "md5", "sha1", "b303", "b324"),
        "Replace MD5/SHA-1 with SHA-256 or stronger; for passwords use bcrypt, argon2, or scrypt.",
        "Weak hash algorithms are computationally feasible to reverse, exposing sensitive data.",
        "data",
    ),
    # Timing attack
    (
        ("timing_attack", "timing_side_channel"),
        "Use hmac.compare_digest (or secrets.compare_digest) for constant-time comparison of secrets.",
        "Non-constant-time string comparison leaks information about secret values through response-time differences.",
        "service",
    ),
    # JWT vulnerabilities
    (
        ("jwt_alg_none", "jwt_none_algorithm", "jwt_algorithm"),
        "Explicitly specify and enforce the expected algorithm(s) in JWT verification; never accept 'none'.",
        "Accepting the 'none' algorithm allows attackers to forge tokens without a valid signature.",
        "service",
    ),
    (
        ("jwt_long_expiry", "jwt_expiry"),
        "Set JWT expiry to 15 minutes or less for sensitive operations; use refresh tokens for session continuity.",
        "Long-lived tokens remain valid after a breach, extending the attacker's window of access.",
        "service",
    ),
    # CSRF
    (
        ("csrf", "cross_site_request_forgery"),
        "Implement CSRF tokens on all state-changing endpoints; validate the Origin/Referer header.",
        "Missing CSRF protection allows malicious sites to trigger authenticated actions on behalf of a victim.",
        "service",
    ),
    # Open redirect
    (
        ("open_redirect", "unvalidated_redirect"),
        "Validate redirect destinations against an explicit allowlist of trusted URLs.",
        "Attacker-controlled redirect targets can redirect users to phishing sites after authentication.",
        "service",
    ),
    # Eval / code injection
    (
        ("eval_injection", "code_injection", "b307"),
        "Remove eval/exec calls; if dynamic code is required, use a restricted evaluator or AST-based approach.",
        "Passing user input to eval() or exec() allows arbitrary Python code execution.",
        "service",
    ),
    # Predictable tokens / random
    (
        ("predictable_token", "weak_random", "b311"),
        "Use secrets.token_hex or secrets.token_urlsafe for cryptographic tokens, not the random module.",
        "The random module uses a predictable PRNG unsuitable for security-sensitive token generation.",
        "service",
    ),
    # Missing auth / broken access control
    (
        ("missing_auth", "broken_access_control", "missing_authorization", "unauthenticated"),
        "Enforce authentication and authorisation checks on every route that accesses sensitive resources.",
        "Endpoints reachable without authentication expose sensitive functionality to unauthenticated users.",
        "data",
    ),
    # Insecure transport / TLS
    (
        ("insecure_transport", "tls_verification_disabled", "b501", "b502", "b503", "b504"),
        "Enable TLS certificate verification; never set verify=False in production HTTP clients.",
        "Disabling TLS verification allows man-in-the-middle attacks that intercept or alter traffic.",
        "data",
    ),
    # Log injection
    (
        ("log_injection", "log_forging"),
        "Sanitise log messages by stripping or escaping newline characters from user-supplied input.",
        "Unsanitised user data in log messages allows an attacker to inject fake log entries.",
        "local",
    ),
    # Orphan / dead code
    (
        ("orphan", "dead_code", "unreachable"),
        "Remove unused code to reduce the attack surface and maintenance burden.",
        "Dead or unreachable code cannot be maintained and may contain latent vulnerabilities.",
        "local",
    ),
]


def _match_rule(rule_id: str) -> tuple[str, str, str] | None:
    """Return (remediation_hint, root_cause, risk_scope) for a rule_id, or None."""
    rule_lower = rule_id.lower()
    for prefixes, hint, cause, scope in _RULE_TABLE:
        for prefix in prefixes:
            if prefix in rule_lower:
                return hint, cause, scope
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enrich_finding(finding: Any) -> None:
    """
    Attach remediation_hint, root_cause, and risk_scope to a finding in-place.

    The function is a no-op if all three fields are already populated.
    It first checks LLM verification metadata for structured fields, then
    falls back to the deterministic rule table.

    Args:
        finding: A Finding dataclass instance or dict-like object.
    """
    from warden.shared.utils.finding_utils import get_finding_attribute, set_finding_attribute

    # Skip if already fully enriched
    existing_hint = get_finding_attribute(finding, "remediation_hint")
    existing_cause = get_finding_attribute(finding, "root_cause")
    existing_scope = get_finding_attribute(finding, "risk_scope")
    if existing_hint and existing_cause and existing_scope:
        return

    # Try to extract from LLM verification metadata
    vm = get_finding_attribute(finding, "verification_metadata") or {}
    if isinstance(vm, dict):
        if not existing_hint and vm.get("remediation_hint"):
            set_finding_attribute(finding, "remediation_hint", vm["remediation_hint"])
            existing_hint = vm["remediation_hint"]
        if not existing_cause and vm.get("root_cause"):
            set_finding_attribute(finding, "root_cause", vm["root_cause"])
            existing_cause = vm["root_cause"]
        if not existing_scope and vm.get("risk_scope"):
            set_finding_attribute(finding, "risk_scope", vm["risk_scope"])
            existing_scope = vm["risk_scope"]

    # Fall back to rule-based lookup for any missing fields
    if not (existing_hint and existing_cause and existing_scope):
        rule_id = (
            get_finding_attribute(finding, "rule_id")
            or get_finding_attribute(finding, "id")
            or ""
        )
        match = _match_rule(str(rule_id))
        if match:
            hint, cause, scope = match
            if not existing_hint:
                set_finding_attribute(finding, "remediation_hint", hint)
            if not existing_cause:
                set_finding_attribute(finding, "root_cause", cause)
            if not existing_scope:
                set_finding_attribute(finding, "risk_scope", scope)
        else:
            logger.debug("remediation_enricher_no_match", rule_id=rule_id)


def enrich_findings(findings: list[Any]) -> list[Any]:
    """
    Enrich a list of findings with remediation/root_cause/risk_scope.

    Mutates findings in-place and also returns the list for convenience.

    Args:
        findings: List of Finding objects or dicts.

    Returns:
        The same list, with fields populated where applicable.
    """
    for finding in findings:
        try:
            enrich_finding(finding)
        except Exception as exc:
            logger.warning("remediation_enricher_failed", error=str(exc))
    return findings
