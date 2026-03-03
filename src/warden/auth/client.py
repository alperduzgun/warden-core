"""
HTTP client for Warden Cloud auth endpoints.

Uses ``httpx.AsyncClient`` following the project convention
(see ``src/warden/llm/config.py``).
"""

from __future__ import annotations

import os

import httpx

from warden.auth.models import AuthSession, AuthTokens, AuthUser, CliAuthResponse, Workspace
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_BASE_URL = "https://api.wardencloud.com"
_TIMEOUT = 15.0  # seconds


def _unwrap(body: dict) -> dict:
    """Unwrap the Panel ``ApiResponse`` envelope: ``{success, data, ...}``."""
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


class AuthClient:
    """Thin async wrapper around the Panel auth API."""

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (
            base_url
            or os.environ.get("WARDEN_CLOUD_URL")
            or _DEFAULT_BASE_URL
        )

    # ------------------------------------------------------------------
    # CLI session flow
    # ------------------------------------------------------------------

    async def init_cli_session(self) -> CliAuthResponse:
        """``POST /v1/auth/cli/init`` — start a browser-based auth flow."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{self._base_url}/v1/auth/cli/init")
            resp.raise_for_status()
            return CliAuthResponse.from_json(_unwrap(resp.json()))

    async def poll_cli_session(self, session_id: str) -> AuthSession | None:
        """``GET /v1/auth/cli/poll`` — check if the user has authenticated."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{self._base_url}/v1/auth/cli/poll",
                params={"session_id": session_id},
            )
            if resp.status_code == 202:
                # Not yet authenticated
                return None
            resp.raise_for_status()
            data = _unwrap(resp.json())
            tokens = AuthTokens.from_json(data["tokens"])
            user = AuthUser.from_json(data["user"])
            workspaces = [Workspace.from_json(w) for w in data.get("workspaces", [])]
            return AuthSession(tokens=tokens, user=user, workspaces=workspaces)

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def refresh_token(self, refresh_token: str) -> AuthTokens:
        """``POST /v1/auth/refresh`` — exchange a refresh token for new tokens."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{self._base_url}/v1/auth/refresh",
                json={"refreshToken": refresh_token},
            )
            resp.raise_for_status()
            return AuthTokens.from_json(_unwrap(resp.json()))

    # ------------------------------------------------------------------
    # User info
    # ------------------------------------------------------------------

    async def get_me(self, access_token: str) -> AuthUser:
        """``GET /v1/auth/me`` — fetch the authenticated user profile."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{self._base_url}/v1/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return AuthUser.from_json(_unwrap(resp.json()))

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------

    async def logout(self, access_token: str) -> None:
        """``POST /v1/auth/logout`` — invalidate the session on the backend."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                resp = await client.post(
                    f"{self._base_url}/v1/auth/logout",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                # Best-effort: log but don't block local cleanup
                logger.warning("remote_logout_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Onboarding
    # ------------------------------------------------------------------

    async def complete_onboarding(
        self,
        access_token: str,
        *,
        role: str | None = None,
        workspace_name: str | None = None,
    ) -> None:
        """``PUT /v1/users/me/onboarding`` — mark onboarding as done."""
        payload: dict[str, str] = {}
        if role:
            payload["role"] = role
        if workspace_name:
            payload["workspaceName"] = workspace_name

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.put(
                f"{self._base_url}/v1/users/me/onboarding",
                json=payload,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
