"""LLM provider test configuration.

All tests in this directory use mocked LLM clients and are classified as
integration tests. Tests that call real APIs are additionally marked llm.
"""

import pytest

pytestmark = pytest.mark.integration
