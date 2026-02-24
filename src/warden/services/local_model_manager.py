"""
Local Model Manager for Warden.

Manages Ollama lifecycle: start server, check model availability, pull models.
This is the Python equivalent of the CI shell script logic:
  ollama serve → health check → pull → scan
"""

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_OLLAMA_HOST = "http://localhost:11434"
_HEALTH_CHECK_RETRIES = 30
_HEALTH_CHECK_INTERVAL = 1.0  # seconds


def _get_ollama_host() -> str:
    """Return the Ollama host URL, validated against SSRF risks."""
    raw = os.environ.get("OLLAMA_HOST", _DEFAULT_OLLAMA_HOST).strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        logger.warning("ollama_host_invalid_scheme", scheme=parsed.scheme, fallback=_DEFAULT_OLLAMA_HOST)
        return _DEFAULT_OLLAMA_HOST
    return raw


class LocalModelManager:
    """
    Manages the Ollama local model lifecycle.

    Mirrors the CI shell script logic so init, scan preflight, and doctor
    can all share the same behaviour:
      1. ensure_ollama_running()  — start server if needed
      2. is_model_available()     — check /api/tags
      3. pull_model()             — subprocess ollama pull
      4. get_configured_models()  — read warden.yaml for required models
    """

    def __init__(self, ollama_host: str | None = None) -> None:
        self._host = (ollama_host or _get_ollama_host()).rstrip("/")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_installed(self) -> bool:
        """Return True if the ``ollama`` binary is available on PATH."""
        return shutil.which("ollama") is not None

    def install_ollama(self) -> bool:
        """
        Attempt to install Ollama using the official install script.

        - macOS: ``brew install ollama`` (if Homebrew is available), otherwise
          falls back to the curl installer.
        - Linux: ``curl -fsSL https://ollama.com/install.sh | sh``

        Returns True if installation succeeded.
        """
        import platform

        system = platform.system()
        logger.info("ollama_install_attempt", system=system)

        try:
            if system == "Darwin" and shutil.which("brew"):
                result = subprocess.run(
                    ["brew", "install", "ollama"],
                    timeout=300,
                )
            else:
                result = subprocess.run(
                    ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                    timeout=300,
                )
            success = result.returncode == 0
            if success:
                logger.info("ollama_install_success")
            else:
                logger.error("ollama_install_failed", returncode=result.returncode)
            return success
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.error("ollama_install_error", error=str(exc))
            return False

    def ensure_ollama_running(self) -> bool:
        """
        Ensure the Ollama server is reachable.

        If not running, attempts to start it via ``ollama serve`` and waits
        up to 30 s for the health endpoint to respond.

        Returns True when the server is ready, False on timeout or if the
        ``ollama`` binary is not available.
        """
        if self._ping():
            return True

        # Binary not found → can't start
        if not self.is_installed():
            logger.warning("ollama_binary_not_found")
            return False

        logger.info("ollama_not_running_starting")
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            logger.error("ollama_serve_launch_failed", error=str(exc))
            return False

        # Wait for health check
        for attempt in range(1, _HEALTH_CHECK_RETRIES + 1):
            time.sleep(_HEALTH_CHECK_INTERVAL)
            if self._ping():
                logger.info("ollama_ready", attempt=attempt)
                return True
            logger.debug("ollama_health_check_waiting", attempt=attempt, max=_HEALTH_CHECK_RETRIES)

        logger.error("ollama_start_timeout", retries=_HEALTH_CHECK_RETRIES)
        return False

    def is_model_available(self, model: str) -> bool:
        """Return True if *model* is present in the Ollama model list."""
        available = self._list_models()
        # Exact match first, then prefix match for tags like "qwen2.5-coder:7b"
        return model in available or any(m.startswith(model) for m in available)

    def pull_model(self, model: str, show_progress: bool = True) -> bool:
        """
        Run ``ollama pull <model>``.

        Parameters
        ----------
        model:
            The model tag to pull, e.g. ``qwen2.5-coder:7b``.
        show_progress:
            When True, subprocess output is streamed to stdout in real-time
            (suitable for interactive terminals). When False, output is
            suppressed (CI / non-interactive).

        Returns True on success, False on failure.
        """
        if not shutil.which("ollama"):
            logger.error("ollama_binary_not_found_pull", model=model)
            return False

        logger.info("ollama_pulling_model", model=model)
        stdout = None if show_progress else subprocess.DEVNULL
        stderr = None if show_progress else subprocess.DEVNULL

        try:
            result = subprocess.run(
                ["ollama", "pull", model],
                stdout=stdout,
                stderr=stderr,
                timeout=600,  # 10-minute hard cap
            )
            success = result.returncode == 0
            if success:
                logger.info("ollama_pull_success", model=model)
            else:
                logger.error("ollama_pull_failed", model=model, returncode=result.returncode)
            return success
        except subprocess.TimeoutExpired:
            logger.error("ollama_pull_timeout", model=model)
            return False
        except OSError as exc:
            logger.error("ollama_pull_os_error", model=model, error=str(exc))
            return False

    def get_configured_models(self, config_path: Path | None = None) -> list[str]:
        """
        Return all Ollama model names referenced in *warden.yaml*.

        Only returns models for providers that actually use Ollama:
        - ``llm.provider == "ollama"`` → primary model + fast_model
        - ``llm.use_local_llm == True`` → fast_model (hybrid mode)

        Parameters
        ----------
        config_path:
            Explicit path to ``warden.yaml`` / ``config.yaml``.  When omitted,
            searches ``cwd/warden.yaml`` then ``cwd/.warden/config.yaml``.
        """
        data = self._load_config(config_path)
        if not data:
            return []

        llm = data.get("llm", {})
        if not isinstance(llm, dict):
            return []

        provider = llm.get("provider", "")
        use_local = llm.get("use_local_llm", False)

        models: list[str] = []

        if provider == "ollama":
            # Primary model
            if m := llm.get("model", "").strip():
                models.append(m)
            # Fast model
            if m := llm.get("fast_model", "").strip():
                models.append(m)
            # Smart model (explicit override)
            if m := llm.get("smart_model", "").strip():
                models.append(m)

        elif use_local:
            # Hybrid mode: cloud for smart tier, Ollama for fast tier
            if m := llm.get("fast_model", "").strip():
                models.append(m)

        # Deduplicate, preserving order
        seen: set[str] = set()
        result: list[str] = []
        for m in models:
            if m and m not in seen:
                seen.add(m)
                result.append(m)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ping(self) -> bool:
        """Return True if the Ollama /api/tags endpoint responds."""
        try:
            urllib.request.urlopen(f"{self._host}/api/tags", timeout=2)
            return True
        except (URLError, OSError):
            return False

    def _list_models(self) -> list[str]:
        """Return names of all locally available Ollama models."""
        try:
            resp = urllib.request.urlopen(f"{self._host}/api/tags", timeout=3)
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
        except (URLError, OSError, json.JSONDecodeError, KeyError):
            return []

    @staticmethod
    def _load_config(config_path: Path | None) -> dict:
        """Load warden.yaml / config.yaml and return the parsed dict."""
        import yaml

        if config_path is None:
            cwd = Path.cwd()
            config_path = cwd / "warden.yaml"
            if not config_path.exists():
                config_path = cwd / ".warden" / "config.yaml"

        if not config_path.exists():
            return {}

        try:
            with open(config_path) as f:
                data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("local_model_manager_config_load_failed", error=str(exc))
            return {}
