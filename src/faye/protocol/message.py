from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from faye.exceptions import FayeError


@dataclass
class Message:
    """A Bayeux protocol message.

    This class represents messages exchanged in the Bayeux protocol,
    including handshake, connect, subscribe, publish and other message types.

    Attributes:
    ----------
        channel (str): The message channel (e.g., "/meta/handshake")
        id (str): Unique message identifier
        client_id (str, optional): Client identifier from server
        subscription (str, optional): Channel pattern for subscribe/unsubscribe
        data (Any, optional): Message payload
        error (str, optional): Error message from server
        successful (bool, optional): Success/failure indicator
        advice (Dict[str, Any], optional): Server connection advice
        ext (Dict[str, Any], optional): Extension data
        version (str): Protocol version (default: "1.0")
        minimum_version (str): Minimum supported version
        connection_type (str, optional): Transport type being used
        supported_connection_types (List[str], optional): Supported transports
        timestamp (str, optional): Message timestamp
        retry (int, optional): Retry interval in seconds
        interval (int, optional): Polling interval in seconds
        timeout (int, optional): Connection timeout in seconds

    Example:
    -------
        >>> msg = Message("/chat/public", data={"text": "Hello"})
        >>> msg.to_dict()
        {'channel': '/chat/public', 'data': {'text': 'Hello'}, 'id': '...'}

    """

    channel: str
    id: str = field(default_factory=lambda: str(uuid4()))
    client_id: str | None = None
    subscription: str | None = None
    data: Any | None = None
    error: str | None = None
    successful: bool | None = None
    advice: dict[str, str | int | bool] | None = None
    ext: dict[str, dict[str, str] | str] | None = None
    version: str = "1.0"
    minimum_version: str = "1.0"
    connection_type: str | None = None
    _connection_types: list[str] = field(default_factory=list)
    timestamp: str | None = None
    retry: int | None = None
    interval: int | None = None
    timeout: int | None = None

    def __init__(
        self,
        channel: str,
        **kwargs: str | int | bool | dict[str, Any] | list[str] | None,
    ) -> None:
        """Initialize a new message.

        Args:
        ----
            channel: The message channel
            **kwargs: Additional message fields

        """
        self.channel = channel
        self.id = str(kwargs.get("id", str(uuid4())))
        self.client_id = str(kwargs["client_id"]) if "client_id" in kwargs else None
        self.successful = bool(kwargs["successful"]) if "successful" in kwargs else None
        self.error = str(kwargs["error"]) if "error" in kwargs else None
        self.data = kwargs.get("data")

        # Handle ext with proper type checking
        ext_value = kwargs.get("ext")
        if isinstance(ext_value, dict):
            self.ext = {str(k): v for k, v in ext_value.items()}
        else:
            self.ext = {}

        # Handle advice with proper type checking
        advice_value = kwargs.get("advice")
        if isinstance(advice_value, dict):
            self.advice = {str(k): v for k, v in advice_value.items()}
        else:
            self.advice = {}

        # Handle connection types with proper type checking
        connection_types = kwargs.get("supportedConnectionTypes") or kwargs.get(
            "supported_connection_types"
        )
        if isinstance(connection_types, list):
            self._connection_types = [str(t).lower() for t in connection_types]
        else:
            self._connection_types = []

        self.subscription = (
            str(kwargs["subscription"]) if "subscription" in kwargs else None
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """Create a Message instance from a dictionary.

        Args:
        ----
            data: Dictionary containing message fields

        Returns:
        -------
            Message: New message instance

        Example:
        -------
            >>> data = {"channel": "/meta/connect", "client_id": "123"}
            >>> msg = Message.from_dict(data)

        """
        channel = data.pop("channel")
        data_value = data.pop("data", None)
        return cls(channel=channel, data=data_value, **data)

    def to_dict(self) -> dict[str, Any]:
        """Convert Message to dictionary, excluding None values.

        Returns:
        -------
            Dict[str, Any]: Dictionary representation of message

        Example:
        -------
            >>> msg = Message("/chat", data="Hello")
            >>> msg.to_dict()
            {'channel': '/chat', 'data': 'Hello', 'id': '...'}

        """
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @property
    def is_handshake(self) -> bool:
        """Check if message is a handshake message.

        Returns
        -------
            bool: True if channel is /meta/handshake

        """
        return self.channel == "/meta/handshake"

    @property
    def is_connect(self) -> bool:
        """Check if message is a connect message."""
        return self.channel == "/meta/connect"

    @property
    def is_subscribe(self) -> bool:
        """Check if message is a subscribe message."""
        return self.channel == "/meta/subscribe"

    @property
    def is_unsubscribe(self) -> bool:
        """Check if message is an unsubscribe message."""
        return self.channel == "/meta/unsubscribe"

    @property
    def is_disconnect(self) -> bool:
        """Check if message is a disconnect message."""
        return self.channel == "/meta/disconnect"

    @property
    def is_meta(self) -> bool:
        """Check if message is a meta channel message."""
        return self.channel.startswith("/meta/")

    @property
    def is_service(self) -> bool:
        """Check if message is a service channel message."""
        return self.channel.startswith("/service/")

    @property
    def error_type(self) -> str | None:
        """Get the type of error if present.

        Returns:
        -------
            str: Error type based on error code, or None if no error

        Note:
        ----
            Error types are mapped from Bayeux error codes:
            - 401: unauthorized
            - 403: forbidden
            - 405: invalid_channel
            - 409: connection_failed

        """
        if not self.error:
            return None
        # Parse error types according to Faye spec
        if "401" in str(self.error):
            return "unauthorized"
        if "403" in str(self.error):
            return "forbidden"
        if "405" in str(self.error):
            return "invalid_channel"
        if "409" in str(self.error):
            return "connection_failed"
        return "unknown"

    @property
    def is_error(self) -> bool:
        """Check if message represents an error.

        Returns
        -------
            bool: True if message has error or successful=False

        """
        return bool(self.error) or self.successful is False

    def validate(self) -> list[str]:
        """Validate the message according to Bayeux protocol.

        Returns:
        -------
            List[str]: List of error messages (empty if valid)

        Note:
        ----
            Validates:
            - Channel presence and format
            - Required fields for message type
            - Client ID requirements
            - Subscription field presence

        """
        errors = []

        if not self.channel:
            errors.append("Message must have a channel")
        elif not self.channel.startswith("/"):
            errors.append("Channel must start with /")

        if (self.is_subscribe or self.is_unsubscribe) and not self.subscription:
            errors.append(f"{self.channel} message must have a subscription field")

        if self.is_meta and not self.id:
            errors.append("Meta messages must have an id")

        if not self.is_handshake and not self.is_disconnect and not self.client_id:
            errors.append(
                "Message must have a client_id (except for handshake/disconnect)"
            )

        return errors

    def matches(self, pattern: str) -> bool:
        """Check if this message's channel matches a subscription pattern.

        Args:
        ----
            pattern: Channel pattern to match against

        Returns:
        -------
            bool: True if channel matches pattern

        Example:
        -------
            >>> msg = Message("/foo/bar")
            >>> msg.matches("/foo/*")  # True
            >>> msg.matches("/foo/**")  # True
            >>> msg.matches("/baz/*")  # False

        """
        if not pattern.startswith("/"):
            return False

        pattern_parts = pattern.split("/")
        channel_parts = self.channel.split("/")

        if "**" in pattern_parts:
            # Handle globbing pattern
            glob_index = pattern_parts.index("**")
            if not self._match_parts(
                pattern_parts[:glob_index], channel_parts[:glob_index]
            ):
                return False
            if glob_index < len(pattern_parts) - 1:
                return self._match_parts(
                    pattern_parts[glob_index + 1 :],
                    channel_parts[-len(pattern_parts[glob_index + 1 :]) :],
                )
            return True

        if len(pattern_parts) != len(channel_parts):
            return False

        return self._match_parts(pattern_parts, channel_parts)

    def _match_parts(self, pattern_parts: list[str], channel_parts: list[str]) -> bool:
        """Match channel parts against pattern parts."""
        return all(
            p == "*" or p == c
            for p, c in zip(pattern_parts, channel_parts, strict=False)
        )

    @property
    def supported_connection_types(self) -> list[str]:
        """Get supported connection types."""
        return self._connection_types

    @supported_connection_types.setter
    def supported_connection_types(self, value: list[str] | None) -> None:
        """Set supported connection types."""
        new_types: list[str] = []
        if value is not None:
            new_types.extend(str(t).lower() for t in value)
        self._connection_types = new_types

    # Protocol compatibility property
    @property
    def supportedConnectionTypes(self) -> list[str]:  # noqa: N802, RUF100
        """Get supported connection types (camelCase version for protocol compatibility)."""
        return self._connection_types

    @supportedConnectionTypes.setter  # noqa: N802, RUF100
    def supportedConnectionTypes(  # noqa: N802, RUF100
        self, value: list[str] | None
    ) -> None:  # noqa: N802, RUF100
        """Set supported connection types (camelCase version for protocol compatibility)."""
        new_types: list[str] = []
        if value is not None:
            new_types.extend(str(t).lower() for t in value)
        self._connection_types = new_types


class MessageFactory:
    """Factory class for creating standard Bayeux protocol messages.

    This class provides static methods for creating properly formatted
    messages for each Bayeux protocol operation.

    Example:
    -------
        >>> msg = MessageFactory.handshake({"auth": {"token": "secret"}})
        >>> connect = MessageFactory.connect("client123", "websocket")

    """

    _current_operation: str | None = None

    @staticmethod
    def handshake(ext: dict[str, Any] | None = None) -> Message:
        """Create a handshake message according to Bayeux protocol.

        Args:
        ----
            ext: Optional extension data

        Returns:
        -------
            Message: Handshake message

        """
        return Message(
            channel="/meta/handshake",
            version="1.0",
            supported_connection_types=["websocket", "long-polling"],
            ext=ext,
        )

    @staticmethod
    def connect(client_id: str, connection_type: str = "websocket") -> Message:
        """Create a connect message according to Bayeux protocol."""
        return Message(
            channel="/meta/connect",
            client_id=client_id,
            connection_type=connection_type,
        )

    @staticmethod
    def disconnect(client_id: str) -> Message:
        """Create a disconnect message according to Bayeux protocol."""
        return Message(channel="/meta/disconnect", client_id=client_id)

    @staticmethod
    def subscribe(client_id: str, subscription: str) -> Message:
        """Create a subscribe message according to Bayeux protocol."""
        return Message(
            channel="/meta/subscribe", client_id=client_id, subscription=subscription
        )

    @staticmethod
    def unsubscribe(client_id: str, subscription: str) -> Message:
        """Create an unsubscribe message according to Bayeux protocol."""
        return Message(
            channel="/meta/unsubscribe", client_id=client_id, subscription=subscription
        )

    @staticmethod
    def publish(
        channel: str,
        data: str | int | bool | dict[str, Any] | list[str] | None,
        client_id: str,
    ) -> Message:
        """Create a publish message according to Bayeux protocol."""
        if channel.startswith("/meta/"):
            error_msg = (
                "Cannot subscribe to service channels"
                if MessageFactory._current_operation == "subscribe"
                else "Cannot publish to service channels"
            )
            raise FayeError(error_msg)
        return Message(channel=channel, data=data, client_id=client_id)
