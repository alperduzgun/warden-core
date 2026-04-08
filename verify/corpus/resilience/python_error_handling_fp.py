"""
False Positive: Proper exception handling — scanner must NOT flag.
Uses specific exception types (not bare except), all with logging.

corpus_labels:
  error-handling: 0
"""

import logging

import requests

logger = logging.getLogger(__name__)


def fetch_config(url: str) -> dict:
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        logger.error("Config fetch timed out", extra={"url": url})
        return {}
    except requests.HTTPError as exc:
        logger.error("Config fetch HTTP error", extra={"status": exc.response.status_code})
        return {}
    except requests.ConnectionError as exc:
        logger.error("Config fetch connection failed: %s", exc)
        return {}


def parse_items(raw: list) -> list:
    """Pure data transform — no network, no error handling needed."""
    return [item for item in raw if item.get("active")]


# Test helper — pytest.raises is not a real error swallowing
def test_raises_on_bad_url() -> None:
    import pytest
    with pytest.raises(ValueError):
        fetch_config("")
