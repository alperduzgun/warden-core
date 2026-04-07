"""
Safe cryptography patterns that weak-crypto scanners wrongly flag.
MD5/SHA1 are acceptable for checksums, cache keys, ETags — NOT for passwords.

corpus_labels:
  weak-crypto: 0
  sql-injection: 0
"""

import hashlib
import hmac


# ── MD5/SHA1 for file integrity / checksums — NOT password hashing ───────────

def compute_file_checksum(filepath: str) -> str:
    """MD5 for file integrity check — acceptable, NOT password hashing."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_content_hash(content: bytes) -> str:
    """SHA1 for content addressing — acceptable for non-security use."""
    return hashlib.sha1(content).hexdigest()


# ── MD5 for cache keys / ETags ────────────────────────────────────────────────

def make_cache_key(user_id: str, query: str) -> str:
    """MD5 cache key — NOT security-sensitive, just an identifier."""
    raw = f"{user_id}:{query}".encode()
    return hashlib.md5(raw).hexdigest()


def compute_etag(content: bytes) -> str:
    """ETag via MD5 — standard HTTP caching pattern, NOT password hashing."""
    return f'"{hashlib.md5(content).hexdigest()}"'


def file_fingerprint(path: str) -> str:
    """File fingerprint via SHA1 — NOT credential storage."""
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha1(data).hexdigest()


# ── Git-style content hashing ─────────────────────────────────────────────────

def git_blob_hash(content: bytes) -> str:
    """SHA1 blob hash (git-compatible) — NOT password hashing."""
    header = f"blob {len(content)}\0".encode()
    sha1sum = hashlib.sha1(header + content)
    return sha1sum.hexdigest()


# ── HMAC-SHA1 for API signatures (still used in legacy AWS v2, OAuth 1.0) ────

def sign_request(key: bytes, message: str) -> str:
    """HMAC-SHA1 for legacy API compatibility — acceptable in this context."""
    return hmac.new(key, message.encode(), hashlib.sha1).hexdigest()


# ── Non-password context message digest ──────────────────────────────────────

def message_digest(data: bytes) -> str:
    """MD5 message digest for deduplication — NOT security-sensitive."""
    return hashlib.md5(data).hexdigest()


def md5sum(filepath: str) -> str:
    """Standard md5sum CLI equivalent — file integrity only."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


# ── Pattern definitions in security check files — NOT weak crypto usage ──────

DANGEROUS_PATTERNS = [
    (r"hashlib\.md5\s*\(", "hashlib.md5() weak hash"),
    (r"DES\.MODE_", "DES cipher is broken"),
    (r"AES\.MODE_ECB", "ECB mode is insecure"),
]

WEAK_CIPHER_NAMES = ["DES", "RC4", "MD5", "SHA1"]  # cipher blocklist for validation
