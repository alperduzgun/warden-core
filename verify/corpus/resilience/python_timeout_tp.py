"""
True Positive: HTTP calls without timeout — scanner must flag these.

corpus_labels:
  timeout: 3
"""

import requests
import httpx
import aiohttp


def fetch_user_data(user_id: int) -> dict:
    """Fetches user data — no timeout specified."""
    response = requests.get(f"https://api.example.com/users/{user_id}")
    return response.json()


def fetch_payment_status(order_id: str) -> dict:
    """Fetches payment — no timeout, can hang indefinitely."""
    response = httpx.get(f"https://payments.internal/orders/{order_id}")
    return response.json()


async def fetch_notifications(user_id: int) -> list:
    """aiohttp session without timeout — blocks entire event loop on hang."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://notifs.internal/{user_id}") as resp:
            return await resp.json()
