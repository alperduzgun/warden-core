"""
Credential store for Warden CLI auth tokens.

Persists auth session to ``~/.warden/credentials.json`` with restricted
file permissions (0600).
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

from warden.auth.models import AuthSession
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

_WARDEN_DIR = Path.home() / ".warden"
_CREDENTIALS_FILE = _WARDEN_DIR / "credentials.json"


class CredentialStore:
    """Read/write auth credentials to disk."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _CREDENTIALS_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, session: AuthSession) -> None:
        """Persist *session* as JSON with ``chmod 600``."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Compute absolute expiry from relative ``expires_in``
        if session.expires_at == 0.0:
            session.expires_at = time.time() + session.tokens.expires_in

        payload = session.to_json()
        self._path.write_text(json.dumps(payload, indent=2))

        # Restrict to owner read/write only
        os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
        logger.info("credentials_saved", path=str(self._path))

    def load(self) -> AuthSession | None:
        """Return the stored session or ``None``."""
        if not self._path.is_file():
            return None
        try:
            data = json.loads(self._path.read_text())
            return AuthSession.from_json(data)
        except Exception as exc:
            logger.warning("credentials_load_failed", error=str(exc))
            return None

    def clear(self) -> None:
        """Remove the credentials file."""
        if self._path.is_file():
            self._path.unlink()
            logger.info("credentials_cleared", path=str(self._path))

    def is_logged_in(self) -> bool:
        """``True`` if a non-expired session exists."""
        session = self.load()
        if session is None:
            return False
        return not self.is_expired(session)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_expired(session: AuthSession) -> bool:
        """``True`` when the access token has expired."""
        if session.expires_at == 0.0:
            return False
        return time.time() >= session.expires_at
