"""
Python Dogfooding Example - Security Vulnerabilities.

Contains intentional security issues for testing warden security frame.
"""

import os
import subprocess
from typing import Optional


# 🔴 SQL Injection vulnerability
def get_user_by_id(user_id: str) -> dict:
    query = f"SELECT * FROM users WHERE id = '{user_id}'"  # VULNERABLE
    # execute_query(query)
    return {"id": user_id}


# 🔴 Command Injection vulnerability
def run_command(filename: str) -> str:
    result = subprocess.run(f"cat {filename}", shell=True, capture_output=True)  # VULNERABLE
    return result.stdout.decode()


# 🔴 Hardcoded secret
API_KEY = "sk_live_1234567890abcdefghijklmnop"  # VULNERABLE
DATABASE_PASSWORD = "super_secret_password_123"  # VULNERABLE


# 🔴 Path traversal vulnerability
def read_file(user_path: str) -> str:
    base_dir = "/var/data"
    full_path = os.path.join(base_dir, user_path)  # No validation - VULNERABLE
    with open(full_path) as f:
        return f.read()


# 🟡 Unused function (orphan)
def unused_helper_function():
    """This function is never called."""
    return "orphan"


# 🟡 Unused import would be detected too
# from typing import List  # Uncomment to test unused import


# ✅ Used function
def main():
    user = get_user_by_id("1")
    print(user)


if __name__ == "__main__":
    main()
