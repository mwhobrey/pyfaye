import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from faye.exceptions import TransportError
from faye.protocol import Message

logger = logging.getLogger(__name__)


class Transport(ABC):
    """Base class for Faye transport implementations.

    This abstract class defines the interface for transport layers that handle
    the actual communication between client and server. Implementations include
    WebSocket and HTTP Long-Polling transports.

    Attributes:
    ----------
        url (str): The server URL to connect to
        connected (bool): Whether transport is currently connected

    Example:
    -------
        >>> class WebSocketTransport(Transport):
        ...     async def connect(self):
        ...         self._ws = await websockets.connect(self.url)
        ...         self._connected = True
        ...
        ...     async def send(self, message):
        ...         await self._ws.send(json.dumps(message.to_dict()))
        ...         return await self._ws.recv()

    Note:
    ----
        Implementations must handle:
        - Connection establishment and teardown
        - Message sending and receiving
        - Connection state management
        - Error handling and recovery

    """

    def __init__(self, url: str) -> None:
        """Initialize the transport.

        Args:
        ----
            url: The server URL to connect to

        """
        self.url = url
        self._connected: bool = False
        self._message_callback: Callable[[Message], Awaitable[None]] | None = None

    @property
    def connected(self) -> bool:
        """Check if transport is currently connected.

        Returns
        -------
            bool: True if connected, False otherwise

        """
        return self._connected

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection with the server.

        Implementations should:
        - Establish the physical connection
        - Set connected state
        - Initialize any required resources

        Raises
        ------
            TransportError: If connection fails

        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection with the server.

        Implementations should:
        - Close the physical connection
        - Clean up resources
        - Reset connected state

        Raises
        ------
            TransportError: If disconnect fails

        """
        pass

    @abstractmethod
    async def send(self, message: dict[str, Any] | Message) -> Message:
        """Send a message to the server and return the response.

        Args:
        ----
            message: The message to send (dict or Message object)

        Returns:
        -------
            Message: The server's response

        Raises:
        ------
            TransportError: If sending fails or connection is lost

        Note:
        ----
            Implementations should handle:
            - Message serialization/deserialization
            - Connection errors
            - Response timeout

        """
        pass

    @abstractmethod
    async def set_message_callback(
        self, callback: Callable[[Message], Awaitable[None]]
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
        pass

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
