"""
SQL Injection Demo - Educational Example

This file demonstrates SQL injection vulnerability for educational purposes.
DO NOT USE IN PRODUCTION!

# warden-context: example
"""

import sqlite3


def vulnerable_login(username: str, password: str) -> bool:
    """
    Example of vulnerable SQL query - INTENTIONALLY INSECURE!

    This is a demonstration of what NOT to do.
    """
    conn = sqlite3.connect('demo.db')

    # BAD: Direct string interpolation - SQL Injection vulnerability!
    query = f"SELECT * FROM users WHERE username='{username}' AND password='{password}'"

    cursor = conn.execute(query)
    result = cursor.fetchone()

    return result is not None


def secure_login(username: str, password: str) -> bool:
    """
    Example of secure parameterized query.

    This is the correct way to handle user input in SQL queries.
    """
    conn = sqlite3.connect('demo.db')

    # GOOD: Parameterized query prevents SQL injection
    query = "SELECT * FROM users WHERE username=? AND password=?"

    cursor = conn.execute(query, (username, password))
    result = cursor.fetchone()

    return result is not None


if __name__ == "__main__":
    # Demo usage
    print("This is an educational demo about SQL injection.")
    print("The vulnerable_login function contains intentional vulnerabilities.")
    print("The secure_login function shows the correct approach.")

    # Example attack vector (commented out for safety)
    # malicious_username = "admin' --"
    # vulnerable_login(malicious_username, "anything")