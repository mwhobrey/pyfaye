"""Bayeux protocol implementation following official Faye client."""

import json
import logging
import re
from asyncio import Lock
from typing import Any, ClassVar

from faye.exceptions import ErrorCode, FayeError
from faye.protocol.message import Message

logger = logging.getLogger(__name__)


class BayeuxError(FayeError):
    """Base class for Bayeux protocol errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode | int | None = None,
        params: list[Any] | None = None,
    ) -> None:
        """Initialize BayeuxError."""
        if isinstance(code, int):
            code_val = code
        else:
            code_val = code.value if code is not None else ErrorCode.SERVER_ERROR.value
        super().__init__(code_val, params or [], message)


class HandshakeError(BayeuxError):
    """Error during handshake process."""


class ProtocolError(BayeuxError):
    """Error in protocol operation."""


class BayeuxProtocol:
    """Implements the Bayeux protocol for Faye pub/sub messaging.

    This class handles the protocol-level details of the Bayeux protocol,
    including handshaking, message creation, channel validation, and state
    management.

    Attributes:
    ----------
        SUPPORTED_CONNECTION_TYPES (List[str]): Supported transport types
        VERSION (str): Protocol version implemented
        MINIMUM_VERSION (str): Minimum protocol version required
        ERROR_CODES (Dict[str, int]): Protocol error codes and their numeric values
        DEFAULT_ADVICE (Dict[str, Any]): Default server advice values for connection management
        META_PATTERN (str): Regex pattern for meta channels
        SERVICE_PATTERN (str): Regex pattern for service channels
        VALID_CHANNEL_PATTERN (str): Regex pattern for valid channel names
        VALID_SUBSCRIPTION_PATTERN (str): Regex pattern for valid subscription patterns

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
    MINIMUM_VERSION = "1.0"

    ERROR_CODES: ClassVar[dict[str, int]] = {
        "CHANNEL_EMPTY": 400,
        "CHANNEL_INVALID": 405,
        "CHANNEL_FORBIDDEN": 403,
        "CLIENT_UNKNOWN": 401,
        "VERSION_MISMATCH": 300,
        "CHANNEL_DENIED": 402,
    }

    DEFAULT_ADVICE: ClassVar[dict[str, Any]] = {
        "reconnect": "retry",
        "interval": 1000,
        "timeout": 60000,
    }

    META_PATTERN: ClassVar[str] = r"^/meta/([^/]+)$"
    SERVICE_PATTERN: ClassVar[str] = r"^/service/([^/]+)$"
    VALID_CHANNEL_PATTERN: ClassVar[str] = r"^(/[^/]+)+$"
    VALID_SUBSCRIPTION_PATTERN: ClassVar[str] = r"^(/[^/]+)*(/\*{1,2})?$"

    def __init__(self) -> None:
        """Initialize protocol state."""
        self._client_id: str | None = None
        self._supported_connection_types: list[str] = []
        self._advice: dict[str, Any] = {}  # Initialize with empty advice
        self._is_handshaken = False
        self._lock = Lock()
        self._current_operation: str | None = None

    @property
    def advice(self) -> dict[str, Any]:
        """Get current server advice."""
        return self._advice

    @property
    def supported_connection_types(self) -> list[str]:
        """Get supported connection types."""
        return self._supported_connection_types

    @supported_connection_types.setter
    def supported_connection_types(self, value: list[str] | None) -> None:
        """Set supported connection types."""
        self._supported_connection_types = value or []

    @property
    def is_handshaken(self) -> bool:
        """Check if handshake is complete."""
        return self._is_handshaken

    async def handle_advice(self, advice: dict[str, Any] | None) -> None:
        """Handle server advice.

        Args:
        ----
            advice: Server advice dictionary

        """
        if advice:
            self._advice = advice.copy()  # Store a copy of the advice

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
            error_msg = response.error or "Unknown error"
            error_code = (
                ErrorCode.VERSION_MISMATCH
                if "version" in error_msg.lower()
                else ErrorCode.CLIENT_UNKNOWN
            )
            raise HandshakeError(
                f"Handshake failed: {error_msg}",
                error_code,
                [],
            )

        # Handle advice if present
        if response.advice:
            await self.handle_advice(response.advice)

        self._client_id = response.client_id
        self._supported_connection_types = [
            t.lower()
            for t in (
                response.supported_connection_types or ["websocket", "long-polling"]
            )
        ]

        if not self._client_id:
            raise HandshakeError(
                "No client_id in handshake response",
                ErrorCode.CLIENT_UNKNOWN,
                [],
            )

        self._is_handshaken = True

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

        return Message.handshake(ext)

    def create_connect_message(self, connection_type: str = "websocket") -> Message:
        """Create connect message for maintaining connection."""
        if not self._client_id:
            raise ProtocolError(
                "Cannot connect without client_id",
                ErrorCode.CLIENT_UNKNOWN,
                [],
            )

        return Message(
            channel="/meta/connect",
            client_id=self._client_id,
            connection_type=connection_type,
            advice=self._advice if self._advice else None,  # Only include if not empty
        )

    def create_disconnect_message(self) -> Message:
        """Create disconnect message according to Bayeux protocol.

        Returns:
        -------
            Message: Disconnect message ready to send

        Raises:
        ------
            ProtocolError: If client is not handshaken

        """
        if not self._client_id:
            raise ProtocolError(
                "Cannot disconnect without client_id",
                self.ERROR_CODES["CLIENT_UNKNOWN"],
                [],
            )

        return Message.disconnect(self._client_id)

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
            raise ProtocolError(
                "Cannot subscribe without client_id",
                self.ERROR_CODES["CLIENT_UNKNOWN"],
                [],
            )

        self._validate_channel(subscription)
        return Message.subscribe(self._client_id, subscription)

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
            raise ProtocolError(
                "Cannot unsubscribe without client_id",
                self.ERROR_CODES["CLIENT_UNKNOWN"],
                [],
            )

        return Message.unsubscribe(self._client_id, subscription)

    def create_publish_message(self, channel: str, data: dict[str, Any]) -> Message:
        """Create a publish message for sending data to a channel.

        Args:
        ----
            channel: The channel to publish to
            data: The data to publish. Non-dict data will be wrapped in a dict with 'value' key

        Returns:
        -------
            Message: Publish message ready to send

        Raises:
        ------
            ProtocolError: If client is not handshaken

        """
        if not self._client_id:
            raise ProtocolError(
                "Not connected - no client ID",
                self.ERROR_CODES["CLIENT_UNKNOWN"],
                [],
            )

        if isinstance(data, str | int | bool | list):
            data = {"value": data}
        elif data is None:
            data = {}

        return Message.publish(channel, data, self._client_id)

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
            except json.JSONDecodeError as err:
                raise ProtocolError(
                    f"Invalid JSON message: {err}",
                    ErrorCode.CHANNEL_INVALID,
                    [],
                ) from err

        if not isinstance(data, dict):
            raise ProtocolError(
                f"Invalid message format: {type(data)}",
                ErrorCode.CHANNEL_INVALID,
                [],
            )

        return Message.from_dict(data)

    def reset(self) -> None:
        """Reset protocol state."""
        self._supported_connection_types = []
        self._is_handshaken = False
        self._client_id = None
        self._advice = {}
        self._current_operation = None

    def _validate_channel_empty(self, channel: str) -> None:
        """Check if channel name is empty.

        Args:
        ----
            channel: Channel name to validate

        Raises:
        ------
            BayeuxError: If channel name is empty

        """
        if not channel:
            raise BayeuxError(
                "Channel name cannot be empty",
                self.ERROR_CODES["CHANNEL_EMPTY"],
                [],
            )
        if not channel.startswith("/"):
            raise BayeuxError(
                "Channel name must start with /",
                self.ERROR_CODES["CHANNEL_INVALID"],
                [],
            )
        if "//" in channel:
            raise BayeuxError(
                "Channel segments cannot be empty",
                self.ERROR_CODES["CHANNEL_INVALID"],
                [],
            )

    def _validate_meta_channel(self, channel: str) -> bool:
        """Validate meta channel format."""
        if re.match(self.META_PATTERN, channel):
            if self._current_operation in ["subscribe", "publish"]:
                raise BayeuxError(
                    "Cannot subscribe or publish to meta channels",
                    self.ERROR_CODES["CHANNEL_FORBIDDEN"],
                    [],
                )
            return True
        return False

    def _validate_service_channel(self, channel: str) -> bool:
        """Validate service channel format."""
        if re.match(self.SERVICE_PATTERN, channel):
            if self._current_operation in ["subscribe", "publish"]:
                raise BayeuxError(
                    "Cannot subscribe or publish to service channels",
                    self.ERROR_CODES["CHANNEL_FORBIDDEN"],
                    [],
                )
            return True
        return False

    def _validate_wildcards(self, channel: str) -> None:
        """Validate wildcard usage in channel name."""
        segments = channel.split("/")
        for segment in segments[1:]:  # Skip first empty segment
            if "*" in segment and segment not in ["*", "**"]:
                raise BayeuxError(
                    "Wildcard * can only be used as full segment",
                    self.ERROR_CODES["CHANNEL_INVALID"],
                    [],
                )
            if "**" in segment and segment != "**":
                raise BayeuxError(
                    "Wildcard ** can only be used as full segment",
                    self.ERROR_CODES["CHANNEL_INVALID"],
                    [],
                )

    def _validate_channel(self, channel: str) -> None:
        """Validate channel name according to Bayeux spec.

        Args:
        ----
            channel: Channel name to validate

        Raises:
        ------
            BayeuxError: If channel name is invalid

        """
        # Basic validation
        self._validate_channel_empty(channel)

        # Check if it's a valid channel pattern
        if not re.match(self.VALID_CHANNEL_PATTERN, channel):
            raise BayeuxError(
                "Channel segments cannot be empty",
                self.ERROR_CODES["CHANNEL_INVALID"],
                [],
            )

        # Validate meta and service channels
        if self._validate_meta_channel(channel) or self._validate_service_channel(
            channel,
        ):
            return

        # Validate subscription pattern for subscribe operations
        if self._current_operation == "subscribe" and not re.match(
            self.VALID_SUBSCRIPTION_PATTERN,
            channel,
        ):
            raise BayeuxError(
                "Invalid subscription pattern",
                self.ERROR_CODES["CHANNEL_INVALID"],
                [],
            )

        # Validate wildcards
        self._validate_wildcards(channel)

    def _validate_message(self, message: Message | dict[str, Any]) -> Message:
        """Validate and convert message to Message object.

        Args:
        ----
            message: Message to validate

        Returns:
        -------
            Message: Validated message object

        Raises:
        ------
            ProtocolError: If message is invalid

        """
        # Convert dict to Message if needed
        if not isinstance(message, Message):
            try:
                message = Message.from_dict(message)
            except Exception as err:
                raise ProtocolError(
                    f"Invalid message format: {err}",
                    ErrorCode.CHANNEL_INVALID,
                    [],
                ) from err
        return message
