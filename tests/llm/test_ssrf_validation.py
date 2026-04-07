import pytest

from warden.llm.config import _validate_ollama_endpoint


def test_function_exists_and_is_callable():
    assert callable(_validate_ollama_endpoint), (
        "_validate_ollama_endpoint must exist and be callable — "
        "removing or bypassing it breaks SSRF protection (issue #310)"
    )


def test_rejects_everything_guard():
    dangerous_inputs = [
        "http://169.254.169.254/latest/meta-data",
        "http://[fe80::1]:11434",
        "ftp://localhost:11434",
    ]
    results = [_validate_ollama_endpoint(url) for url in dangerous_inputs]
    assert not all(results), (
        "_validate_ollama_endpoint returns True for every input — "
        "the SSRF guard has been bypassed (issue #310)"
    )


@pytest.mark.parametrize(
    "url",
    [
        # Cloud metadata — always blocked regardless of allow_lan
        "http://169.254.169.254/latest/meta-data",
        # Link-local IPv6 (fe80::/10) — always blocked
        "http://[fe80::1]:11434",
        # IPv4-mapped link-local — always blocked
        "http://[::ffff:169.254.169.254]:11434",
        # Non-HTTP scheme — always blocked
        "ftp://localhost:11434",
    ],
)
def test_ssrf_vectors_are_rejected(url):
    assert _validate_ollama_endpoint(url) is False, (
        f"SSRF vector not blocked: {url!r}"
    )


@pytest.mark.parametrize(
    "url",
    [
        # Loopback — allowed for local providers (allow_lan=True)
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        # ULA (fd00::/7) — IPv6 private range, allowed for LAN providers
        "http://[fd00::1]:11434",
        # RFC1918 and internal hostnames — allowed for LAN
        "https://ollama.internal:11434",
        "http://192.168.1.100:11434",
    ],
)
def test_valid_endpoints_are_allowed(url):
    assert _validate_ollama_endpoint(url) is True, (
        f"Legitimate Ollama endpoint incorrectly rejected: {url!r}"
    )
