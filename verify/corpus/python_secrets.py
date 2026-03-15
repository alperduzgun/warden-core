"""Vulnerable: Hardcoded secrets and credentials."""

import os

# Hardcoded API keys
OPENAI_API_KEY = "sk-proj-1234567890abcdef1234567890abcdef1234567890abcdef"
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

# Hardcoded database password
DB_PASSWORD = "super_secret_password_123"
db_connection_string = "postgresql://admin:super_secret_password_123@localhost:5432/mydb"


class Config:
    password = "admin123"
    jwt_secret = "my-jwt-secret-key-that-should-not-be-here"
    stripe_key = "sk_live_FAKE_TEST_KEY_NOT_REAL_000"  # noqa: S105


def connect_db():
    return os.getenv("DATABASE_URL", db_connection_string)
