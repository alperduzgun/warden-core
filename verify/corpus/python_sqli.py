"""Vulnerable: SQL injection via f-string and string concatenation."""

import sqlite3

from flask import Flask, request

app = Flask(__name__)


def get_db():
    return sqlite3.connect(":memory:")


@app.route("/users")
def search_users():
    name = request.args.get("name")
    db = get_db()
    cursor = db.cursor()
    cursor.execute(f"SELECT * FROM users WHERE name = '{name}'")
    return str(cursor.fetchall())


@app.route("/items")
def search_items():
    query = request.args.get("q")
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM items WHERE title LIKE '%" + query + "%'")
    return str(cursor.fetchall())
