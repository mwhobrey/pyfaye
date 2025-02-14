import json
import logging
from asyncio import Lock
from typing import Any, ClassVar

from faye.exceptions import FayeError, HandshakeError, ProtocolError

from .message import Message, MessageFactory

logger = logging.getLogger(__name__)


class BayeuxProtocol:
    """Implements the Bayeux protocol for Faye pub/sub messaging.

    This class handles the protocol-level details of the Bayeux protocol,
    including handshaking, message creation, channel validation, and state
    management.

    Attributes:
    ----------
        SUPPORTED_CONNECTION_TYPES (List[str]): Supported transport types
        VERSION (str): Protocol version implemented
        advice (Dict[str, Any]): Server advice for connection management
        is_handshaken (bool): Whether handshake is complete
        supported_connection_types (List[str]): Server-supported transports

    Example:
    -------
        >>> protocol = BayeuxProtocol()
        >>> handshake = protocol.create_handshake_message()
        >>> response = await transport.send(handshake)
        >>> await protocol.process_handshake_response(response)
        >>> connect = protocol.create_connect_message()

    """

    SUPPORTED_CONNECTION_TYPES: ClassVar[list[str]] = ["websocket", "long-polling"]
    VERSION = "1.0"

    def __init__(self) -> None:
        """Initialize protocol state."""
        self._client_id: str | None = None
        self._supported_connection_types: list[str] = []
        self.advice: dict[str, Any] = {}
        self._handshaken = False
        self._lock = Lock()
        self._current_operation: str | None = None

    @property
    def is_handshaken(self) -> bool:
        """Check if handshake is complete.

        Returns
        -------
            bool: True if handshake is complete, False otherwise

        """
        return self._handshaken

    @property
    def supported_connection_types(self) -> list[str]:
        """Get server-supported connection types.

        Returns
        -------
            List[str]: List of transport types supported by server

        """
        return self._supported_connection_types

    def _validate_response(self, response: Message) -> None:
        """Validate response message and check for errors.

        Args:
        ----
            response: The message to validate

        Raises:
        ------
            ProtocolError: If response indicates an error

        """
        if not response.successful:
            error_msg = response.error or "Unknown error"
            raise ProtocolError(f"Server returned error: {error_msg}")

    async def handle_advice(self, advice: dict[str, Any] | None) -> None:
        """Handle server advice for reconnection strategies.

        Updates internal advice state with server recommendations for
        reconnection behavior.

        Args:
        ----
            advice: Server advice dictionary containing reconnection instructions

        """
        if advice:
            self.advice.update(advice)

    async def process_handshake_response(self, response: Message) -> None:
        """Process handshake response from server.

        Args:
        ----
            response: Server handshake response message

        Raises:
        ------
            HandshakeError: If handshake fails

        """
        if not response.successful:
            raise HandshakeError(f"Handshake failed: {response.error}")

        self._client_id = response.client_id
        # Convert connection types to lowercase for case-insensitive comparison
        if response.supported_connection_types:
            self._supported_connection_types = [
                t.lower() for t in response.supported_connection_types
            ]
        else:
            self._supported_connection_types = [
                "websocket",
                "long-polling",
            ]  # Default fallback

        if not self._client_id:
            raise HandshakeError("No client_id in handshake response")

        async with self._lock:
            self._handshaken = True

        await self.handle_advice(response.advice)

    def create_handshake_message(
        self,
        ext: dict[str, Any] | None = None,
        supported_connection_types: list[str] | None = None,
    ) -> Message:
        """Create handshake message with supported connection types.

        Args:
        ----
            ext: Optional extension data to include
            supported_connection_types: List of supported transports
                (defaults to self.SUPPORTED_CONNECTION_TYPES)

        Returns:
        -------
            Message: Handshake message ready to send

        Example:
        -------
            >>> msg = protocol.create_handshake_message(
            ...     ext={"auth": {"token": "secret"}},
            ...     supported_connection_types=["websocket"]
            ... )

        """
        if supported_connection_types is None:
            supported_connection_types = self.SUPPORTED_CONNECTION_TYPES

        return Message(
            channel="/meta/handshake",
            version=self.VERSION,
            supportedConnectionTypes=supported_connection_types,
            minimumVersion="1.0",
            ext=ext,
        )

    def create_connect_message(self, connection_type: str = "websocket") -> Message:
        """Create connect message for maintaining connection.

        Args:
        ----
            connection_type: Transport type being used

        Returns:
        -------
            Message: Connect message ready to send

        Raises:
        ------
            ProtocolError: If client is not handshaken

        """
        if not self._client_id:
            raise ProtocolError("Cannot connect without client_id. Handshake first.")

        return Message(
            channel="/meta/connect",
            client_id=self._client_id,
            connection_type=connection_type,
            advice=self.advice if self.advice else None,
        )

    def create_disconnect_message(self) -> Message:
        """Create disconnect message according to Bayeux protocol.

        Returns
        -------
            Message: Disconnect message ready to send

        Raises
        ------
            ProtocolError: If client is not handshaken

        """
        if not self._client_id:
            raise ProtocolError("Cannot disconnect without client_id")

        return Message(channel="/meta/disconnect", client_id=self._client_id)

    def create_subscribe_message(self, subscription: str) -> Message:
        """Create subscription message according to Bayeux protocol.

        Args:
        ----
            subscription: Channel to subscribe to

        Returns:
        -------
            Message: Subscribe message ready to send

        Raises:
        ------
            ProtocolError: If client is not handshaken
            FayeError: If channel name is invalid

        """
        if not self._client_id:
            raise ProtocolError("Cannot subscribe without client_id")

        self._validate_channel(subscription)
        return Message(
            channel="/meta/subscribe",
            client_id=self._client_id,
            subscription=subscription,
        )

    def create_unsubscribe_message(self, subscription: str) -> Message:
        """Create unsubscribe message for a channel.

        Args:
        ----
            subscription: Channel to unsubscribe from

        Returns:
        -------
            Message: Unsubscribe message ready to send

        Raises:
        ------
            ProtocolError: If client is not handshaken

        """
        if not self._client_id:
            raise ProtocolError("Cannot unsubscribe without client_id")

        return MessageFactory.unsubscribe(self._client_id, subscription)

    def create_publish_message(
        self,
        channel: str,
        data: str | int | bool | dict[str, Any] | list[str] | None,
    ) -> Message:
        """Create a publish message."""
        if not self._client_id:
            raise ProtocolError("Not connected - no client ID")
        return MessageFactory.publish(
            channel=channel,
            data=data,
            client_id=self._client_id,
        )

    def parse_message(self, data: str | dict[str, Any] | Message) -> Message:
        """Parse incoming message data into Message object.

        Args:
        ----
            data: Raw message data (string, dict, or Message)

        Returns:
        -------
            Message: Parsed message object

        Raises:
        ------
            ProtocolError: If message format is invalid

        """
        if isinstance(data, Message):
            return data

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                raise ProtocolError(f"Invalid JSON message: {e}") from e

        if not isinstance(data, dict):
            raise ProtocolError(f"Invalid message format: {type(data)}")

        return Message.from_dict(data)

    def reset(self) -> None:
        """Reset protocol state.

        Clears client ID, handshake state, and other protocol state
        in preparation for rehandshake.
        """
        self._client_id = None
        self._handshaken = False
        self._supported_connection_types = []
        self.advice = {}
        self._current_operation = None

    def _validate_channel(self, channel: str) -> None:
        """Validate channel name according to Bayeux spec.

        Args:
        ----
            channel: Channel name to validate

        Raises:
        ------
            FayeError: If channel name is invalid

        Note:
        ----
            - Channel must start with /
            - Segments cannot be empty
            - Cannot subscribe/publish to /meta/ or /service/
            - Wildcards * and ** must be full segments

        """
        if not channel:
            raise FayeError("Channel name cannot be empty")

        if not channel.startswith("/"):
            raise FayeError("Channel name must start with /")

        segments = channel.split("/")
        if "" in segments[1:]:  # Allow empty first segment for leading /
            raise FayeError("Channel segments cannot be empty")

        # Different error messages for subscribe and publish
        if channel.startswith("/meta/"):
            if self._current_operation == "subscribe":
                raise FayeError("Cannot subscribe to service channels")
            else:
                raise FayeError("Cannot publish to service channels")

        if channel.startswith("/service/"):
            if self._current_operation == "subscribe":
                raise FayeError("Cannot subscribe to service channels")
            else:
                raise FayeError("Cannot publish to service channels")

        # Allow ** as a full segment for globbing
        if any(("*" in seg and seg not in ["*", "**"]) for seg in segments):
            raise FayeError("Wildcard * can only be used as full segment")
