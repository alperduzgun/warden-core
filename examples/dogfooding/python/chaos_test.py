"""
Chaos Frame Test - Resilience pattern detection.

This file contains code that LACKS proper chaos engineering patterns:
- No timeout handling
- No retry logic  
- No circuit breaker
- Poor error recovery
"""

import requests
import time


# 🔴 NO TIMEOUT - Chaos frame should detect this
def fetch_user_data(user_id: str) -> dict:
    """Fetches user data without any timeout handling."""
    response = requests.get(f"https://api.example.com/users/{user_id}")
    return response.json()


# 🔴 NO RETRY LOGIC - Should have retry for transient failures
def send_notification(message: str) -> bool:
    """Sends notification without retry logic."""
    response = requests.post(
        "https://notifications.example.com/send",
        json={"message": message}
    )
    return response.status_code == 200


# 🔴 NO CIRCUIT BREAKER - External service call without protection
def process_payment(amount: float) -> dict:
    """Processes payment without circuit breaker pattern."""
    response = requests.post(
        "https://payments.example.com/charge",
        json={"amount": amount}
    )
    if response.status_code != 200:
        # 🔴 POOR ERROR RECOVERY - Just raises, no fallback
        raise Exception("Payment failed")
    return response.json()


# 🔴 INFINITE RETRY POTENTIAL - No backoff, no max retries
def sync_data_dangerous():
    """Dangerous sync with potential infinite loop."""
    while True:
        try:
            response = requests.get("https://data.example.com/sync")
            if response.status_code == 200:
                return response.json()
        except Exception:
            time.sleep(1)  # Just sleeps and retries forever


# ✅ GOOD PATTERN - Proper timeout and error handling
def fetch_with_timeout(url: str, timeout: int = 5) -> dict:
    """Properly handles timeout."""
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        return {"error": "timeout", "fallback": True}
    except requests.RequestException as e:
        return {"error": str(e), "fallback": True}


if __name__ == "__main__":
    # These calls demonstrate the vulnerability
    fetch_user_data("123")
    send_notification("Hello")
