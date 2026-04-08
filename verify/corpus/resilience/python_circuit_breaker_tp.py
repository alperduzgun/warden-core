"""
True Positive: External HTTP calls without any circuit breaker pattern.

corpus_labels:
  circuit-breaker: 1
"""

import requests


def call_payment_service(amount: float, currency: str) -> dict:
    """Calls payment API with no circuit breaker — cascading failure risk."""
    response = requests.post(
        "https://payments.example.com/charge",
        json={"amount": amount, "currency": currency},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def send_notification(user_id: int, message: str) -> bool:
    """Calls notification service — no resilience pattern."""
    response = requests.post(
        "https://notify.internal/send",
        json={"user_id": user_id, "message": message},
        timeout=10,
    )
    return response.status_code == 200
