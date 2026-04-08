"""
False Positive: Uses circuit breaker — scanner must NOT flag.

corpus_labels:
  circuit-breaker: 0
"""

import pybreaker
import requests

payment_breaker = pybreaker.CircuitBreaker(fail_max=5, timeout_duration=60)


@payment_breaker
def call_payment_service(amount: float, currency: str) -> dict:
    """Payment call protected by pybreaker circuit breaker."""
    response = requests.post(
        "https://payments.example.com/charge",
        json={"amount": amount, "currency": currency},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
