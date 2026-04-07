"""
Safe credential patterns that hardcoded-secret scanners wrongly flag.

corpus_labels:
  hardcoded-password: 0
  sql-injection: 0
"""

import os

# ── Environment variables — safe, NOT hardcoded ──────────────────────────────

DB_PASSWORD = os.getenv("DB_PASSWORD")
API_KEY = os.environ["API_KEY"]
JWT_SECRET = os.getenv("JWT_SECRET", "")
STRIPE_KEY = os.environ.get("STRIPE_SECRET_KEY")


class Config:
    password = os.getenv("APP_PASSWORD")
    secret_key = os.getenv("SECRET_KEY")
    auth_token = os.getenv("AUTH_TOKEN")


# ── Placeholder values — excluded by _is_likely_password heuristic ───────────

DATABASE_URL = "postgresql://user:your_password_here@localhost/db"
API_ENDPOINT = "https://api.example.com/v1"
DEFAULT_PASSWORD = "change_me_in_production"
EXAMPLE_TOKEN = "enter_password"


# ── Short / clearly non-secret values ────────────────────────────────────────

status = "ok"
mode = "dev"
env = "test"


# ── Template variables — excluded by {{ }} check ─────────────────────────────

helm_password = "{{ .Values.db.password }}"
ansible_secret = "${SECRET_KEY}"
terraform_token = "{{ vault('secret/myapp/token') }}"


# ── getpass / input — interactive, NOT hardcoded ─────────────────────────────

import getpass  # noqa: E402


def prompt_password() -> str:
    return getpass.getpass("Enter password: ")


def prompt_token() -> str:
    return input("Enter API token: ")


# ── Common passwords in a blocklist — NOT a hardcoded credential ─────────────

COMMON_PASSWORDS = frozenset({
    "password",
    "admin",
    "root",
    "123456",
    "qwerty",
    "letmein",
    "monkey",
    "abc123",
})


def is_weak_password(pwd: str) -> bool:
    """Check against known weak passwords."""
    return pwd.lower() in COMMON_PASSWORDS


# ── Test fixture — acceptable in test context ─────────────────────────────────

# In test files, hardcoded values are expected and acceptable.
# Warden should lower severity for test files, not hard-block.

TEST_DB_PASSWORD = "test_password_123"
TEST_API_KEY = "test_api_key_for_unit_tests_only"
FIXTURE_SECRET = "fixture_secret_do_not_use_in_prod"
