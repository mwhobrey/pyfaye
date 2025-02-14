import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

import aiohttp
from aiohttp import ClientSession, ClientTimeout

from faye.exceptions import TransportError
from faye.protocol import Message

from .base import Transport

logger = logging.getLogger(__name__)


class HttpTransport(Transport):
    """HTTP long-polling transport implementation for Faye.

    This transport uses HTTP long-polling to maintain a connection with
    the Faye server. It periodically sends connect messages and handles
    server responses through a polling loop.

    Attributes:
    ----------
        CONNECTION_TYPE (str): Transport identifier ("long-polling")
        url (str): Server URL to connect to
        connected (bool): Whether transport is connected

    Example:
    -------
        >>> transport = HttpTransport("http://server.com/faye")
        >>> await transport.connect()
        >>> response = await transport.send(handshake_message)
        >>> await transport.disconnect()

    Note:
    ----
        - Uses aiohttp for HTTP communication
        - Maintains persistent connection through polling
        - Handles server advice for timeouts and intervals
        - Automatically recovers from connection errors

    """

    CONNECTION_TYPE = "long-polling"

    def __init__(self, url: str) -> None:
        """Initialize HTTP transport.

        Args:
        ----
            url: The Faye server URL

        """
        super().__init__(url)
        self._session: ClientSession | None = None
        self._polling_task: asyncio.Task[None] | None = None
        self._connect_lock = asyncio.Lock()
        self._client_id: str | None = None

    async def connect(self) -> None:
        """Connect to the server using HTTP.

        Establishes an HTTP session and starts the polling loop
        for receiving messages.

        Raises
        ------
            TransportError: If connection fails or times out

        """
        if self._session:
            return

        try:
            session = ClientSession()
            self._session = await session.__aenter__()
            self._connected = True
            self._start_polling()
        except Exception as e:
            if isinstance(e, asyncio.TimeoutError):
                raise TransportError("Connection timed out") from e
            raise TransportError(f"Failed to connect: {e}") from e

    async def _cleanup(self) -> None:
        """Clean up transport resources.

        Cancels polling task and closes HTTP session.
        """
        self._connected = False
        if self._polling_task:
            self._polling_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._polling_task
            self._polling_task = None
        if self._session:
            await self._session.close()
            self._session = None

    async def send(self, message: dict[str, Any] | Message) -> Message:
        """Send message to server using HTTP POST.

        Args:
        ----
            message: Message to send (dict or Message object)

        Returns:
        -------
            Message: Server's response

        Raises:
        ------
            TransportError: If send fails or not connected

        Note:
        ----
            Automatically adds connection_type for connect messages

        """
        if not self._session or not self._connected:
            raise TransportError("Not connected")

        try:
            data = message.to_dict() if isinstance(message, Message) else message
            if isinstance(message, Message) and message.is_connect:
                self._client_id = message.client_id
                data["connection_type"] = self.CONNECTION_TYPE

            messages = [data] if not isinstance(data, list) else data

            async with self._session.post(self.url, json=messages) as response:
                response.raise_for_status()
                result = await response.json()
                return Message.from_dict(result[0])
        except Exception as e:
            raise TransportError(f"Failed to send message: {e}") from e

    def _start_polling(self) -> None:
        """Start long-polling task.

        Creates and starts an asyncio task for the polling loop.
        """
        if self._polling_task:
            return

        self._polling_task = asyncio.create_task(self._poll_messages())
        self._polling_task.add_done_callback(self._handle_task_done)

    def _handle_task_done(self, task: asyncio.Task[None]) -> None:
        """Handle completion of polling task.

        Args:
        ----
            task: The completed polling task

        Note:
        ----
            Logs any errors that occurred in the polling task.

        """
        try:
            task.result()
        except asyncio.CancelledError:
            pass  # Task was cancelled normally
        except Exception as e:
            logger.error(f"Polling task failed: {e}")

    async def _poll_messages(self) -> None:
        """Long-polling loop for receiving messages."""
        retry_delay = 1.0  # Default retry delay in seconds

        while self._connected and self._session:
            try:
                await self._poll_single_message(retry_delay)
            except asyncio.CancelledError:
                return
            except Exception as e:
                if self._connected:
                    logger.error(f"Polling error: {e}")
                    await asyncio.sleep(retry_delay)

    async def _poll_single_message(self, retry_delay: float) -> None:
        """Handle a single poll cycle."""
        connect_msg = self._create_connect_message()
        timeout = self._get_timeout()

        if not self._session:
            raise TransportError("Not connected")

        async with self._session.post(
            self.url, json=[connect_msg.to_dict()], timeout=ClientTimeout(total=timeout)
        ) as response:
            response.raise_for_status()
            await self._process_response(response, retry_delay)

        await asyncio.sleep(retry_delay)

    async def disconnect(self) -> None:
        """Close HTTP transport connection.

        Closes any open session and cleans up resources.

        Raises
        ------
            TransportError: If disconnect fails

        """
        try:
            # First cancel polling task
            if self._polling_task:
                self._polling_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._polling_task
                self._polling_task = None

            # Then close session
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                except Exception as e:
                    raise TransportError(f"Failed to disconnect: {e}") from e

            self._session = None
            self._connected = False
            logger.debug("HTTP transport disconnected")
        except Exception as e:
            logger.error(f"Error during HTTP transport disconnect: {e}")
            raise TransportError(f"Failed to disconnect: {e}") from e

    async def set_message_callback(
        self, callback: Callable[[Message], Awaitable[None]]
    ) -> None:
        """Set callback for incoming messages.

        Args:
        ----
            callback: Async function to handle incoming messages

        Note:
        ----
            Callback will be invoked for each message received through polling.

        """
        self._message_callback = callback

    def _create_connect_message(self) -> Message:
        """Create connect message for polling."""
        return Message(
            channel="/meta/connect",
            client_id=self._client_id,
            connection_type=self.CONNECTION_TYPE,
        )

    def _get_timeout(self) -> float:
        """Get timeout value from protocol advice."""
        return 30.0  # Default timeout

    async def _process_response(
        self, response: aiohttp.ClientResponse, retry_delay: float
    ) -> None:
        """Process polling response."""
        data = await response.json()
        messages = data if isinstance(data, list) else [data]
        for msg_data in messages:
            message = Message.from_dict(msg_data)
            await self.handle_message(message)
