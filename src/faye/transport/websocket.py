"""WebSocket transport implementation following official Faye protocol."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, ClassVar

from aiohttp import (
    ClientSession,
    ClientWebSocketResponse,
    WSMsgType,
    WSServerHandshakeError,
)

from faye.exceptions import TransportError
from faye.protocol import Message
from faye.transport.base import ConnectionState, Transport

logger = logging.getLogger(__name__)


class WebSocketTransport(Transport):
    """WebSocket transport implementation matching official Faye client.

    This class implements the WebSocket transport layer for the Faye protocol,
    providing real-time bidirectional communication between client and server.

    Attributes:
    ----------
        CONNECTION_TYPE (str): The transport type identifier
        DEFAULT_PORTS (dict[str, int]): Default ports for WebSocket protocols

    Features:
    --------
        - Automatic reconnection with exponential backoff
        - Message batching and response tracking
        - Channel subscription management
        - Heartbeat/ping for connection health monitoring
        - Graceful cleanup and resource management

    """

    CONNECTION_TYPE: ClassVar[str] = "websocket"
    DEFAULT_PORTS: ClassVar[dict[str, int]] = {"ws:": 80, "wss:": 443}

    def __init__(self, url: str) -> None:
        """Initialize WebSocket transport.

        Args:
        ----
            url: The WebSocket server URL to connect to

        """
        super().__init__(url)
        self._ws: ClientWebSocketResponse | None = None
        self._session: ClientSession | None = None
        self._message_callback: Callable[[Message], Awaitable[None]] | None = None
        self._pending_channels: set[str] = set()
        self._subscribed_channels: set[str] = set()
        self._ever_connected = False
        self._receive_task: asyncio.Task[None] | None = None
        self._response_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._connect_lock = asyncio.Lock()
        self._client_id: str | None = None
        self._advice: dict[str, Any] = {
            "reconnect": "retry",
            "interval": 0,
            "timeout": 60000,
        }

    @property
    def connected(self) -> bool:
        """Check if WebSocket is connected."""
        return (
            self._state == ConnectionState.CONNECTED
            and self._ws is not None
            and not self._ws.closed
        )

    @staticmethod
    def _truncate_message(
        message: str | bytes | dict[str, Any] | list[Any],
        max_length: int = 500,
    ) -> str:
        """Truncate message for logging.

        Args:
        ----
            message: Message to truncate
            max_length: Maximum length before truncation

        Returns:
        -------
            Truncated string representation

        """
        msg_str = str(message)
        if len(msg_str) > max_length:
            return f"{msg_str[:max_length]}... (truncated)"
        return msg_str

    async def _connect(self) -> None:
        """Create WebSocket connection.

        Raises:
        ------
            TransportError: If connection fails

        """
        try:
            if not self._session:
                self._session = ClientSession()

            self._ws = await self._session.ws_connect(
                self.url,
                protocols=["faye-websocket"],
                heartbeat=5.0,
                max_msg_size=1024 * 1024,
            )

            self._receive_task = asyncio.create_task(self._receive_loop())

        except Exception as err:
            await self._cleanup()
            # Format error message consistently
            error_msg = str(err)
            if isinstance(err, WSServerHandshakeError):
                error_msg = err.message
            raise TransportError(f"WebSocket connection failed: {error_msg}") from err

    async def _send_connect_message(self) -> None:
        """Send a connect message following server advice."""
        if not self._ws or not self._client_id:
            return

        try:
            connect_msg = Message(
                channel="/meta/connect",
                client_id=self._client_id,
                connection_type="websocket",
                version="1.0",
                advice=self._advice,
            )
            await self._ws.send_json([connect_msg.to_dict()])

        except Exception as e:
            logger.warning(f"Connect message error: {e}")
            await self._cleanup()

    async def _disconnect(self) -> None:
        """Close WebSocket connection."""
        try:
            await self._send_disconnect_message()
        except Exception as err:
            logger.debug(f"Failed to send disconnect message: {err}")

        try:
            await self._cleanup()
        except Exception as err:
            raise TransportError(f"Failed to disconnect: {err}") from err

    async def _send(self, message: Message | list[Message]) -> Message | list[Message]:
        """Send message using WebSocket transport.

        Args:
        ----
            message: Message or list of messages to send

        Returns:
        -------
            Message or list[Message]: Response from server

        Raises:
        ------
            TransportError: If send fails or times out

        """
        ws = self._ws
        if not ws:
            raise TransportError("Not connected")

        try:
            messages = [message] if not isinstance(message, list) else message
            data = [
                msg.to_dict() if isinstance(msg, Message) else msg for msg in messages
            ]

            await self._track_pending_channels(messages)
            await ws.send_json(data if len(data) > 1 else data[0])
            logger.debug(f"Sent WebSocket message: {self._truncate_message(data)}")

        except Exception as err:
            if not isinstance(err, TransportError) or not getattr(
                err,
                "timeout",
                False,
            ):
                await self._cleanup()
            raise TransportError(f"Failed to send message: {err}") from err

        try:
            response = await self._wait_for_response()
        except asyncio.TimeoutError as err:
            logger.error("Timeout waiting for initial response")
            if self._state == ConnectionState.CONNECTED:
                await self._cleanup()
            raise TransportError(
                "Timeout waiting for response",
                is_timeout=True,
            ) from err
        else:
            await self._handle_response(response)
            return response

        finally:
            await self._cleanup_pending_channels(messages)

    async def _track_pending_channels(self, messages: list[Message]) -> None:
        """Track channels waiting for responses."""
        for msg in messages:
            if isinstance(msg, Message):
                if msg.channel:
                    self._pending_channels.add(msg.channel)
                # Track subscribed channels
                if msg.channel == "/meta/subscribe" and msg.subscription:
                    self._subscribed_channels.add(msg.subscription)

    async def _wait_for_response(self) -> Message:
        """Wait for response with timeout."""
        return await asyncio.wait_for(self._response_queue.get(), timeout=60.0)

    async def _handle_response(self, response: Message) -> None:
        """Handle response message."""
        # Remove from pending after response
        if response.channel:
            self._pending_channels.discard(response.channel)

        # Handle subscription responses
        if response.channel == "/meta/subscribe":
            if response.successful:
                if response.subscription:
                    self._subscribed_channels.add(response.subscription)
            elif response.subscription:
                self._subscribed_channels.discard(response.subscription)

        # Check for errors
        if not response.successful:
            error_msg = response.error or "Unknown error"
            if "401:" in error_msg:
                # Re-establish connection on auth error
                await self._cleanup()
                await self._transition_state(ConnectionState.CONNECTING)
            raise TransportError(f"Server error: {error_msg}")

    async def _cleanup_pending_channels(self, messages: list[Message]) -> None:
        """Clean up pending channels."""
        for msg in messages:
            if isinstance(msg, Message) and msg.channel:
                self._pending_channels.discard(msg.channel)

    async def _receive_loop(self) -> None:
        """Background task to receive messages."""
        ws = self._ws
        if not ws:
            return

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_text_message(msg.data)
                elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                    logger.warning(f"WebSocket closed with type: {msg.type}")
                    break

        except Exception as err:
            logger.error(f"Error in receive loop: {err}", exc_info=True)

        finally:
            await self._cleanup()

    async def _handle_text_message(self, data: str) -> None:
        """Handle incoming text message.

        Args:
        ----
            data: Raw message data from WebSocket

        This method:
        - Parses the raw message data
        - Invokes registered callbacks
        - Handles protocol-specific messages
        - Queues responses for pending requests

        """
        try:
            messages = self._parse_messages(data)
            for msg_data in messages:
                message = Message.from_dict(msg_data)
                logger.debug(
                    f"Processing message: channel={message.channel}, id={message.id}",
                )

                await self._invoke_message_callback(message)

                if await self._handle_specific_message(message):
                    continue

                if self._should_queue_message(message):
                    logger.debug(f"Queueing message: channel={message.channel}")
                    await self._response_queue.put(message)
                else:
                    logger.debug(f"Skipping message: channel={message.channel}")

        except Exception as err:
            logger.error(f"Error handling text message: {err}", exc_info=True)
            raise

    def _parse_messages(self, data: str) -> list[dict[str, Any]]:
        """Parse incoming message data."""
        try:
            parsed = json.loads(data)
            logger.debug(
                f"WebSocket received raw data: {self._truncate_message(parsed)}",
            )
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError as err:
            logger.error(f"Error parsing message data: {err}")
            return []  # Return empty list for invalid JSON

    async def _invoke_message_callback(self, message: Message) -> None:
        """Invoke message callback if registered."""
        if self._message_callback:
            try:
                logger.debug("Invoking message callback")
                await self._message_callback(message)
            except Exception as err:
                logger.error(f"Error in message callback: {err}", exc_info=True)

    async def _handle_specific_message(self, message: Message) -> bool:
        """Handle protocol-specific message types.

        Args:
        ----
            message: Message to handle

        Returns:
        -------
            bool: True if message was handled and should not be queued

        This method handles:
        - Disconnect messages
        - Handshake responses
        - Connect responses

        """
        if message.channel == "/meta/disconnect":
            if not message.successful:
                logger.warning(f"Disconnect failed: {message.error}")
            await self._cleanup()
            return True

        if message.channel == "/meta/handshake" and message.successful:
            self._client_id = message.client_id
            if message.advice:
                self._advice.update(message.advice)
            await self._send_connect_message()
            return False

        if message.channel == "/meta/connect" and message.successful:
            if message.advice:
                self._advice.update(message.advice)
            interval = float(self._advice.get("interval", 0)) / 1000
            self._connect_task = asyncio.create_task(self._delayed_connect(interval))
            return False

        return False

    def _should_queue_message(self, message: Message) -> bool:
        """Check if message should be queued."""
        if not message.channel:
            return False

        return bool(
            message.channel.startswith("/meta/")
            or message.id
            or (message.channel and message.channel in self._pending_channels)
            or (message.channel and message.channel in self._subscribed_channels)
            or (message.data and message.channel in self._subscribed_channels),
        )

    async def _delayed_connect(self, delay: float) -> None:
        """Send connect message after delay."""
        if delay > 0:
            await asyncio.sleep(delay)
        await self._send_connect_message()

    async def _cleanup_receive_task(self) -> None:
        """Clean up the receive task."""
        if self._receive_task:
            self._receive_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._receive_task
            self._receive_task = None

    async def _cleanup_message_queue(self) -> None:
        """Clean up the message queue."""
        while not self._response_queue.empty():
            try:
                self._response_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self._pending_channels.clear()
        self._subscribed_channels.clear()

    async def _send_disconnect_message(self) -> None:
        """Send disconnect message if WebSocket is still connected."""
        if self._ws and not self._ws.closed:
            try:
                disconnect_msg = Message(
                    channel="/meta/disconnect",
                    client_id=self._client_id,
                    version="1.0",
                    minimum_version="1.0",
                )
                await self._ws.send_json([disconnect_msg.to_dict()])
                logger.debug("Sent disconnect message")
            except Exception as err:
                logger.debug(f"Failed to send disconnect message: {err}")

    async def _cleanup_websocket(self) -> None:
        """Clean up WebSocket connection."""
        if self._ws:
            try:
                if not self._ws.closed:
                    await self._ws.close()
                    logger.debug("WebSocket connection closed")
            except Exception as err:
                raise TransportError(f"Failed to disconnect: {err}") from err
            self._ws = None

    async def _cleanup_session(self) -> None:
        """Clean up client session."""
        if self._session:
            try:
                await self._session.close()
                logger.debug("Client session closed")
            except Exception as err:
                raise TransportError(f"Failed to disconnect: {err}") from err
            self._session = None

    async def _cleanup(self) -> None:
        """Clean up WebSocket connection and session."""
        # Cancel receive task first to prevent new messages during cleanup
        await self._cleanup_receive_task()

        # Clear message queue and channels
        await self._cleanup_message_queue()

        # Only transition if in CONNECTED state
        if self._state == ConnectionState.CONNECTED:
            try:
                # Send disconnect message before closing if still connected
                await self._send_disconnect_message()
                await self._transition_state(ConnectionState.DISCONNECTED)
                await self._transition_state(ConnectionState.UNCONNECTED)
            except Exception as err:
                logger.warning(f"Error during state transition: {err}")
                self._state = ConnectionState.UNCONNECTED

        # Close WebSocket and session
        await self._cleanup_websocket()
        await self._cleanup_session()

    async def set_message_callback(
        self,
        callback: Callable[[Message], Awaitable[None]],
    ) -> None:
        """Set callback for incoming messages."""
        self._message_callback = callback

    async def _ping(self) -> None:
        """Send WebSocket ping frame."""
        ws = self._ws
        if ws and not ws.closed:
            try:
                await ws.ping()
            except Exception as err:
                logger.warning(f"Failed to send ping: {err}")
                # Don't raise - let the receive loop handle disconnection
