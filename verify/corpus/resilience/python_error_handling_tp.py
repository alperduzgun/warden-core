"""
True Positive: Bare except and silent swallowing — scanner must flag.

corpus_labels:
  error-handling: 2
"""

import requests


def fetch_config(url: str) -> dict:
    try:
        response = requests.get(url, timeout=5)
        return response.json()
    except:  # bare except — catches KeyboardInterrupt too!
        return {}


def load_user(user_id: int) -> dict | None:
    try:
        response = requests.get(f"https://api.internal/users/{user_id}", timeout=10)
        return response.json()
    except Exception:  # no logging — error silently swallowed
        pass
    return None
