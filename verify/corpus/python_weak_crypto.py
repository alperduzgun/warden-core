"""Vulnerable: Weak cryptographic algorithms."""

import hashlib
import hmac


def hash_password(password: str) -> str:
    # MD5 is cryptographically broken
    return hashlib.md5(password.encode()).hexdigest()


def verify_signature(data: bytes, signature: str, key: bytes) -> bool:
    # SHA1 is deprecated for security use
    computed = hmac.new(key, data, hashlib.sha1).hexdigest()
    return computed == signature


def quick_hash(content: str) -> str:
    # MD5 again
    return hashlib.md5(content.encode()).hexdigest()
