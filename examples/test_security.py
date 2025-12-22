import os
import subprocess

# SQL Injection vulnerability
def get_user(user_id):
    query = f"SELECT * FROM users WHERE id = '{user_id}'"  # VULNERABLE!
    return db.execute(query)

# Command Injection vulnerability
def run_command(filename):
    subprocess.run(f"cat {filename}", shell=True)  # VULNERABLE!

# Hardcoded secret
API_KEY = "sk_live_12345abcdef"  # VULNERABLE!

print("Test file with security issues")
