"""Tests for SSRF taint sink detection (CWE-918).

Verifies that user-controlled URLs flowing into HTTP client sinks are detected
as HTTP-request taint paths by the taint analyzer.
"""

from __future__ import annotations

import pytest

from warden.validation.frames.security._internal.taint_analyzer import (
    TAINT_SINKS,
    TaintAnalyzer,
)

# ===========================================================================
# TestSSRFSinkRegistration
# ===========================================================================


class TestSSRFSinkRegistration:
    """TAINT_SINKS must include all expected HTTP client functions."""

    @pytest.mark.parametrize(
        "sink_name",
        [
            "requests.get",
            "requests.post",
            "requests.put",
            "requests.delete",
            "requests.patch",
            "requests.request",
            "requests.head",
            "urllib.request.urlopen",
            "urllib.request.Request",
            "httpx.get",
            "httpx.post",
            "httpx.put",
            "httpx.delete",
            "httpx.request",
            "httpx.AsyncClient.get",
            "httpx.AsyncClient.post",
            "aiohttp.ClientSession.get",
            "aiohttp.ClientSession.post",
            "aiohttp.ClientSession.request",
        ],
    )
    def test_http_sink_registered(self, sink_name: str) -> None:
        assert sink_name in TAINT_SINKS, f"{sink_name} not in TAINT_SINKS"
        assert TAINT_SINKS[sink_name] == "HTTP-request"

    def test_http_request_sink_type_exists(self) -> None:
        """At least one HTTP-request type sink must be registered."""
        http_sinks = {k: v for k, v in TAINT_SINKS.items() if v == "HTTP-request"}
        assert len(http_sinks) >= 5

    def test_existing_sinks_not_removed(self) -> None:
        """Existing SQL/CMD/FILE sinks must still be present."""
        assert "cursor.execute" in TAINT_SINKS
        assert "os.system" in TAINT_SINKS
        assert "eval" in TAINT_SINKS
        assert "open" in TAINT_SINKS


# ===========================================================================
# TestSSRFTaintDetection
# ===========================================================================


class TestSSRFTaintDetection:
    """TaintAnalyzer must detect SSRF when user input flows into HTTP sinks."""

    def setup_method(self) -> None:
        self.analyzer = TaintAnalyzer()

    def test_requests_get_user_url_detected(self) -> None:
        code = """
def fetch_resource():
    url = request.args.get("url")
    response = requests.get(url)
    return response.text
"""
        paths = self.analyzer.analyze(code)
        assert len(paths) >= 1
        assert any(p.sink.sink_type == "HTTP-request" for p in paths)

    def test_requests_post_user_url_detected(self) -> None:
        code = """
def webhook():
    target = request.form["webhook_url"]
    requests.post(target, json={"event": "test"})
"""
        paths = self.analyzer.analyze(code)
        assert any(p.sink.sink_type == "HTTP-request" for p in paths)

    def test_requests_get_hardcoded_url_safe(self) -> None:
        """Hardcoded URL with no taint source should not trigger SSRF."""
        code = """
def ping():
    response = requests.get("https://example.com/api/health")
    return response.status_code
"""
        paths = self.analyzer.analyze(code)
        http_paths = [p for p in paths if p.sink.sink_type == "HTTP-request"]
        assert len(http_paths) == 0

    def test_no_taint_clean_code(self) -> None:
        """Code with no taint sources should produce no paths."""
        code = """
def greet(name):
    return f"Hello, {name}"
"""
        paths = self.analyzer.analyze(code)
        assert len(paths) == 0

    def test_ssrf_propagation_through_variable(self) -> None:
        """Taint propagated through simple variable assignment reaches HTTP sink."""
        code = """
def proxy():
    raw = request.args.get("target")
    url = raw
    response = requests.get(url)
"""
        paths = self.analyzer.analyze(code)
        assert any(p.sink.sink_type == "HTTP-request" for p in paths)

    def test_urllib_urlopen_user_url_detected(self) -> None:
        code = """
def fetch():
    url = request.args.get("url")
    urllib.request.urlopen(url)
"""
        paths = self.analyzer.analyze(code)
        assert any(p.sink.sink_type == "HTTP-request" for p in paths)

    def test_ssrf_taint_path_has_correct_fields(self) -> None:
        """TaintPath for SSRF must have source, sink, and confidence fields."""
        code = """
def fetch_resource():
    url = request.args.get("url")
    response = requests.get(url)
"""
        paths = self.analyzer.analyze(code)
        http_paths = [p for p in paths if p.sink.sink_type == "HTTP-request"]
        assert len(http_paths) >= 1

        path = http_paths[0]
        assert path.sink.name in TAINT_SINKS
        assert path.confidence > 0.0
        assert path.source is not None
