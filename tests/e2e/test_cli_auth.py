"""E2E tests for CLI auth commands: ``warden /login``, ``warden /logout``, ``warden /whoami``.

The Panel backend is mocked via ``unittest.mock`` — these tests verify the
CLI-side behaviour (prompts, credential storage, output formatting) without
needing a real backend.
"""

import json
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from warden.main import app

from tests.e2e.conftest import CliRunner, strip_ansi


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_FAKE_SESSION_ID = str(uuid.uuid4())
_FAKE_LOGIN_URL = f"https://app.wardencloud.com/cli/login?session_id={_FAKE_SESSION_ID}"
_FAKE_ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.fake"
_FAKE_REFRESH_TOKEN = "rt_fake_refresh_token"
_FAKE_USER_EMAIL = "testcli@warden.dev"
_FAKE_USER_NAME = "CLI Test User"


def _mock_cli_auth_response():
    """Return a mock CliAuthResponse."""
    from warden.auth.models import CliAuthResponse

    return CliAuthResponse(
        session_id=_FAKE_SESSION_ID,
        login_url=_FAKE_LOGIN_URL,
        expires_in=300,
    )


def _mock_auth_session():
    """Return a mock AuthSession (successful poll result)."""
    from warden.auth.models import AuthSession, AuthTokens, AuthUser

    return AuthSession(
        tokens=AuthTokens(
            access_token=_FAKE_ACCESS_TOKEN,
            refresh_token=_FAKE_REFRESH_TOKEN,
            expires_in=900,
        ),
        user=AuthUser(
            id=str(uuid.uuid4()),
            email=_FAKE_USER_EMAIL,
            name=_FAKE_USER_NAME,
            is_onboarded=True,
        ),
        workspaces=[],
        expires_at=time.time() + 900,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def credentials_path(tmp_path):
    """Provide a temp credentials file and patch CredentialStore to use it."""
    return tmp_path / "credentials.json"


@pytest.fixture
def store(credentials_path):
    """A CredentialStore pointed at a temp file."""
    from warden.auth.credentials import CredentialStore

    return CredentialStore(path=credentials_path)


# ---------------------------------------------------------------------------
# warden /login --help / warden /logout --help / warden /whoami --help
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestAuthHelp:
    """All three auth commands show help correctly."""

    def test_login_help(self, runner):
        result = runner.invoke(app, ["/login", "--help"])
        assert result.exit_code == 0
        out = strip_ansi(result.stdout)
        assert "Authenticate" in out or "authenticate" in out.lower()
        assert "--force" in out

    def test_logout_help(self, runner):
        result = runner.invoke(app, ["/logout", "--help"])
        assert result.exit_code == 0
        out = strip_ansi(result.stdout)
        assert "Log out" in out or "log out" in out.lower()

    def test_whoami_help(self, runner):
        result = runner.invoke(app, ["/whoami", "--help"])
        assert result.exit_code == 0
        out = strip_ansi(result.stdout)
        assert "authenticated" in out.lower() or "user" in out.lower()

    def test_all_auth_commands_in_root_help(self, runner):
        """/login, /logout, /whoami appear in `warden --help`."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        out = result.stdout.lower()
        assert "/login" in out
        assert "/logout" in out
        assert "/whoami" in out


# ---------------------------------------------------------------------------
# warden /login (mocked backend)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestLoginCommand:
    """warden /login — full flow with mocked AuthClient."""

    def test_login_happy_path(self, runner, credentials_path):
        """Successful login stores credentials and prints success message."""
        mock_session = _mock_auth_session()

        with (
            patch("warden.cli.commands.login._get_client") as mock_get_client,
            patch("warden.cli.commands.login._get_store") as mock_get_store,
            patch("warden.cli.commands.login.webbrowser.open"),
            patch("warden.cli.commands.login.Prompt.ask", return_value=""),
        ):
            client_mock = AsyncMock()
            client_mock.init_cli_session.return_value = _mock_cli_auth_response()
            client_mock.poll_cli_session.return_value = mock_session
            mock_get_client.return_value = client_mock

            from warden.auth.credentials import CredentialStore

            real_store = CredentialStore(path=credentials_path)
            mock_get_store.return_value = real_store

            result = runner.invoke(app, ["/login"])

        assert result.exit_code == 0
        out = strip_ansi(result.stdout)
        assert "Logged in" in out
        assert _FAKE_USER_EMAIL in out

        # Verify credentials file was created
        assert credentials_path.exists()
        creds = json.loads(credentials_path.read_text())
        assert creds["tokens"]["accessToken"] == _FAKE_ACCESS_TOKEN

    def test_login_already_logged_in(self, runner, credentials_path):
        """If already logged in, login shows message without re-authenticating."""
        # Pre-populate credentials
        from warden.auth.credentials import CredentialStore

        real_store = CredentialStore(path=credentials_path)
        real_store.save(_mock_auth_session())

        with patch("warden.cli.commands.login._get_store") as mock_get_store:
            mock_get_store.return_value = real_store
            result = runner.invoke(app, ["/login"])

        assert result.exit_code == 0
        out = strip_ansi(result.stdout)
        assert "Already logged in" in out
        assert _FAKE_USER_EMAIL in out

    def test_login_force_reauthenticates(self, runner, credentials_path):
        """--force flag triggers re-authentication even if already logged in."""
        from warden.auth.credentials import CredentialStore

        real_store = CredentialStore(path=credentials_path)
        real_store.save(_mock_auth_session())

        new_session = _mock_auth_session()

        with (
            patch("warden.cli.commands.login._get_client") as mock_get_client,
            patch("warden.cli.commands.login._get_store") as mock_get_store,
            patch("warden.cli.commands.login.webbrowser.open"),
            patch("warden.cli.commands.login.Prompt.ask", return_value=""),
        ):
            client_mock = AsyncMock()
            client_mock.init_cli_session.return_value = _mock_cli_auth_response()
            client_mock.poll_cli_session.return_value = new_session
            mock_get_client.return_value = client_mock
            mock_get_store.return_value = real_store

            result = runner.invoke(app, ["/login", "--force"])

        assert result.exit_code == 0
        out = strip_ansi(result.stdout)
        assert "Logged in" in out

    def test_login_poll_retry_on_failure(self, runner, credentials_path):
        """When first poll returns None, CLI retries after user presses Enter."""
        mock_session = _mock_auth_session()

        with (
            patch("warden.cli.commands.login._get_client") as mock_get_client,
            patch("warden.cli.commands.login._get_store") as mock_get_store,
            patch("warden.cli.commands.login.webbrowser.open"),
            patch("warden.cli.commands.login.Prompt.ask", return_value=""),
            patch("warden.cli.commands.login.Confirm.ask", return_value=True),
        ):
            client_mock = AsyncMock()
            client_mock.init_cli_session.return_value = _mock_cli_auth_response()
            # First poll: not ready, second poll: success
            client_mock.poll_cli_session.side_effect = [None, mock_session]
            mock_get_client.return_value = client_mock

            from warden.auth.credentials import CredentialStore

            mock_get_store.return_value = CredentialStore(path=credentials_path)

            result = runner.invoke(app, ["/login"])

        assert result.exit_code == 0
        out = strip_ansi(result.stdout)
        assert "Logged in" in out

    def test_login_shows_url_panel(self, runner, credentials_path):
        """Login displays the auth URL in a panel."""
        with (
            patch("warden.cli.commands.login._get_client") as mock_get_client,
            patch("warden.cli.commands.login._get_store") as mock_get_store,
            patch("warden.cli.commands.login.webbrowser.open"),
            patch("warden.cli.commands.login.Prompt.ask", return_value=""),
        ):
            client_mock = AsyncMock()
            client_mock.init_cli_session.return_value = _mock_cli_auth_response()
            client_mock.poll_cli_session.return_value = _mock_auth_session()
            mock_get_client.return_value = client_mock

            from warden.auth.credentials import CredentialStore

            mock_get_store.return_value = CredentialStore(path=credentials_path)

            result = runner.invoke(app, ["/login"])

        out = strip_ansi(result.stdout)
        assert "Warden Cloud Login" in out
        assert "wardencloud.com/cli/login" in out
        assert "Open this URL to authenticate" in out

    def test_login_opens_browser(self, runner, credentials_path):
        """Login attempts to open the browser with the login URL."""
        with (
            patch("warden.cli.commands.login._get_client") as mock_get_client,
            patch("warden.cli.commands.login._get_store") as mock_get_store,
            patch("warden.cli.commands.login.webbrowser.open") as mock_open,
            patch("warden.cli.commands.login.Prompt.ask", return_value=""),
        ):
            client_mock = AsyncMock()
            client_mock.init_cli_session.return_value = _mock_cli_auth_response()
            client_mock.poll_cli_session.return_value = _mock_auth_session()
            mock_get_client.return_value = client_mock

            from warden.auth.credentials import CredentialStore

            mock_get_store.return_value = CredentialStore(path=credentials_path)

            runner.invoke(app, ["/login"])

        mock_open.assert_called_once_with(_FAKE_LOGIN_URL)

    def test_login_triggers_onboarding_for_new_user(self, runner, credentials_path):
        """If user.is_onboarded is False, onboarding runs after login."""
        from warden.auth.models import AuthSession, AuthTokens, AuthUser

        new_user_session = AuthSession(
            tokens=AuthTokens(
                access_token=_FAKE_ACCESS_TOKEN,
                refresh_token=_FAKE_REFRESH_TOKEN,
                expires_in=900,
            ),
            user=AuthUser(
                id=str(uuid.uuid4()),
                email=_FAKE_USER_EMAIL,
                name=_FAKE_USER_NAME,
                is_onboarded=False,
            ),
            workspaces=[],
            expires_at=time.time() + 900,
        )

        mock_onboarding = AsyncMock()

        with (
            patch("warden.cli.commands.login._get_client") as mock_get_client,
            patch("warden.cli.commands.login._get_store") as mock_get_store,
            patch("warden.cli.commands.login.webbrowser.open"),
            patch("warden.cli.commands.login.Prompt.ask", return_value=""),
            patch(
                "warden.cli.commands.onboarding.run_onboarding",
                mock_onboarding,
            ),
        ):
            client_mock = AsyncMock()
            client_mock.init_cli_session.return_value = _mock_cli_auth_response()
            client_mock.poll_cli_session.return_value = new_user_session
            mock_get_client.return_value = client_mock

            from warden.auth.credentials import CredentialStore

            mock_get_store.return_value = CredentialStore(path=credentials_path)

            result = runner.invoke(app, ["/login"])

        assert result.exit_code == 0
        mock_onboarding.assert_awaited_once()


# ---------------------------------------------------------------------------
# warden /logout
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestLogoutCommand:
    """warden /logout — clears credentials and invalidates remote session."""

    def test_logout_when_logged_in(self, runner, credentials_path):
        """Logout clears credentials and shows success."""
        from warden.auth.credentials import CredentialStore

        store = CredentialStore(path=credentials_path)
        store.save(_mock_auth_session())

        with (
            patch("warden.cli.commands.login._get_store") as mock_get_store,
            patch("warden.cli.commands.login._get_client") as mock_get_client,
        ):
            mock_get_store.return_value = store
            client_mock = AsyncMock()
            client_mock.logout.return_value = None
            mock_get_client.return_value = client_mock

            result = runner.invoke(app, ["/logout"])

        assert result.exit_code == 0
        out = strip_ansi(result.stdout)
        assert "Logged out" in out

        # Credentials file should be gone
        assert not credentials_path.exists()

    def test_logout_when_not_logged_in(self, runner, credentials_path):
        """Logout when not logged in shows informative message."""
        from warden.auth.credentials import CredentialStore

        with patch("warden.cli.commands.login._get_store") as mock_get_store:
            mock_get_store.return_value = CredentialStore(path=credentials_path)
            result = runner.invoke(app, ["/logout"])

        assert result.exit_code == 0
        out = strip_ansi(result.stdout)
        assert "Not currently logged in" in out

    def test_logout_calls_remote_logout(self, runner, credentials_path):
        """Logout calls AuthClient.logout to invalidate the remote session."""
        from warden.auth.credentials import CredentialStore

        store = CredentialStore(path=credentials_path)
        store.save(_mock_auth_session())

        with (
            patch("warden.cli.commands.login._get_store") as mock_get_store,
            patch("warden.cli.commands.login._get_client") as mock_get_client,
        ):
            mock_get_store.return_value = store
            client_mock = MagicMock()
            client_mock.logout = AsyncMock()
            mock_get_client.return_value = client_mock

            runner.invoke(app, ["/logout"])

        client_mock.logout.assert_called_once_with(_FAKE_ACCESS_TOKEN)


# ---------------------------------------------------------------------------
# warden /whoami
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestWhoamiCommand:
    """warden /whoami — displays authenticated user info."""

    def test_whoami_when_logged_in(self, runner, credentials_path):
        """Shows user info table when credentials exist."""
        from warden.auth.credentials import CredentialStore

        store = CredentialStore(path=credentials_path)
        store.save(_mock_auth_session())

        with patch("warden.cli.commands.login._get_store") as mock_get_store:
            mock_get_store.return_value = store
            result = runner.invoke(app, ["/whoami"])

        assert result.exit_code == 0
        out = strip_ansi(result.stdout)
        assert _FAKE_USER_EMAIL in out
        assert _FAKE_USER_NAME in out
        assert "Active" in out

    def test_whoami_when_not_logged_in(self, runner, credentials_path):
        """Shows not-logged-in message when no credentials."""
        from warden.auth.credentials import CredentialStore

        with patch("warden.cli.commands.login._get_store") as mock_get_store:
            mock_get_store.return_value = CredentialStore(path=credentials_path)
            result = runner.invoke(app, ["/whoami"])

        assert result.exit_code == 0
        out = strip_ansi(result.stdout)
        assert "Not logged in" in out
        assert "warden /login" in out

    def test_whoami_shows_expired_when_token_expired(self, runner, credentials_path):
        """Shows 'Expired' status when token has expired."""
        from warden.auth.credentials import CredentialStore
        from warden.auth.models import AuthSession, AuthTokens, AuthUser

        expired_session = AuthSession(
            tokens=AuthTokens(
                access_token=_FAKE_ACCESS_TOKEN,
                refresh_token=_FAKE_REFRESH_TOKEN,
                expires_in=900,
            ),
            user=AuthUser(
                id=str(uuid.uuid4()),
                email=_FAKE_USER_EMAIL,
                name=_FAKE_USER_NAME,
                is_onboarded=True,
            ),
            workspaces=[],
            expires_at=time.time() - 100,  # expired
        )

        store = CredentialStore(path=credentials_path)
        store.save(expired_session)
        # Manually override expires_at after save (save recalculates)
        import json as _json

        data = _json.loads(credentials_path.read_text())
        data["expiresAt"] = time.time() - 100
        credentials_path.write_text(_json.dumps(data))

        with patch("warden.cli.commands.login._get_store") as mock_get_store:
            mock_get_store.return_value = store
            result = runner.invoke(app, ["/whoami"])

        assert result.exit_code == 0
        out = strip_ansi(result.stdout)
        assert "Expired" in out


# ---------------------------------------------------------------------------
# CredentialStore unit tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestCredentialStore:
    """Credential storage: save, load, clear, permissions."""

    def test_save_and_load(self, store, credentials_path):
        session = _mock_auth_session()
        store.save(session)

        loaded = store.load()
        assert loaded is not None
        assert loaded.user.email == _FAKE_USER_EMAIL
        assert loaded.tokens.access_token == _FAKE_ACCESS_TOKEN

    def test_save_sets_file_permissions(self, store, credentials_path):
        """Credentials file must be owner-readable only (0600)."""
        import os
        import stat

        store.save(_mock_auth_session())

        mode = os.stat(credentials_path).st_mode
        assert mode & stat.S_IRGRP == 0, "Group should not have read"
        assert mode & stat.S_IROTH == 0, "Other should not have read"
        assert mode & stat.S_IRUSR != 0, "Owner should have read"

    def test_clear_removes_file(self, store, credentials_path):
        store.save(_mock_auth_session())
        assert credentials_path.exists()

        store.clear()
        assert not credentials_path.exists()

    def test_load_returns_none_when_no_file(self, store):
        assert store.load() is None

    def test_is_logged_in(self, store):
        assert store.is_logged_in() is False

        store.save(_mock_auth_session())
        assert store.is_logged_in() is True

    def test_is_expired(self, store, credentials_path):
        from warden.auth.credentials import CredentialStore
        from warden.auth.models import AuthSession, AuthTokens, AuthUser

        expired_session = AuthSession(
            tokens=AuthTokens(
                access_token="x",
                refresh_token="y",
                expires_in=1,
            ),
            user=AuthUser(
                id=str(uuid.uuid4()),
                email="e@e.com",
                name="E",
                is_onboarded=True,
            ),
            expires_at=time.time() - 10,
        )
        assert CredentialStore.is_expired(expired_session) is True

        valid_session = _mock_auth_session()
        assert CredentialStore.is_expired(valid_session) is False
