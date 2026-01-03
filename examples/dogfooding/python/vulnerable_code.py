"""
Example code with various security issues and code quality problems.
This file is for testing Warden's detection capabilities.
"""

import os
import sqlite3
from flask import Flask, request, render_template_string

# Hardcoded secrets (should be in env vars)
API_KEY = "sk-1234567890abcdef"
DATABASE_PASSWORD = "admin123"

app = Flask(__name__)

# Single letter variable names (bad naming)
a = 10
b = 20
x = a + b

# Unused imports
import json
import hashlib
import random

# SQL Injection vulnerability
def get_user(user_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    # VULNERABLE: Direct string concatenation
    query = f"SELECT * FROM users WHERE id = '{user_id}'"
    cursor.execute(query)
    return cursor.fetchone()

# XSS vulnerability
@app.route('/hello')
def hello():
    name = request.args.get('name', 'World')
    # VULNERABLE: Directly rendering user input
    template = f"<h1>Hello {name}!</h1>"
    return render_template_string(template)

# Path traversal vulnerability
@app.route('/read_file')
def read_file():
    filename = request.args.get('file')
    # VULNERABLE: No path validation
    with open(f"/var/www/{filename}") as f:
        return f.read()

# Complex function (too long, needs refactoring)
def process_data(data_list):
    result = []
    for item in data_list:
        if item > 0:
            if item < 10:
                result.append(item * 2)
            elif item < 20:
                result.append(item * 3)
            elif item < 30:
                result.append(item * 4)
            elif item < 40:
                result.append(item * 5)
            elif item < 50:
                result.append(item * 6)
            elif item < 60:
                result.append(item * 7)
            elif item < 70:
                result.append(item * 8)
            elif item < 80:
                result.append(item * 9)
            elif item < 90:
                result.append(item * 10)
            else:
                result.append(item * 11)
        else:
            if item > -10:
                result.append(item * -2)
            elif item > -20:
                result.append(item * -3)
            elif item > -30:
                result.append(item * -4)
            elif item > -40:
                result.append(item * -5)
            elif item > -50:
                result.append(item * -6)
            elif item > -60:
                result.append(item * -7)
            elif item > -70:
                result.append(item * -8)
            elif item > -80:
                result.append(item * -9)
            elif item > -90:
                result.append(item * -10)
            else:
                result.append(item * -11)

    # More complex logic
    total = 0
    for r in result:
        total += r

    average = total / len(result) if result else 0

    # Duplicate code
    print(f"Processing completed: {len(result)} items")
    print(f"Total: {total}")
    print(f"Average: {average}")

    # More duplicate code
    print(f"Processing completed: {len(result)} items")
    print(f"Total: {total}")
    print(f"Average: {average}")

    return result

# Dead code - never called
def unused_function():
    pass

def another_unused():
    return "This is never used"

# Weak crypto
import hashlib
def hash_password(password):
    # VULNERABLE: MD5 is weak
    return hashlib.md5(password.encode()).hexdigest()

if __name__ == "__main__":
    app.run(debug=True)  # Debug mode in production is bad
# Triggering cache miss
