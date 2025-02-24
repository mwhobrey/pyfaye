"""Base transport implementation following official Faye protocol."""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import ClassVar

from faye.exceptions import TransportError
from faye.protocol import Message

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """Transport connection states.

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


class Transport(ABC):
    """Base class for Faye transport implementations.

    This abstract class defines the interface for transport layers that handle
    the actual communication between client and server. Implementations include
    WebSocket and HTTP Long-Polling transports.

    Attributes:
    ----------
        DEFAULT_TIMEOUT (int): Default timeout in milliseconds (60 seconds)
        DEFAULT_PING_INTERVAL (int): Default ping interval in milliseconds (5 seconds)
        MAX_RETRY_DELAY (int): Maximum retry delay in milliseconds (30 seconds)
        url (str): The server URL to connect to
        connected (bool): Whether transport is currently connected
        state (ConnectionState): Current connection state

    Implementation Requirements:
    -------------------------
    Subclasses must implement:
        - _connect(): Establish physical connection
        - _disconnect(): Close physical connection
        - _send(): Send message(s) to server
        - _ping(): Connection keepalive logic

    Error Handling:
    -------------
    The transport handles:
        - Connection failures with automatic retry
        - Message send/receive errors
        - State transitions
        - Resource cleanup

    """

    # Default timeout values (in milliseconds)
    DEFAULT_TIMEOUT: ClassVar[int] = 60000  # 60 seconds
    DEFAULT_PING_INTERVAL: ClassVar[int] = 5000  # 5 seconds
    MAX_RETRY_DELAY: ClassVar[int] = 30000  # 30 seconds

    def __init__(self, url: str) -> None:
        """Initialize the transport.

        Args:
        ----
            url: The server URL to connect to

        """
        self.url = url
        self._state = ConnectionState.UNCONNECTED
        self._message_callback: Callable[[Message], Awaitable[None]] | None = None
        self._pending_messages: list[Message] = []
        self._retry_count = 0
        self._ping_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        """Check if transport is currently connected.

        Returns:
        -------
            bool: True if connected, False otherwise

        """
        return self._state == ConnectionState.CONNECTED

    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        return self._state

    async def _transition_state(self, new_state: ConnectionState) -> None:
        """Handle connection state transitions."""
        if self._state == new_state:
            return  # No transition needed if already in target state

        valid_transitions = {
            ConnectionState.UNCONNECTED: {ConnectionState.CONNECTING},
            ConnectionState.CONNECTING: {
                ConnectionState.CONNECTED,
                ConnectionState.DISCONNECTED,
            },
            ConnectionState.CONNECTED: {ConnectionState.DISCONNECTED},
            ConnectionState.DISCONNECTED: {ConnectionState.UNCONNECTED},
        }

        if new_state not in valid_transitions.get(self._state, set()):
            logger.warning(
                f"Invalid state transition attempted: {self._state.name} -> {new_state.name}",
            )
            # Handle special cases
            if (
                new_state == ConnectionState.DISCONNECTED
                and self._state == ConnectionState.UNCONNECTED
            ):
                # Already in a disconnected-like state, no need to transition
                return

            if (
                new_state == ConnectionState.UNCONNECTED
                and self._state == ConnectionState.DISCONNECTED
            ):
                # Already heading to unconnected, no need to transition
                return

            # If we get here, it's a truly invalid transition
            raise TransportError(
                f"Invalid state transition: {self._state.name} -> {new_state.name}",
            )

        old_state = self._state
        self._state = new_state
        logger.debug(f"Transport state changed: {old_state.name} -> {new_state.name}")

        if new_state == ConnectionState.CONNECTED:
            self._retry_count = 0
            await self._start_ping()
        elif new_state == ConnectionState.DISCONNECTED:
            await self._stop_ping()

    async def connect(self) -> None:
        """Establish connection with the server.

        Implementations should:
        - Establish the physical connection
        - Set connected state
        - Initialize any required resources

        Raises:
        ------
            TransportError: If connection fails

        """
        if self.connected:
            return

        await self._transition_state(ConnectionState.CONNECTING)
        try:
            await self._connect()
            await self._transition_state(ConnectionState.CONNECTED)
            # Send any pending messages
            await self._send_pending()
        except Exception as e:
            # Ensure we transition through DISCONNECTED to UNCONNECTED
            await self._transition_state(ConnectionState.DISCONNECTED)
            await self._transition_state(ConnectionState.UNCONNECTED)
            # Re-raise the original error without wrapping
            if isinstance(e, TransportError):
                raise
            raise TransportError(str(e)) from e

    @abstractmethod
    async def _connect(self) -> None:
        """Implement actual connection logic."""

    async def disconnect(self) -> None:
        """Close the connection with the server.

        Implementations should:
        - Close the physical connection
        - Clean up resources
        - Reset connected state

        Raises:
        ------
            TransportError: If disconnect fails

        """
        if not self.connected:
            return

        await self._transition_state(ConnectionState.DISCONNECTED)
        try:
            await self._disconnect()
        finally:
            await self._transition_state(ConnectionState.UNCONNECTED)

    @abstractmethod
    async def _disconnect(self) -> None:
        """Implement actual disconnection logic."""

    async def send(self, message: Message | list[Message]) -> Message | list[Message]:
        """Send message(s) to the server.

        Args:
        ----
            message: Message or list of messages to send

        Returns:
        -------
            Message or list[Message]: Response from server

        Raises:
        ------
            TransportError: If send fails

        """
        if not self.connected:
            try:
                await self.connect()
            except Exception as e:
                raise TransportError("Not connected") from e

        try:
            return await self._send(message)
        except Exception as e:
            if isinstance(e, TransportError):
                raise
            raise TransportError(str(e)) from e

    @abstractmethod
    async def _send(self, message: Message | list[Message]) -> Message | list[Message]:
        """Implement actual message sending logic.

        Must handle both single messages and batches.
        """

    async def _send_pending(self) -> None:
        """Send any pending messages."""
        while self._pending_messages and self.connected:
            message = self._pending_messages.pop(0)
            try:
                await self.send(message)
            except Exception as e:
                logger.error(f"Error sending pending message: {e}")
                self._pending_messages.insert(0, message)
                break

    async def _handle_connection_error(self, error: Exception) -> None:
        """Handle connection errors with retry logic."""
        logger.error(f"Transport error: {error}")

        # Only transition if not already disconnected/unconnected
        if self._state not in (
            ConnectionState.DISCONNECTED,
            ConnectionState.UNCONNECTED,
        ):
            try:
                await self._transition_state(ConnectionState.DISCONNECTED)
                await self._transition_state(ConnectionState.UNCONNECTED)
            except Exception as e:
                logger.error(f"Error during state transition: {e}")
                # Force state to UNCONNECTED if transitions fail
                self._state = ConnectionState.UNCONNECTED

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()

        delay = min(self._retry_count * 1000, self.MAX_RETRY_DELAY)
        self._retry_count += 1

        self._reconnect_task = asyncio.create_task(self._delayed_reconnect(delay))

    async def _delayed_reconnect(self, delay: int) -> None:
        """Attempt reconnection after delay."""
        await asyncio.sleep(delay / 1000)  # Convert to seconds
        try:
            await self.connect()
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")

    async def _start_ping(self) -> None:
        """Start ping interval for connection keepalive."""
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()

        self._ping_task = asyncio.create_task(self._ping_loop())

    async def _stop_ping(self) -> None:
        """Stop ping interval."""
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
            self._ping_task = None

    async def _ping_loop(self) -> None:
        """Maintain connection with periodic pings."""
        while self.connected:
            await asyncio.sleep(self.DEFAULT_PING_INTERVAL / 1000)
            try:
                await self._ping()
            except Exception as e:
                logger.error(f"Ping failed: {e}")
                await self._handle_connection_error(e)
                break

    @abstractmethod
    async def _ping(self) -> None:
        """Implement connection keepalive logic."""

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
            The callback will be invoked for all messages received outside
            of the normal request/response cycle (e.g., server pushes).

        """
        self._message_callback = callback

    async def handle_message(self, message: Message) -> None:
        """Process incoming message and invoke callback if set.

        Args:
        ----
            message: The received message to process

        Raises:
        ------
            TransportError: If callback execution fails

        Note:
        ----
            This method is typically called by implementations when
            receiving messages outside the normal request/response cycle.

        """
        if self._message_callback:
            try:
                await self._message_callback(message)
            except Exception as e:
                logger.error(f"Error in message callback: {e}")
                raise TransportError(f"Message callback error: {e}") from e
