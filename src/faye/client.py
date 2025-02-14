import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from .exceptions import FayeError, TransportError
from .extensions.base import Extension
from .protocol.bayeux import BayeuxProtocol
from .protocol.message import Message
from .transport.base import Transport
from .transport.http import HttpTransport
from .transport.websocket import WebSocketTransport

logger = logging.getLogger(__name__)


class FayeClient:
    """A client implementation for the Faye publish-subscribe messaging protocol.

    This client supports both WebSocket and HTTP Long-Polling transports, handles automatic
    reconnection, and provides an extensible architecture through extensions.

    Args:
    ----
        url: The Faye server URL (e.g., "http://server.com/faye" or "ws://server.com/faye")
        transport_type: The transport type to use ('websocket' or 'http'). Defaults to 'websocket'

    Attributes:
    ----------
        url: The Faye server URL
        connected: Whether the client is currently connected

    Example:
    -------
        >>> client = FayeClient("http://server.com/faye")
        >>> await client.connect()
        >>> async def handler(message):
        ...     print(f"Received: {message.data}")
        >>> await client.subscribe("/channel", handler)
        >>> await client.publish("/channel", {"message": "Hello!"})

    """

    def __init__(self, url: str, transport_type: str = "websocket") -> None:
        """Initialize FayeClient.

        Args:
        ----
            url: The Faye server URL
            transport_type: Transport type to use ('websocket' or 'http')

        """
        self.url = url
        self._transport_type = transport_type.lower()
        self._transport: Transport | None = None
        self._protocol = BayeuxProtocol()
        self._subscriptions: dict[str, Callable[[Message], Awaitable[None]]] = {}
        self._connect_lock = asyncio.Lock()
        self._extensions: list[Extension] = []

    @property
    def connected(self) -> bool:
        """Check if client is connected to server.

        Returns
        -------
            bool: True if client is connected and handshaken, False otherwise

        """
        return (
            self._transport is not None
            and self._transport.connected
            and self._protocol.is_handshaken
        )

    def _create_transport(self) -> Transport:
        """Create appropriate transport based on configuration and server support.

        Creates either WebSocket or HTTP transport based on client configuration
        and server-supported connection types.

        Returns
        -------
            Transport: The configured transport instance

        Raises
        ------
            FayeError: If no connection types are available
            ValueError: If no supported transport types are available

        """
        if not self._protocol.supported_connection_types:
            raise FayeError("No connection types available - handshake first")

        supported = [t.lower() for t in self._protocol.supported_connection_types]

        # If only long-polling is supported, must use HTTP transport
        if len(supported) == 1 and supported[0] == "long-polling":
            return HttpTransport(self.url)

        # First check client's preferred transport type
        if self._transport_type == "websocket":
            if "websocket" in supported:
                parsed = urlparse(self.url)
                ws_scheme = "wss" if parsed.scheme == "https" else "ws"
                ws_url = parsed._replace(scheme=ws_scheme).geturl()
                return WebSocketTransport(ws_url)
            elif "long-polling" in supported:
                return HttpTransport(self.url)
        else:  # HTTP transport preferred
            if "long-polling" in supported:
                return HttpTransport(self.url)
            elif "websocket" in supported:
                parsed = urlparse(self.url)
                ws_scheme = "wss" if parsed.scheme == "https" else "ws"
                ws_url = parsed._replace(scheme=ws_scheme).geturl()
                return WebSocketTransport(ws_url)

        raise ValueError("No supported transport types available")

    async def _handle_message(self, message: Message) -> None:
        """Handle incoming messages from transport.

        Processes server advice messages and routes subscription messages
        to appropriate callbacks.

        Args:
        ----
            message: The incoming message to handle

        Note:
        ----
            Server advice can trigger:
            - Rehandshake if reconnect="handshake"
            - Retry if reconnect="retry"
            - Disconnect if reconnect="none"

        """
        # Handle server advice
        if message.advice:
            if message.advice.get("reconnect") == "handshake":
                self._protocol.reset()
                await self._rehandshake()
                return  # Return early to avoid further processing
            elif message.advice.get("reconnect") == "retry":
                await self._retry_connection()
            elif message.advice.get("reconnect") == "none":
                await self.disconnect()

        # Handle subscription messages
        for pattern, callback in self._subscriptions.items():
            if message.matches(pattern):
                try:
                    await callback(message)
                except Exception as e:
                    logger.error(f"Error in subscription callback: {e}")

    async def _rehandshake(self) -> None:
        """Perform a new handshake with the server.

        Disconnects current transport, resets protocol state,
        and initiates a new connection cycle.
        """
        if self._transport:
            await self._transport.disconnect()
            self._transport = None

        # Ensure protocol is reset before reconnecting
        self._protocol.reset()
        await self.connect()

    async def _retry_connection(self) -> None:
        """Retry the current connection.

        Attempts to send a new connect message using the current transport.
        Logs errors but does not raise them.
        """
        if not self._transport:
            return
        try:
            connect_msg = self._protocol.create_connect_message()
            await self._transport.send(connect_msg)
        except Exception as e:
            logger.error(f"Retry connection failed: {e}")

    async def connect(self, ext: dict[str, Any] | None = None) -> None:
        """Connect to the Faye server and perform handshake.

        Establishes connection to the server using the configured transport,
        performs protocol handshake, and starts the connection cycle.

        Args:
        ----
            ext: Optional extension data to include in handshake message

        Raises:
        ------
            FayeError: If connection fails
            TransportError: If transport connection fails
            HandshakeError: If protocol handshake fails

        """
        async with self._connect_lock:
            if self.connected:
                return

            # Create transport if needed
            if not self._transport:
                self._transport = self._create_transport()
                await self._transport.set_message_callback(self._handle_message)

            try:
                # Connect transport
                await self._transport.connect()

                # Perform handshake
                handshake_msg = self._protocol.create_handshake_message(ext=ext)
                response = await self._transport.send(handshake_msg)
                await self._protocol.process_handshake_response(response)

                # Start connection
                connect_msg = self._protocol.create_connect_message()
                await self._transport.send(connect_msg)

                logger.info("Successfully connected to Faye server")

            except Exception as e:
                # Clean up on failure
                if self._transport:
                    await self._transport.disconnect()
                self._transport = None
                raise FayeError(f"Connection failed: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from the Faye server.

        Sends disconnect message, closes transport connection, and cleans up
        client state including subscriptions.

        Raises
        ------
            FayeError: If disconnect fails

        """
        if not self.connected or not self._transport:
            return

        try:
            # Send disconnect message
            disconnect_msg = self._protocol.create_disconnect_message()
            await self._transport.send(disconnect_msg)

            # Clean up
            await self._transport.disconnect()
            self._transport = None
            self._subscriptions.clear()  # Clear all subscriptions
            self._protocol.reset()

            logger.info("Disconnected from Faye server")

        except Exception as e:
            raise FayeError(f"Disconnect failed: {e}") from e

    async def subscribe(
        self, channel: str, callback: Callable[[Message], Awaitable[None]]
    ) -> None:
        """Subscribe to a channel and register a message handler.

        Args:
        ----
            channel: The channel to subscribe to (e.g., "/foo" or "/foo/**")
            callback: Async function to handle received messages

        Raises:
        ------
            FayeError: If subscription fails or client not connected
            ValueError: If channel name is invalid

        Example:
        -------
            >>> async def handler(message):
            ...     print(f"Received: {message.data}")
            >>> await client.subscribe("/foo", handler)

        """
        if not self.connected or not self._transport:
            raise FayeError("Not connected")

        # Set current operation and validate channel
        self._protocol._current_operation = "subscribe"
        self._protocol._validate_channel(channel)

        try:
            # Send subscribe message
            subscribe_msg = self._protocol.create_subscribe_message(channel)
            processed = await self._process_outgoing(subscribe_msg)
            if processed is None:
                raise FayeError("Subscribe message halted by extension")

            response = await self._transport.send(processed)
            processed_response = await self._process_incoming(response)

            if not processed_response or not processed_response.successful:
                error = (
                    processed_response.error if processed_response else "Unknown error"
                )
                raise FayeError(f"Subscription failed: {error}")

            self._subscriptions[channel] = callback
            logger.info(f"Subscribed to channel: {channel}")

        except Exception as e:
            raise FayeError(f"Subscribe failed: {e}") from e

    async def unsubscribe(self, channel: str) -> None:
        """Unsubscribe from a channel."""
        if not self.connected or not self._transport:
            raise FayeError("Not connected")

        # Validate channel before unsubscribing
        self._protocol._validate_channel(channel)

        try:
            # Send unsubscribe message
            unsubscribe_msg = self._protocol.create_unsubscribe_message(channel)
            processed = await self._process_outgoing(unsubscribe_msg)
            if processed is None:
                raise FayeError("Unsubscribe message halted by extension")

            response = await self._transport.send(processed)
            processed_response = await self._process_incoming(response)

            if not processed_response or not processed_response.successful:
                error = (
                    processed_response.error if processed_response else "Unknown error"
                )
                raise FayeError(f"Unsubscribe failed: {error}")

            self._subscriptions.pop(channel, None)
            logger.info(f"Unsubscribed from channel: {channel}")

        except Exception as e:
            raise FayeError(f"Unsubscribe failed: {e}") from e

    async def publish(
        self, channel: str, data: str | int | bool | dict[str, Any] | list[str] | None
    ) -> None:
        """Publish a message to a channel.

        Args:
        ----
            channel: The channel to publish to
            data: The message data to publish (must be JSON-serializable)

        Raises:
        ------
            FayeError: If publish fails or client not connected
            ValueError: If channel name is invalid
            TypeError: If data cannot be JSON serialized

        Example:
        -------
            >>> await client.publish("/foo", {"message": "Hello!"})

        """
        if not self.connected or not self._transport:
            raise FayeError("Not connected")

        # Set current operation and validate channel
        self._protocol._current_operation = "publish"
        self._protocol._validate_channel(channel)

        try:
            # Send publish message
            publish_msg = self._protocol.create_publish_message(channel, data)
            processed = await self._process_outgoing(publish_msg)
            if processed is None:
                raise FayeError("Publish message halted by extension")

            response = await self._transport.send(processed)
            processed_response = await self._process_incoming(response)

            if not processed_response or not processed_response.successful:
                error = (
                    processed_response.error if processed_response else "Unknown error"
                )
                raise FayeError(f"Publish failed: {error}")

            logger.info(f"Published message to channel: {channel}")

        except Exception as e:
            raise FayeError(f"Publish failed: {e}") from e

    def add_extension(self, extension: Extension) -> None:
        """Add an extension to the client's extension pipeline.

        Extensions can modify or intercept messages in both directions.

        Args:
        ----
            extension: The extension instance to add

        Example:
        -------
            >>> auth = AuthenticationExtension("token")
            >>> client.add_extension(auth)

        """
        self._extensions.append(extension)

    async def _process_outgoing(self, message: Message) -> Message | None:
        """Process message through outgoing extension pipeline.

        Passes message through each extension's outgoing method in order.

        Args:
        ----
            message: The message to process

        Returns:
        -------
            Message: The processed message, or None if halted by an extension

        Note:
        ----
            Extensions are processed in registration order for outgoing messages.

        """
        current_message = message
        for extension in self._extensions:
            try:
                result = await extension.outgoing(current_message)
                if result is None:
                    return None
                current_message = result
            except Exception as e:
                logger.error(f"Extension error processing outgoing message: {e}")
        return current_message

    async def _process_incoming(self, message: Message) -> Message | None:
        """Process message through incoming extension pipeline.

        Passes message through each extension's incoming method in reverse order.

        Args:
        ----
            message: The message to process

        Returns:
        -------
            Message: The processed message, or None if halted by an extension

        Note:
        ----
            Extensions are processed in reverse registration order for incoming messages.

        """
        current_message = message
        for extension in reversed(self._extensions):  # Process in reverse order
            try:
                result = await extension.incoming(current_message)
                if result is None:
                    return None
                current_message = result
            except Exception as e:
                logger.error(f"Extension error processing incoming message: {e}")
        return current_message

    async def send(self, message: Message) -> Message | None:
        """Send message with extension processing.

        Processes message through extension pipeline, sends via transport,
        and processes response through extensions.

        Args:
        ----
            message: The message to send

        Returns:
        -------
            Message: The processed response message, or None if halted by an extension

        Note:
        ----
            This is a low-level method, prefer using publish() for normal messaging.

        """
        if not self._transport:
            raise TransportError("Not connected")
        processed = await self._process_outgoing(message)
        if processed is None:
            return None
        response = await self._transport.send(processed)
        return await self._process_incoming(response)
