"""Deliberately vulnerable Python file for E2E testing."""
import os
import subprocess


# VULN-1: Hardcoded secret
API_KEY = "sk-1234567890abcdef1234567890abcdef"
DB_PASSWORD = "admin123"

# VULN-2: SQL injection
def get_user(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return query

# VULN-3: Command injection
def run_command(user_input):
    os.system(f"echo {user_input}")
    subprocess.call(user_input, shell=True)

# VULN-4: Eval usage
def evaluate(expression):
    return eval(expression)
