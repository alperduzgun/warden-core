"""Shared fixtures for self_healing tests."""

from __future__ import annotations

import pytest

from warden.self_healing.orchestrator import reset_heal_attempts
from warden.self_healing.registry import HealerRegistry


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset healing attempts and registry before each test."""
    reset_heal_attempts()
    # Re-import strategies to ensure registry is populated after clear
    saved = dict(HealerRegistry._strategies)
    yield
    reset_heal_attempts()
    HealerRegistry._strategies = saved
