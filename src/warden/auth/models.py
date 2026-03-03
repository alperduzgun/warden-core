"""
Auth domain models.

Mirrors the Panel API types (camelCase JSON ↔ snake_case Python).
"""

from __future__ import annotations

from warden.shared.domain.base_model import BaseDomainModel


class AuthTokens(BaseDomainModel):
    """JWT token pair returned by the Panel backend."""

    access_token: str
    refresh_token: str
    expires_in: int  # seconds until access_token expires


class AuthUser(BaseDomainModel):
    """Authenticated user profile."""

    id: str
    email: str
    name: str | None = None
    avatar_url: str | None = None
    is_onboarded: bool = True
    role: str | None = None


class Workspace(BaseDomainModel):
    """User workspace."""

    id: str
    name: str
    plan: str | None = None


class AuthSession(BaseDomainModel):
    """Full session persisted to credentials file."""

    tokens: AuthTokens
    user: AuthUser
    workspaces: list[Workspace] = []
    expires_at: float = 0.0  # epoch timestamp


class CliAuthResponse(BaseDomainModel):
    """Response from POST /v1/auth/cli/init."""

    session_id: str
    login_url: str
    expires_in: int  # seconds until this auth request expires
