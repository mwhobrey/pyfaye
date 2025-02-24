"""Faye client implementation following official protocol.

This module provides the main client implementation for the Faye protocol,
supporting both WebSocket and HTTP Long-Polling transports. It handles:
- Connection management and automatic reconnection
- Message publishing and subscription
- Extension pipeline for message processing
- Error handling and recovery
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import IntEnum
from typing import Any
from urllib.parse import urlparse

from .exceptions import ErrorCode, FayeError
from .extensions import Extension
from .protocol import Message
from .protocol.bayeux import BayeuxProtocol
from .transport.base import Transport
from .transport.http import HttpTransport
from .transport.websocket import WebSocketTransport

logger = logging.getLogger(__name__)

# Type alias for supported float conversion types
FloatValue = float | int | str


class ConnectionState(IntEnum):
    """Connection states matching official client.

    Attributes:
    ----------
        UNCONNECTED: Initial state before connection attempt
        CONNECTING: Connection in progress
        CONNECTED: Successfully connected
        DISCONNECTED: Connection terminated

    """

    UNCONNECTED = 1
    CONNECTING = 2
    CONNECTED = 3
    DISCONNECTED = 4


class ReconnectType:
    """Reconnection strategies matching official client.

    Attributes:
    ----------
        RETRY: Attempt reconnection with backoff
        HANDSHAKE: Start fresh with new handshake
        NONE: Do not attempt reconnection

    """

    RETRY = "retry"
    HANDSHAKE = "handshake"
    NONE = "none"


class FayeClient:
    """Faye client implementation following official protocol.

    This class provides the main client implementation for the Faye protocol,
    supporting both WebSocket and HTTP Long-Polling transports.

    Args:
    ----
        url: The server URL to connect to
        transport_type: Transport type to use ('websocket' or 'http')
        extensions: Optional list of extensions to use

    Attributes:
    ----------
        connected (bool): Whether client is currently connected
        extensions (List[Extension]): Active extensions

    Example:
    -------
        >>> client = FayeClient('http://example.com/faye')
        >>> await client.connect()
        >>> await client.subscribe('/foo', callback)
        >>> await client.publish('/foo', {'text': 'Hello!'})

    """

    # Constants matching official client
    DEFAULT_ENDPOINT = "/bayeux"
    CONNECTION_TIMEOUT = 60.0  # seconds
    INTERVAL = 0.0  # seconds

    @staticmethod
    def _safe_float(value: float | str | None, default: float) -> float:
        """Convert value to float safely.

        Args:
        ----
            value: Value to convert
            default: Default value if conversion fails

        Returns:
        -------
            float: Converted value or default

        """
        if not isinstance(value, (float | str | None)) or value is None:
            return default

        try:
            if isinstance(value, float):
                return value
            return float(value)
        except (TypeError, ValueError):
            return default

    def __init__(
        self,
        url: str,
        transport_type: str = "websocket",
        extensions: list[Extension] | None = None,
    ) -> None:
        """Initialize the client."""
        self._url = url
        self._transport_type = transport_type.lower()
        self._transport: Transport | None = None
        self._protocol = BayeuxProtocol()
        self._subscriptions: dict[str, Callable[[Message], Awaitable[None]]] = {}
        self._extensions = extensions or []
        self._connect_lock = asyncio.Lock()
        self._disconnect_lock = asyncio.Lock()
        self._state = ConnectionState.UNCONNECTED
        self._client_id: str | None = None
        self._message_id = 0
        self._response_callbacks: dict[
            str,
            tuple[Callable[[Message], Awaitable[None]], Any],
        ] = {}

        # Initialize options
        self._retry_interval = self.INTERVAL
        self._request_timeout = self.CONNECTION_TIMEOUT

        # Initialize advice matching official client
        self._advice = {
            "reconnect": ReconnectType.RETRY,
            "interval": 1000 * self._retry_interval,  # Convert to milliseconds
            "timeout": 1000 * self._request_timeout,  # Convert to milliseconds
        }

    @property
    def client_id(self) -> str | None:
        """Get client ID assigned by server."""
        return self._client_id

    @property
    def connected(self) -> bool:
        """Check if client is currently connected."""
        return (
            self._transport is not None
            and self._transport.connected
            and self._protocol.is_handshaken
            and self._state == ConnectionState.CONNECTED
        )

    @property
    def state(self) -> str:
        """Get current connection state as string."""
        return self._state.name.lower()

    def _generate_message_id(self) -> str:
        """Generate unique message ID matching official client."""
        self._message_id += 1
        if self._message_id >= 2**32:
            self._message_id = 0
        return str(self._message_id).encode().hex()

    async def _handle_advice(self, advice: dict[str, Any]) -> None:
        """Handle server advice for reconnection strategies."""
        if not advice:
            return

        # Update advice
        self._advice.update(advice)

        # Handle reconnection advice
        reconnect = advice.get("reconnect")
        if (
            reconnect == ReconnectType.HANDSHAKE
            and self._state != ConnectionState.DISCONNECTED
        ):
            self._state = ConnectionState.UNCONNECTED
            self._client_id = None
            await self._cycle_connection()
        elif reconnect == ReconnectType.NONE:
            await self.disconnect()

    async def _cycle_connection(self) -> None:
        """Cycle the connection after advice or error."""
        interval = float(self._advice["interval"]) / 1000  # Convert to seconds
        await asyncio.sleep(interval)
        await self.connect()

    async def _deliver_message(self, message: Message) -> None:
        """Deliver message to subscribers."""
        if not message.channel or message.data is None:
            return

        # Convert string data to dict format for consistency
        data = message.data
        if isinstance(data, str):
            data = {"message": data}
        message.data = data

        # Check for pattern matches in subscriptions
        matched = False
        for pattern, callback in self._subscriptions.items():
            if message.matches(pattern):
                matched = True
                try:
                    await callback(message)
                except Exception as e:
                    logger.error(f"Error in subscription callback: {e}")

        if not matched and not message.is_meta:
            logger.debug(f"No subscribers for message on channel: {message.channel}")

    async def _send_message(
        self,
        message: Message,
        callback: Callable[[Message], Awaitable[None]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Send message and register response callback."""
        if not self._transport:
            raise FayeError(ErrorCode.TRANSPORT_ERROR, ["transport"], "Not connected")

        # Add message ID
        message.id = self._generate_message_id()

        # Register callback if provided
        if callback:
            self._response_callbacks[message.id] = (callback, context)

        try:
            # Process through extensions
            for extension in self._extensions:
                processed = await extension.process_outgoing(message)
                if not processed:
                    return
                message = processed

            # Send via transport
            await self._transport.send(message)

        except Exception as err:
            if message.id in self._response_callbacks:
                del self._response_callbacks[message.id]
            raise FayeError(ErrorCode.SERVER_ERROR, ["send"], str(err)) from err

    async def _receive_message(self, message: Message) -> None:
        """Handle incoming message from transport."""
        try:
            # Process through extensions
            for extension in self._extensions:
                processed = await extension.process_incoming(message)
                if not processed:
                    return
                message = processed

            # Handle advice
            if message.advice:
                await self._handle_advice(message.advice)

            # Handle response callbacks
            if (
                message.id is not None
                and message.successful is not None
                and message.id in self._response_callbacks
            ):
                callback, context = self._response_callbacks.pop(message.id)
                await callback(message)

            # Deliver message to subscribers
            await self._deliver_message(message)

        except Exception as err:
            logger.error(f"Error handling message: {err}")

    async def connect(self) -> None:
        """Connect to Faye server.

        This method:
        1. Establishes transport connection
        2. Performs protocol handshake
        3. Starts connection maintenance

        Raises:
        ------
            FayeError: If connection fails

        """
        async with self._connect_lock:
            if self._state == ConnectionState.CONNECTED:
                return

            try:
                await self._establish_connection()
            except Exception as err:
                self._state = ConnectionState.UNCONNECTED
                raise FayeError(
                    ErrorCode.CONNECTION_FAILED,
                    ["connect"],
                    str(err),
                ) from err

    async def _establish_connection(self) -> None:
        """Establish connection to Faye server."""
        try:
            # Create initial transport
            if not self._transport:
                parsed = urlparse(self._url)
                if self._transport_type == "long-polling":
                    self._transport = HttpTransport(self._url)
                else:
                    # Default to WebSocket
                    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
                    ws_url = parsed._replace(scheme=ws_scheme).geturl()
                    self._transport = WebSocketTransport(ws_url)

            # Connect transport
            await self._transport.connect()

            # Send handshake
            handshake = self._protocol.create_handshake_message()
            response = await self._transport.send(handshake)

            # Handle response list or single message
            if isinstance(response, list):
                response = response[0]  # Take first message from batch

            if response.successful:
                self._client_id = response.client_id
                self._state = ConnectionState.CONNECTED

                # Update protocol state
                self._protocol._client_id = response.client_id
                self._protocol.supported_connection_types = (
                    response.supported_connection_types or []
                )
                self._protocol._is_handshaken = True

                logger.info(f"Connected with client ID: {self._client_id}")
            else:
                raise FayeError(
                    ErrorCode.HANDSHAKE_FAILED,
                    ["handshake"],
                    str(response.error),
                )

        except Exception as err:
            await self._cleanup()
            raise FayeError(ErrorCode.SERVER_ERROR, ["connect"], str(err)) from err

    def _create_transport(self) -> Transport:
        """Create appropriate transport based on configuration and server support.

        Creates either WebSocket or HTTP transport based on client configuration
        and server-supported connection types.

        Returns:
        -------
            Transport: The configured transport instance

        Raises:
        ------
            FayeError: If no connection types are available
            ValueError: If no supported transport types are available

        """
        if not self._protocol.supported_connection_types:
            raise FayeError(
                ErrorCode.HANDSHAKE_FAILED,
                ["handshake"],
                "No connection types available - handshake first",
            )

        supported = [t.lower() for t in self._protocol.supported_connection_types]

        # If only long-polling is supported, must use HTTP transport
        if len(supported) == 1 and supported[0] == "long-polling":
            return HttpTransport(self._url)

        # Check client's preferred transport type
        if self._transport_type == "websocket" and "websocket" in supported:
            parsed = urlparse(self._url)
            ws_scheme = "wss" if parsed.scheme == "https" else "ws"
            ws_url = parsed._replace(scheme=ws_scheme).geturl()
            return WebSocketTransport(ws_url)

        if "long-polling" in supported:
            return HttpTransport(self._url)

        if "websocket" in supported:
            parsed = urlparse(self._url)
            ws_scheme = "wss" if parsed.scheme == "https" else "ws"
            ws_url = parsed._replace(scheme=ws_scheme).geturl()
            return WebSocketTransport(ws_url)

        raise ValueError("No supported transport types available")

    async def _handle_message(self, message: Message) -> None:
        """Handle incoming messages from transport."""
        try:
            # Process through extensions
            processed = await self._process_incoming(message)
            if not processed:
                return

            # Handle advice if present
            if processed.advice:
                await self._handle_advice(processed.advice)

            # Check for response callback
            if (
                processed.id is not None
                and processed.successful is not None
                and processed.id in self._response_callbacks
            ):
                callback, context = self._response_callbacks.pop(processed.id)
                await callback(processed)

            # Deliver message to subscribers
            await self._deliver_message(processed)

        except Exception as err:
            logger.error(f"Error handling message: {err}")
            raise FayeError(
                ErrorCode.MESSAGE_PROCESSING_ERROR,
                ["handle"],
                str(err),
            ) from err

    async def disconnect(self) -> None:
        """Disconnect from Faye server.

        This method:
        1. Sends disconnect message
        2. Closes transport connection
        3. Cleans up resources
        """
        if self._state == ConnectionState.UNCONNECTED:
            return

        try:
            if self._transport and self._client_id:
                message = self._protocol.create_disconnect_message()
                await self._transport.send(message)

        except Exception as err:
            logger.debug(f"Error during disconnect: {err}")

        finally:
            await self._cleanup()

    async def subscribe(
        self,
        channel: str,
        callback: Callable[[Message], Awaitable[None]],
    ) -> None:
        """Subscribe to a channel.

        Args:
        ----
            channel: Channel to subscribe to
            callback: Async function to handle messages

        Raises:
        ------
            FayeError: If subscription fails

        """
        await self._ensure_connected()

        message = self._protocol.create_subscribe_message(channel)
        self._subscriptions[channel] = callback

        try:
            await self._send_message(message, None)
        except Exception as err:
            del self._subscriptions[channel]
            raise FayeError(
                ErrorCode.SUBSCRIBE_FAILED,
                ["subscribe", channel],
                str(err),
            ) from err

    async def publish(self, channel: str, data: dict[str, Any] | str) -> None:
        """Publish a message to a channel.

        Args:
        ----
            channel: Channel to publish to
            data: Message data to publish (dict or string)

        Raises:
        ------
            FayeError: If publish fails

        """
        await self._ensure_connected()

        # Convert string data to dict format
        if isinstance(data, str):
            data = {"message": data}

        message = self._protocol.create_publish_message(channel, data)

        async def handle_publish_response(response: Message) -> None:
            if not response.successful:
                error = response.error or "Unknown error"
                raise FayeError(ErrorCode.PUBLISH_FAILED, ["publish"], str(error))

        try:
            await self._send_message(message, handle_publish_response, None)
        except Exception as err:
            raise FayeError(ErrorCode.PUBLISH_FAILED, ["publish"], str(err)) from err

    async def unsubscribe(self, channel: str) -> None:
        """Unsubscribe from a channel.

        Args:
        ----
            channel: Channel to unsubscribe from

        Raises:
        ------
            FayeError: If unsubscribe fails

        """
        await self._ensure_connected()

        if channel not in self._subscriptions:
            raise FayeError(
                ErrorCode.CHANNEL_UNKNOWN,
                ["unsubscribe", channel],
                f"Not subscribed to channel: {channel}",
            )

        message = self._protocol.create_unsubscribe_message(channel)

        try:
            await self._send_message(message, None)
            del self._subscriptions[channel]
        except Exception as err:
            raise FayeError(
                ErrorCode.UNSUBSCRIBE_FAILED,
                ["unsubscribe", channel],
                str(err),
            ) from err

    def add_extension(self, extension: Extension) -> None:
        """Add an extension to the client's extension pipeline.

        Args:
        ----
            extension: Extension instance to add

        """
        self._extensions.append(extension)

    def remove_extension(self, extension: Extension) -> None:
        """Remove an extension from the client's extension pipeline.

        Args:
        ----
            extension: Extension instance to remove

        """
        if extension in self._extensions:
            self._extensions.remove(extension)

    async def _process_outgoing(self, message: Message) -> Message | None:
        """Process message through outgoing extension pipeline."""
        current_message = message
        for extension in self._extensions:
            try:
                result = await extension.process_outgoing(current_message)
                if result is None:
                    return None
                current_message = result
            except Exception as e:
                logger.error(f"Extension error processing outgoing message: {e}")
        return current_message

    async def _process_incoming(self, message: Message | list[Message]) -> Message:
        """Process incoming message through extensions."""
        # Handle message lists
        if isinstance(message, list):
            message = message[0]  # Take first message from batch

        current_message = message
        for extension in self._extensions:
            try:
                result = await extension.process_incoming(current_message)
                if result is None:
                    raise FayeError(
                        ErrorCode.SERVER_ERROR,
                        ["extension"],
                        "Extension rejected message",
                    )
                current_message = result
            except Exception as e:
                logger.error(f"Extension error processing incoming message: {e}")
                raise

        return current_message

    async def _ensure_connected(self) -> None:
        """Ensure client is connected before operations."""
        if not self.connected:
            await self.connect()

    async def batch(self, messages: list[Message]) -> list[Message | None]:
        """Send multiple messages in a single request."""
        if not self._transport:
            raise FayeError(ErrorCode.TRANSPORT_ERROR, ["transport"], "Not connected")

        processed_messages: list[Message] = []
        for message in messages:
            processed = await self._process_outgoing(message)
            if processed:
                processed_messages.append(processed)

        if not processed_messages:
            return []

        try:
            responses = await self._transport.send(processed_messages)
            if isinstance(responses, list):
                return [
                    await self._process_incoming(response) for response in responses
                ]
            # Handle case where transport returns single message
            return [await self._process_incoming(responses)]
        except Exception as err:
            raise FayeError(ErrorCode.SERVER_ERROR, ["batch"], str(err)) from err

    async def _cleanup(self) -> None:
        """Clean up client resources."""
        try:
            if self._transport:
                await self._transport.disconnect()
                self._transport = None
            self._client_id = None
            self._state = ConnectionState.UNCONNECTED
            self._protocol.reset()
            self._subscriptions.clear()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
