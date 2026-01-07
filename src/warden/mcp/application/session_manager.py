"""
Session Manager

Manages MCP session lifecycle.
"""

import uuid
from typing import Optional

from warden.mcp.domain.models import MCPSession
from warden.mcp.domain.enums import ServerStatus


class SessionManager:
    """
    Manages MCP session lifecycle.

    Creates, tracks, and manages session state.
    """

    def __init__(self) -> None:
        """Initialize session manager."""
        self._current_session: Optional[MCPSession] = None

    def create_session(self) -> MCPSession:
        """
        Create a new session.

        Returns:
            New MCPSession instance
        """
        session_id = str(uuid.uuid4())
        self._current_session = MCPSession(session_id=session_id)
        return self._current_session

    def get_current(self) -> Optional[MCPSession]:
        """
        Get current session.

        Returns:
            Current session or None if not created
        """
        return self._current_session

    def has_session(self) -> bool:
        """Check if a session exists."""
        return self._current_session is not None

    def is_initialized(self) -> bool:
        """Check if current session is initialized."""
        if self._current_session is None:
            return False
        return self._current_session.initialized

    def is_running(self) -> bool:
        """Check if current session is running."""
        if self._current_session is None:
            return False
        return self._current_session.status == ServerStatus.RUNNING

    def end_session(self) -> None:
        """End current session."""
        if self._current_session is not None:
            self._current_session.stop()
            self._current_session = None
