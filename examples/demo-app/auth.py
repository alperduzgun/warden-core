"""
Authentication module with logic-level vulnerabilities.
Intentionally vulnerable for testing warden's logic-level detection.
"""

import hashlib
import hmac
import json
import base64
import random
import os
import re
import time


# ── VULN 1: Timing attack (== instead of hmac.compare_digest) ──────────────
def verify_signature(token: str, secret: str) -> bool:
    parts = token.split(".")
    if len(parts) != 3:
        return False
    payload = parts[1]
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return expected == parts[2]  # VULNERABLE: timing attack


# ── VULN 2: JWT "none" algorithm accepted ──────────────────────────────────
def decode_jwt(token: str, secret: str) -> dict:
    header_b64, payload_b64, signature = token.split(".")
    header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))

    alg = header.get("alg", "HS256")
    if alg == "none":  # VULNERABLE: accepts none algorithm
        return payload

    expected_sig = hmac.new(secret.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).hexdigest()
    if expected_sig == signature:
        return payload
    raise ValueError("Invalid signature")


# ── VULN 3: JWT expiry unreasonably long (30 days) ─────────────────────────
def create_token(user_id: str, secret: str) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).decode()
    payload_data = {
        "sub": user_id,
        "exp": int(time.time()) + 60 * 60 * 24 * 30,  # VULNERABLE: 30 day expiry
        "iat": int(time.time()),
    }
    payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).decode()
    sig = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"{header}.{payload}.{sig}"


# ── VULN 4: Role from JWT payload without server-side validation ───────────
def get_user_role(token: str, secret: str) -> str:
    payload = decode_jwt(token, secret)
    return payload.get("role", "user")  # VULNERABLE: trusts client-supplied role


def is_admin(token: str, secret: str) -> bool:
    role = get_user_role(token, secret)
    return role == "admin"  # VULNERABLE: no server-side role lookup


# ── VULN 5: Static/hardcoded salt + weak hashing ──────────────────────────
STATIC_SALT = "warden2024"  # VULNERABLE: hardcoded salt


def hash_password(password: str) -> str:
    salted = STATIC_SALT + password
    return hashlib.md5(salted.encode()).hexdigest()  # VULNERABLE: MD5 + static salt


def verify_password(password: str, stored_hash: str) -> bool:
    return hash_password(password) == stored_hash


# ── VULN 6: format_map with user-controlled input (attribute leak) ─────────
def render_greeting(template: str, user_data: dict) -> str:
    """Render a user greeting from a template string."""
    return template.format_map(user_data)  # VULNERABLE: attribute leak via __class__


# ── VULN 7: Predictable randomness for security-sensitive paths ────────────
def generate_upload_path(filename: str) -> str:
    random_prefix = random.randint(100000, 999999)  # VULNERABLE: predictable
    return f"/uploads/{random_prefix}_{filename}"


def generate_reset_token() -> str:
    return str(random.randint(100000, 999999))  # VULNERABLE: predictable token


# ── VULN 8: Bypassable HTML sanitizer (blocklist replace) ─────────────────
DANGEROUS_TAGS = ["<script>", "</script>", "<iframe>", "</iframe>", "onclick", "onerror"]


def sanitize_html(html_input: str) -> str:
    result = html_input
    for tag in DANGEROUS_TAGS:
        result = result.replace(tag, "")  # VULNERABLE: bypassable with <scr<script>ipt>
    return result


# ── VULN 9: Trivially bypassable validation regex ─────────────────────────
def validate_email(email: str) -> bool:
    pattern = r".*@.*\..*"  # VULNERABLE: matches almost anything
    return bool(re.match(pattern, email))


def validate_url(url: str) -> bool:
    pattern = r"https?://.*"  # VULNERABLE: no host validation
    return bool(re.match(pattern, url))
