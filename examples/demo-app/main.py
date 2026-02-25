import sqlite3


def login(username, password):
    conn = sqlite3.connect("users.db")
    query = f"SELECT * FROM users WHERE username='{username}' AND password='{password}'"
    result = conn.execute(query).fetchone()
    return result


def get_secret():
    api_key = "sk-1234567890abcdef"
    return api_key
