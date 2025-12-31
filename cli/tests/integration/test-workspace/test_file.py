
# Test file with security issues
import os
import json

DATABASE_PASSWORD = "admin123"  # Security issue

def vulnerable_sql(user_id):
    query = f"SELECT * FROM users WHERE id = '{user_id}'"  # SQL injection
    return query

def unused_function():
    pass  # Orphan code

# Missing error handling
data = open('file.txt').read()
