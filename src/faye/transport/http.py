"""HTTP transport implementation following official Faye protocol."""

import logging
from collections.abc import Awaitable, Callable
from typing import ClassVar

import aiohttp
from aiohttp import ClientSession, CookieJar

from faye.exceptions import TransportError
from faye.protocol import Message
from faye.transport.base import Transport

logger = logging.getLogger(__name__)


class HttpTransport(Transport):
    """HTTP transport implementation matching official Faye client.

    This class implements the HTTP long-polling transport layer for the Faye protocol,
    providing a fallback mechanism when WebSocket is not available.

    Attributes:
    ----------
        CONNECTION_TYPE (str): The transport type identifier
        DEFAULT_PORTS (dict[str, int]): Default ports for HTTP protocols

    Features:
    --------
        - HTTP long-polling with automatic reconnection
        - Message batching support
        - Cookie-based session management
        - Configurable timeouts
        - Error handling and recovery

    """

    CONNECTION_TYPE: ClassVar[str] = "long-polling"
    DEFAULT_PORTS: ClassVar[dict[str, int]] = {"http:": 80, "https:": 443}

    def __init__(self, url: str) -> None:
        """Initialize HTTP transport.

        Args:
        ----
            url: The HTTP server URL to connect to

        """
        super().__init__(url)
        self._session: ClientSession | None = None
        self._cookie_jar = CookieJar()
        self._message_callback: Callable[[Message], Awaitable[None]] | None = None

    async def _connect(self) -> None:
        """Create HTTP session.

        Raises:
        ------
            TransportError: If session creation fails

        """
        try:
            self._session = ClientSession(
                cookie_jar=self._cookie_jar,
                timeout=aiohttp.ClientTimeout(total=self.DEFAULT_TIMEOUT / 1000),
            )
        except Exception as err:
            raise TransportError(f"Failed to create HTTP session: {err}") from err

    async def _disconnect(self) -> None:
        """Close HTTP session and clear cookies.

        Raises:
        ------
            TransportError: If session cleanup fails
        """
        if self._session:
            try:
                await self._session.close()
                self._session = None
                self._cookie_jar.clear()
            except Exception as err:
                raise TransportError(f"Failed to disconnect: {err}") from err

    async def _send(self, message: Message | list[Message]) -> Message | list[Message]:
        """Send message using HTTP transport.

        Args:
        ----
            message: Message or list of messages to send

        Returns:
        -------
            Message or list[Message]: Response from server

        Raises:
        ------
            TransportError: If send fails or server returns an error

        """
        session = self._session
        if not session:
            raise TransportError("Not connected")

        try:
            messages = [message] if not isinstance(message, list) else message
            data = [
                msg.to_dict() if isinstance(msg, Message) else msg for msg in messages
            ]

            async with session.post(
                self.url,
                json=data if len(data) > 1 else data[0],
            ) as response:
                response.raise_for_status()

                result = await response.json()
                if not result:
                    raise TransportError("Empty response from server")

                return (
                    [Message.from_dict(r) for r in result]
                    if isinstance(message, list)
                    else Message.from_dict(result[0])
                )

        except aiohttp.ClientError as err:
            raise TransportError(f"HTTP request failed: {err}") from err
        except Exception as err:
            raise TransportError(f"Failed to send message: {err}") from err

    async def _ping(self) -> None:
        """No-op for HTTP transport.

        HTTP long-polling doesn't require ping/keepalive as each request
        creates a new connection.
        """

    async def set_message_callback(
        self,
        callback: Callable[[Message], Awaitable[None]],
    ) -> None:
        """Set callback for incoming messages.

        Args:
        ----
            callback: Async function to handle incoming messages

        Note:
        ----
            For HTTP transport, this is mostly unused since all messages
            are received as responses to requests.

        """
        self._message_callback = callback
