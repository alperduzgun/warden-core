"""Utility functions for the sample project."""
import hashlib
import os


def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with salt."""
    salt = os.urandom(32)
    return hashlib.sha256(salt + password.encode()).hexdigest()


def validate_email(email: str) -> bool:
    """Basic email validation."""
    return "@" in email and "." in email.split("@")[-1]


def safe_divide(a: float, b: float) -> float:
    """Safely divide two numbers."""
    if b == 0:
        raise ValueError("Division by zero")
    return a / b
