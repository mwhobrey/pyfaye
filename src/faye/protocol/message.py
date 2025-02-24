"""Message implementation following official Faye protocol."""

from dataclasses import dataclass, field
from typing import Any, ClassVar
from uuid import uuid4


@dataclass
class Message:
    """A Bayeux protocol message following official Faye implementation.

    This class represents a message in the Bayeux protocol, with support for all standard
    message types (handshake, connect, subscribe, etc.) and fields.

    Attributes:
    ----------
        Required fields:
            channel (str): The channel this message is for
            id (str): Unique message identifier

        Optional fields:
            client_id (str | None): Client identifier from handshake
            data (dict[str, Any] | None): Message payload
            error (str | None): Error message if any
            successful (bool | None): Whether operation was successful
            subscription (str | None): Channel being subscribed/unsubscribed
            advice (dict[str, Any] | None): Server connection advice
            ext (dict[str, Any] | None): Extension data
            version (str): Protocol version
            minimum_version (str): Minimum supported version
            connection_type (str | None): Transport type being used

        Protocol constants:
            HANDSHAKE (str): Meta channel for handshake
            CONNECT (str): Meta channel for connect
            SUBSCRIBE (str): Meta channel for subscribe
            UNSUBSCRIBE (str): Meta channel for unsubscribe
            DISCONNECT (str): Meta channel for disconnect

        Error codes:
            ERROR_CODES (dict[str, str]): Mapping of numeric codes to error types,
                                        matching the Node.js client implementation

    """

    # Required fields
    channel: str
    id: str = field(default_factory=lambda: str(uuid4()))

    # Optional fields with defaults
    client_id: str | None = None
    data: dict[str, Any] | None = None
    error: str | None = None
    successful: bool | None = None
    subscription: str | None = None
    advice: dict[str, Any] | None = None
    ext: dict[str, Any] | None = None
    version: str = "1.0"
    minimum_version: str = "1.0"
    connection_type: str | None = None
    _connection_types: list[str] = field(default_factory=list)

    # Protocol constants
    HANDSHAKE: ClassVar[str] = "/meta/handshake"
    CONNECT: ClassVar[str] = "/meta/connect"
    SUBSCRIBE: ClassVar[str] = "/meta/subscribe"
    UNSUBSCRIBE: ClassVar[str] = "/meta/unsubscribe"
    DISCONNECT: ClassVar[str] = "/meta/disconnect"

    # Error codes matching Node.js client
    ERROR_CODES: ClassVar[dict[str, str]] = {
        "401": "unauthorized",
        "402": "client_unknown",
        "403": "forbidden",
        "404": "unknown_channel",
        "405": "invalid_channel",
        "406": "unsupported",
        "407": "invalid_message",
        "408": "invalid_version",
        "409": "connection_failed",
        "410": "connection_closed",
    }

    def __init__(
        self,
        channel: str,
        client_id: str | None = None,
        data: dict[str, Any] | str | None = None,
        error: str | None = None,
        ext: dict[str, Any] | None = None,
        message_id: str | None = None,
        version: str | None = None,
        minimum_version: str | None = None,
        supported_connection_types: list[str] | None = None,
        connection_type: str | None = None,
        subscription: str | None = None,
        successful: bool | None = None,
        advice: dict[str, Any] | None = None,
    ) -> None:
        """Initialize message with Bayeux protocol fields."""
        self.channel = channel
        self.client_id = client_id
        self.data = data if isinstance(data, dict | None) else {"message": data}
        self.error = error
        self.ext = self._normalize_ext(ext) if ext else None
        self.id = message_id or str(uuid4())
        self.version = version or "1.0"
        self.minimum_version = minimum_version or "1.0"
        self._connection_types = []
        if supported_connection_types:
            self.supported_connection_types = supported_connection_types
        self.connection_type = connection_type
        self.subscription = subscription
        self.successful = successful
        self.advice = advice

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """Create message from dictionary, handling camelCase conversion."""
        converted = {}
        for key, value in data.items():
            if key == "clientId":
                converted["client_id"] = value
            elif key == "connectionType":
                converted["connection_type"] = value
            elif key == "minimumVersion":
                converted["minimum_version"] = value
            elif key == "supportedConnectionTypes":
                converted["supported_connection_types"] = value
            elif key == "id":
                converted["message_id"] = value
            else:
                converted[key] = value

        channel = converted.pop("channel")
        data_value = converted.pop("data", None)
        return cls(channel=channel, data=data_value, **converted)

    def _build_base_dict(self) -> dict[str, Any]:
        """Build base dictionary with required fields."""
        result: dict[str, Any] = {"channel": self.channel}
        return result

    def _add_optional_fields(self, result: dict[str, Any]) -> None:
        """Add optional fields to the dictionary."""
        if self.client_id is not None:
            result["clientId"] = self.client_id
        if self.data is not None:
            result["data"] = self.data
        if self.error is not None:
            result["error"] = self.error
        if self.ext is not None:
            result["ext"] = self.ext
        if self.id is not None:
            result["id"] = self.id

    def _add_version_fields(self, result: dict[str, Any]) -> None:
        """Add version-related fields to the dictionary."""
        if self.version is not None:
            result["version"] = self.version
        if self.minimum_version is not None:
            result["minimumVersion"] = self.minimum_version
        if self._connection_types:
            result["supportedConnectionTypes"] = self._connection_types

    def _add_connection_fields(self, result: dict[str, Any]) -> None:
        """Add connection-related fields to the dictionary."""
        if self.connection_type is not None:
            result["connectionType"] = self.connection_type
        if self.subscription is not None:
            result["subscription"] = self.subscription
        if self.successful is not None:
            result["successful"] = self.successful
        if self.advice is not None:
            result["advice"] = self.advice

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary using protocol field names."""
        result = self._build_base_dict()
        self._add_optional_fields(result)
        self._add_version_fields(result)
        self._add_connection_fields(result)
        return result

    # Message type checks
    @property
    def is_handshake(self) -> bool:
        """Check if handshake message."""
        return self.channel == self.HANDSHAKE

    @property
    def is_connect(self) -> bool:
        """Check if connect message."""
        return self.channel == self.CONNECT

    @property
    def is_subscribe(self) -> bool:
        """Check if subscribe message."""
        return self.channel == self.SUBSCRIBE

    @property
    def is_unsubscribe(self) -> bool:
        """Check if unsubscribe message."""
        return self.channel == self.UNSUBSCRIBE

    @property
    def is_disconnect(self) -> bool:
        """Check if disconnect message."""
        return self.channel == self.DISCONNECT

    @property
    def is_meta(self) -> bool:
        """Check if meta channel message."""
        return self.channel.startswith("/meta/")

    @property
    def is_service(self) -> bool:
        """Check if service channel message."""
        return self.channel.startswith("/service/")

    @property
    def error_type(self) -> str | None:
        """Get error type from error code or message."""
        if not self.error:
            return None

        # Check for error codes
        for code, error_type in self.ERROR_CODES.items():
            if code in str(self.error):
                return error_type

        # Check error message text
        error_lower = str(self.error).lower()
        if "unauthorized" in error_lower:
            return "unauthorized"
        if "unknown" in error_lower and "client" in error_lower:
            return "client_unknown"
        if "version" in error_lower:
            return "invalid_version"
        if "connection" in error_lower and "closed" in error_lower:
            return "connection_closed"

        return "unknown"

    @property
    def is_error(self) -> bool:
        """Check if message represents an error."""
        return bool(self.error) or self.successful is False

    def validate(self) -> list[str]:
        """Validate message according to Bayeux protocol."""
        errors = []

        if not self.channel:
            errors.append("Message must have a channel")
        elif not self.channel.startswith("/"):
            errors.append("Channel must start with /")

        # Meta message validation
        if self.is_meta:
            if not self.id:
                errors.append("Meta messages must have an id")
            if not self.is_handshake and not self.is_disconnect and not self.client_id:
                errors.append(
                    "Message must have a client_id (except for handshake/disconnect)",
                )

        # Subscription validation
        if (self.is_subscribe or self.is_unsubscribe) and not self.subscription:
            errors.append(f"{self.channel} message must have a subscription field")

        # Connect message validation
        if self.is_connect and not self.connection_type:
            errors.append("Connect messages must have a connection_type")

        # Publish message validation
        if not self.is_meta and not self.is_service and self.data is None:
            errors.append("Publish messages must have a data field")

        return errors

    def matches(self, pattern: str) -> bool:
        """Check if channel matches subscription pattern."""
        pattern = self._normalize_channel(pattern)
        channel = self._normalize_channel(self.channel)

        if not pattern.startswith("/"):
            return False

        pattern_parts = pattern.split("/")
        channel_parts = channel.split("/")

        if "**" in pattern_parts:
            # Handle globbing
            glob_index = pattern_parts.index("**")
            if not self._match_parts(
                pattern_parts[:glob_index],
                channel_parts[:glob_index],
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
            p in {"*", c} for p, c in zip(pattern_parts, channel_parts, strict=False)
        )

    @property
    def supported_connection_types(self) -> list[str]:
        """Get supported connection types."""
        return self._connection_types

    @supported_connection_types.setter
    def supported_connection_types(self, value: list[str] | None) -> None:
        """Set supported connection types."""
        self._connection_types = [str(t).lower() for t in (value or [])]

    # Protocol compatibility properties
    @property
    def supportedConnectionTypes(self) -> list[str]:  # noqa: N802
        """Get supported connection types (camelCase for protocol)."""
        return self._connection_types

    @supportedConnectionTypes.setter
    def supportedConnectionTypes(self, value: list[str] | None) -> None:  # noqa: N802
        """Set supported connection types (camelCase for protocol)."""
        self._connection_types = [str(t).lower() for t in (value or [])]

    @staticmethod
    def _normalize_channel(channel: str) -> str:
        """Normalize channel name."""
        while "//" in channel:
            channel = channel.replace("//", "/")
        if len(channel) > 1 and channel.endswith("/"):
            channel = channel.rstrip("/")
        return channel

    @staticmethod
    def _normalize_ext(ext: dict[str, Any]) -> dict[str, Any]:
        """Normalize extension data types."""
        normalized: dict[str, Any] = {}
        for key, value in ext.items():
            if isinstance(value, dict):
                normalized[key] = {
                    str(k): str(v) if v is not None else "" for k, v in value.items()
                }
            else:
                normalized[key] = str(value) if value is not None else ""
        return normalized

    # Factory methods matching Node.js client
    @classmethod
    def handshake(cls, ext: dict[str, Any] | None = None) -> "Message":
        """Create handshake message.

        Args:
        ----
            ext: Optional extension data to include

        Returns:
        -------
            Message: Handshake message ready to send

        """
        return cls(
            channel=cls.HANDSHAKE,
            version="1.0",
            minimum_version="1.0",
            supported_connection_types=["websocket", "long-polling"],
            ext=ext,
        )

    @classmethod
    def connect(cls, client_id: str, connection_type: str = "websocket") -> "Message":
        """Create connect message.

        Args:
        ----
            client_id: Client identifier from handshake
            connection_type: Transport type being used

        Returns:
        -------
            Message: Connect message ready to send

        """
        return cls(
            channel=cls.CONNECT,
            client_id=client_id,
            connection_type=connection_type,
        )

    @classmethod
    def disconnect(cls, client_id: str) -> "Message":
        """Create disconnect message.

        Args:
        ----
            client_id: Client identifier from handshake

        Returns:
        -------
            Message: Disconnect message ready to send

        """
        return cls(channel=cls.DISCONNECT, client_id=client_id)

    @classmethod
    def subscribe(cls, client_id: str, subscription: str) -> "Message":
        """Create subscribe message.

        Args:
        ----
            client_id: Client identifier from handshake
            subscription: Channel to subscribe to

        Returns:
        -------
            Message: Subscribe message ready to send

        """
        return cls(
            channel=cls.SUBSCRIBE,
            client_id=client_id,
            subscription=subscription,
        )

    @classmethod
    def unsubscribe(cls, client_id: str, subscription: str) -> "Message":
        """Create unsubscribe message.

        Args:
        ----
            client_id: Client identifier from handshake
            subscription: Channel to unsubscribe from

        Returns:
        -------
            Message: Unsubscribe message ready to send

        """
        return cls(
            channel=cls.UNSUBSCRIBE,
            client_id=client_id,
            subscription=subscription,
        )

    @classmethod
    def publish(cls, channel: str, data: dict[str, Any], client_id: str) -> "Message":
        """Create publish message.

        Args:
        ----
            channel: Channel to publish to
            data: Message data to publish
            client_id: Client identifier from handshake

        Returns:
        -------
            Message: Publish message ready to send

        """
        return cls(channel=channel, data=data, client_id=client_id)
