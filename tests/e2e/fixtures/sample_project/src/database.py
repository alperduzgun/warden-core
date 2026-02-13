"""Database layer with connection handling."""
import sqlite3
from contextlib import contextmanager

@contextmanager
def get_connection(db_path: str):
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()

def execute_query(conn, query: str, params=None):
    cursor = conn.cursor()
    cursor.execute(query, params or [])
    return cursor.fetchall()
