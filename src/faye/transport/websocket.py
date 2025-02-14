import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

import aiohttp
from aiohttp import ClientSession, WSMsgType, WSServerHandshakeError
from aiohttp import ClientWebSocketResponse as WebSocket
from websockets.exceptions import WebSocketException

from faye.exceptions import TransportError
from faye.protocol import Message

from .base import Transport

logger = logging.getLogger(__name__)


class WebSocketTransport(Transport):
    """WebSocket transport implementation for Faye.

    This transport maintains a persistent WebSocket connection with the Faye server,
    handling real-time message exchange and automatic reconnection.

    Attributes:
    ----------
        CONNECTION_TYPE (str): Transport identifier ("websocket")
        url (str): Server URL to connect to
        connected (bool): Whether transport is connected

    Example:
    -------
        >>> transport = WebSocketTransport("ws://server.com/faye")
        >>> await transport.connect()
        >>> response = await transport.send(handshake_message)
        >>> await transport.disconnect()

    Note:
    ----
        - Uses aiohttp for WebSocket communication
        - Maintains persistent WebSocket connection
        - Handles automatic heartbeats
        - Processes messages asynchronously
        - Supports the Faye WebSocket subprotocol

    """

    CONNECTION_TYPE = "websocket"

    def __init__(self, url: str) -> None:
        """Initialize WebSocket transport.

        Args:
        ----
            url: The Faye server URL (ws:// or wss://)

        """
        super().__init__(url)
        self._ws: WebSocket | None = None
        self._session: ClientSession | None = None
        self._client_id: str | None = None
        self._message_handler_task: asyncio.Task[None] | None = None
        self._connect_lock = asyncio.Lock()
        self._close_code: int | None = None
        self._close_reason: str | None = None
        self._connected = False
        self._message_callback: Callable[[Message], Awaitable[None]] | None = None

    @property
    def connected(self) -> bool:
        """Check if WebSocket is connected and ready.

        Returns
        -------
            bool: True if WebSocket is connected and open

        """
        return self._connected and self._ws is not None and not self._ws.closed

    async def connect(self, timeout: float | None = None) -> None:
        """Connect to WebSocket server.

        Args:
        ----
            timeout: Connection timeout in seconds

        Raises:
        ------
            TransportError: If connection fails or times out

        """
        try:
            if not self._session:
                self._session = ClientSession()

            connect_task = self._session.ws_connect(
                self.url, protocols=["faye-websocket"], heartbeat=30.0
            )

            if timeout is not None:
                try:
                    self._ws = await asyncio.wait_for(connect_task, timeout)
                except asyncio.TimeoutError as e:
                    await self._cleanup_session()
                    raise TransportError("Connection timed out") from e
            else:
                self._ws = await connect_task

            self._connected = True
            self._message_handler_task = asyncio.create_task(self._handle_messages())
            logger.debug("WebSocket connection established")
        except WSServerHandshakeError as e:
            await self._cleanup_session()
            raise TransportError(f"WebSocket connection failed: {e.message}") from e
        except WebSocketException as e:
            await self._cleanup_session()
            raise TransportError(f"WebSocket connection failed: {e}") from e
        except Exception as e:
            await self._cleanup_session()
            if isinstance(e, asyncio.TimeoutError):
                raise TransportError("Connection timed out") from e
            if isinstance(e, WSServerHandshakeError | WebSocketException):
                raise TransportError(f"WebSocket connection failed: {e}") from e
            raise TransportError(f"WebSocket connection failed: {e!s}") from e

    async def _cleanup_session(self) -> None:
        """Clean up the aiohttp session.

        Closes the session if it exists and is open.
        """
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def send(self, message: dict[str, Any] | Message) -> Message:
        """Send message over WebSocket.

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
            Messages are always sent as arrays per Faye spec

        """
        if not self._ws or not self._connected:
            raise TransportError("Not connected")

        try:
            data = message.to_dict() if isinstance(message, Message) else message
            if isinstance(message, Message) and message.is_connect:
                self._client_id = message.client_id
                data["connection_type"] = self.CONNECTION_TYPE

            await self._ws.send_json([data])  # Always send as array per Faye spec
            return await self._receive_message()
        except Exception as e:
            raise TransportError(f"Failed to send message: {e}") from e

    async def _receive_message(self) -> Message:
        """Receive and parse a single message.

        Returns:
        -------
            Message: Parsed message from server

        Raises:
        ------
            TransportError: If message format is invalid or receive fails

        Note:
        ----
            Handles both single messages and message arrays

        """
        if not self._ws:
            raise TransportError("Not connected")
        try:
            msg = await self._ws.receive_json()
            if isinstance(msg, list):
                msg = msg[0]  # Take first message from array
            if isinstance(msg, dict):
                return Message.from_dict(msg)
            raise TransportError(f"Invalid message format: {msg}")
        except Exception as e:
            raise TransportError(f"Failed to receive message: {e}") from e

    async def _handle_messages(self) -> None:
        """Handle incoming WebSocket messages.

        Processes incoming messages and routes them to the appropriate
        handler based on message type.

        Note:
        ----
            - Handles TEXT messages as Faye protocol messages
            - Processes CLOSE messages for clean shutdown
            - Logs ERROR messages
            - Supports batch message processing

        """
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if isinstance(msg, asyncio.CancelledError):
                    raise msg

                if msg.type == WSMsgType.TEXT:
                    await self._handle_text_message(msg.data)
                elif msg.type == WSMsgType.CLOSE:
                    await self._handle_close_message(msg)
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {msg.data}")
                    self._connected = False
                    break
        except asyncio.CancelledError:
            logger.debug("Message handler cancelled")
            raise
        except Exception as e:
            logger.error(f"WebSocket message handler failed: {e}")
            self._connected = False
            raise
        finally:
            self._connected = False

    async def disconnect(self) -> None:
        """Close WebSocket connection.

        Cancels message handler task and closes WebSocket connection.

        Raises:
        ------
            TransportError: If disconnect fails

        Note:
        ----
            Performs cleanup even if errors occur during disconnect

        """
        if self._ws:
            try:
                if self._message_handler_task:
                    self._message_handler_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await self._message_handler_task

                await self._ws.close()
                self._ws = None
                self._connected = False
                self._client_id = None
                logger.debug("WebSocket connection closed")
            except Exception as e:
                logger.error(f"Error during WebSocket disconnect: {e}")
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
            Callback will be invoked for each message received over WebSocket

        """
        self._message_callback = callback

    async def _handle_text_message(self, data: str) -> None:
        """Handle incoming text messages from WebSocket.

        Args:
        ----
            data: Raw JSON text data from WebSocket

        Note:
        ----
            - Parses JSON data into Message objects
            - Handles both single messages and arrays
            - Invokes message callback for each message
            - Logs but doesn't propagate parsing errors

        """
        try:
            data_dict = json.loads(data)
            messages = data_dict if isinstance(data_dict, list) else [data_dict]
            for msg_data in messages:
                if isinstance(msg_data, dict):
                    message = Message.from_dict(msg_data)
                    if self._message_callback:
                        await self._message_callback(message)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in WebSocket message: {e}")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")

    async def _handle_close_message(self, msg: aiohttp.WSMessage) -> None:
        """Handle WebSocket close messages.

        Args:
        ----
            msg: Close message from WebSocket

        Note:
        ----
            - Stores close code and reason
            - Updates connection state
            - Logs close event at debug level

        """
        logger.debug(f"Received close message: code={msg.data}, reason={msg.extra}")
        self._close_code = msg.data
        self._close_reason = msg.extra
        self._connected = False
