"""
False Positive: All HTTP calls have proper timeout — scanner must NOT flag.

corpus_labels:
  timeout: 0
"""

import requests
import httpx
import aiohttp


DEFAULT_TIMEOUT = 30


def fetch_user_data(user_id: int) -> dict:
    """Proper timeout via parameter."""
    response = requests.get(
        f"https://api.example.com/users/{user_id}",
        timeout=DEFAULT_TIMEOUT,
    )
    return response.json()


def fetch_payment_status(order_id: str) -> dict:
    """httpx with explicit timeout."""
    response = httpx.get(
        f"https://payments.internal/orders/{order_id}",
        timeout=30.0,
    )
    return response.json()


async def fetch_notifications(user_id: int) -> list:
    """aiohttp session with ClientTimeout."""
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"https://notifs.internal/{user_id}") as resp:
            return await resp.json()


class ApiClient:
    """Session configured once with timeout — individual calls inherit it."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.request = lambda *a, **kw: requests.Session.request(
            self._session, *a, timeout=30, **kw
        )

    def get(self, url: str) -> dict:
        return self._session.get(url).json()
