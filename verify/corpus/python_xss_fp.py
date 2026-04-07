"""
Safe patterns that naive XSS scanners wrongly flag.

corpus_labels:
  xss: 0
  sql-injection: 0
  hardcoded-password: 0
"""

import redis

# ── Redis eval — Lua scripting, NOT browser XSS ──────────────────────────────

redis_client = redis.Redis()


def rate_limit(key: str) -> int:
    """Redis Lua script via eval — server-side only, NOT XSS."""
    script = """
    local count = redis.call('INCR', KEYS[1])
    redis.call('EXPIRE', KEYS[1], 60)
    return count
    """
    return redis_client.eval(script, 1, key)


def acquire_lock(name: str, timeout: int = 10) -> bool:
    """Redis distributed lock via eval — NOT XSS."""
    script = """
    if redis.call('EXISTS', KEYS[1]) == 0 then
        redis.call('SET', KEYS[1], ARGV[1])
        redis.call('EXPIRE', KEYS[1], ARGV[2])
        return 1
    end
    return 0
    """
    return bool(redis_client.eval(script, 1, name, "locked", timeout))


class RedisPipeline:
    def __init__(self):
        self._pipe = redis_client.pipeline()

    def flush_batch(self, keys: list[str]) -> list:
        """Redis pipeline execute — NOT XSS."""
        for key in keys:
            self._pipe.delete(key)
        return self._pipe.execute()


# ── mark_safe on string literal — intentional, NOT XSS ──────────────────────

from django.utils.safestring import mark_safe  # noqa: E402


def render_checkmark() -> str:
    """mark_safe on a known-safe literal — NOT XSS."""
    return mark_safe('<span class="icon icon-check" aria-label="ok">✓</span>')


def render_loading_spinner() -> str:
    """mark_safe on a controlled template literal — NOT XSS."""
    return mark_safe(
        '<div class="spinner" role="status">'
        '<span class="sr-only">Loading...</span>'
        "</div>"
    )


# ── DANGEROUS_PATTERNS definition in security check file — NOT XSS ───────────

DANGEROUS_PATTERNS = [
    (r"\.innerHTML\s*=", "innerHTML assignment (potential XSS)"),
    (r"document\.write\(", "document.write() usage"),
    (r"eval\(", "eval() usage"),
]

SECURITY_PATTERNS = [
    r"<script[^>]*>",
    r"javascript:",
    r"on\w+\s*=",
]


# ── Comment lines mentioning innerHTML — NOT XSS ─────────────────────────────

# BAD: element.innerHTML = userInput  ← never do this without sanitization
# GOOD: element.textContent = userInput  ← safe alternative
# GOOD: element.innerHTML = DOMPurify.sanitize(userInput)  ← sanitized

# The following pattern is intentionally flagged as XSS in security tests:
# document.write('<p>' + userInput + '</p>')  — see python_xss.py


# ── DOMPurify sanitized innerHTML — lower confidence, not hard-excluded ───────
# (These have sanitizer evidence in context — will get low confidence score)

def render_with_sanitizer(user_html: str) -> str:
    """JS equivalent: innerHTML after DOMPurify.sanitize() — sanitized."""
    # In the JS layer:
    # const clean = DOMPurify.sanitize(userHtml);
    # element.innerHTML = clean;
    return user_html  # sanitization happens client-side
