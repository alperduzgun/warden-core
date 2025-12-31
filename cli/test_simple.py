#!/usr/bin/env python3
"""Simple test file for Warden CLI"""

def main():
    # Potential SQL injection
    user_input = "admin' OR '1'='1"
    query = f"SELECT * FROM users WHERE name = '{user_input}'"
    print(query)

    # Hardcoded password
    password = "secret123"

    # Missing error handling
    result = open("/tmp/test.txt").read()

if __name__ == "__main__":
    main()