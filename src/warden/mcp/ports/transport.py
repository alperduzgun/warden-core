"""
Transport Port

Abstract interface for MCP transport layer.
Implementations: STDIOTransport (current), SSETransport (future), WebSocketTransport (future)
"""

from abc import ABC, abstractmethod
from typing import Optional


class ITransport(ABC):
    """
    Abstract transport interface for MCP communication.

    Defines the contract for message I/O operations.
    Transport implementations handle the actual read/write
    mechanism (STDIO, SSE, WebSocket, etc.).
    """

    @abstractmethod
    async def read_message(self) -> Optional[str]:
        """
        Read a message from the transport.

        Returns:
            Message string, or None on EOF/close

        Raises:
            MCPTransportError: On transport-level failures
        """
        ...

    @abstractmethod
    async def write_message(self, data: str) -> None:
        """
        Write a message to the transport.

        Args:
            data: Message string to send

        Raises:
            MCPTransportError: On transport-level failures
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        Close the transport connection.

        Should be idempotent - safe to call multiple times.
        """
        ...

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """
        Check if transport is open and ready for I/O.

        Returns:
            True if transport is open, False otherwise
        """
        ...
