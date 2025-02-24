"""Faye client exception classes following the official Faye protocol error codes.

This module provides a comprehensive set of exceptions and error codes that match
the official Faye protocol specification. It includes both protocol-level and
transport-level errors.
"""

from enum import Enum


class ErrorCode(Enum):
    """Error codes for Faye client.

    These error codes match the official Faye protocol specification and are used
    to provide consistent error handling across different implementations.

    Protocol Errors (300-399):
        VERSION_MISMATCH (300): Protocol version mismatch
        CONNTYPE_MISMATCH (301): Unsupported connection type
        EXT_MISMATCH (302): Extension mismatch

    Client Errors (400-499):
        BAD_REQUEST (400): Malformed request
        CLIENT_UNKNOWN (401): Unknown client ID
        PARAMETER_MISSING (402): Required parameter missing
        CHANNEL_FORBIDDEN (403): Channel access denied
        CHANNEL_UNKNOWN (404): Channel not found
        CHANNEL_INVALID (405): Invalid channel name
        EXT_UNKNOWN (406): Unknown extension
        PUBLISH_FAILED (407): Message publish failed
        TIMEOUT_ERROR (408): Operation timed out

    Server Errors (500-599):
        SERVER_ERROR (500): Internal server error
        TRANSPORT_ERROR (501): Transport-level error

    Connection Errors (600-699):
        CONNECTION_FAILED (600): Connection establishment failed
        SUBSCRIBE_FAILED (601): Subscription failed
        UNSUBSCRIBE_FAILED (602): Unsubscribe failed
        HANDSHAKE_FAILED (603): Handshake failed
    """

    VERSION_MISMATCH = 300
    CONNTYPE_MISMATCH = 301
    EXT_MISMATCH = 302
    BAD_REQUEST = 400
    CLIENT_UNKNOWN = 401
    PARAMETER_MISSING = 402
    CHANNEL_FORBIDDEN = 403
    CHANNEL_UNKNOWN = 404
    CHANNEL_INVALID = 405
    EXT_UNKNOWN = 406
    PUBLISH_FAILED = 407
    TIMEOUT_ERROR = 408
    SERVER_ERROR = 500
    TRANSPORT_ERROR = 501
    CONNECTION_FAILED = 600
    SUBSCRIBE_FAILED = 601
    UNSUBSCRIBE_FAILED = 602
    HANDSHAKE_FAILED = 603
    MESSAGE_PROCESSING_ERROR = 706


class FayeError(Exception):
    """Base exception class for all Faye client errors."""

    def __init__(self, code: ErrorCode | int, context: list[str], message: str) -> None:
        """Initialize FayeError.

        Args:
        ----
            code: Error code (either ErrorCode enum or int)
            context: Error context
            message: Error message

        """
        super().__init__(message)
        self.code = code if isinstance(code, ErrorCode) else code
        self.context = context
        self.message = message

    def __str__(self) -> str:
        """Convert error to string format matching official client."""
        code_val = self.code.value if isinstance(self.code, ErrorCode) else self.code
        code_str = str(code_val)
        if self.context:
            code_str = f"{code_str}:{':'.join(self.context)}"
        return f"{code_str}:{self.message}"


class HandshakeError(FayeError):
    """Error during handshake."""

    def __init__(
        self,
        message: str,
        code: ErrorCode | int | None = None,
        context: list[str] | None = None,
    ) -> None:
        """Initialize HandshakeError.

        Args:
        ----
            message: Error message
            code: Error code (optional)
            context: Error context (optional)

        """
        super().__init__(code or ErrorCode.SERVER_ERROR, context or [], message)


class ProtocolError(FayeError):
    """Error in protocol."""

    def __init__(
        self,
        message: str,
        code: ErrorCode | int | None = None,
        context: list[str] | None = None,
    ) -> None:
        """Initialize ProtocolError.

        Args:
        ----
            message: Error message
            code: Error code (optional)
            context: Error context (optional)

        """
        super().__init__(code or ErrorCode.SERVER_ERROR, context or [], message)


class TransportError(FayeError):
    """Transport-specific error."""

    def __init__(self, message: str, *, is_timeout: bool = False) -> None:
        """Initialize transport error.

        Args:
        ----
            message: Error message
            is_timeout: Whether this is a timeout error

        """
        super().__init__(
            ErrorCode.TIMEOUT_ERROR if is_timeout else ErrorCode.TRANSPORT_ERROR,
            [],
            message,
        )
        self.timeout = is_timeout


def version_mismatch(*params: str | int) -> str:
    """Create version mismatch error.

    Args:
    ----
        *params: Error parameters

    Returns:
    -------
        str: Formatted error string

    """
    return str(
        FayeError(
            ErrorCode.VERSION_MISMATCH,
            list(map(str, params)),
            "Version mismatch",
        ),
    )


def conntype_mismatch(*params: str | int) -> str:
    """Create connection type mismatch error.

    Args:
    ----
        *params: Error parameters

    Returns:
    -------
        str: Formatted error string

    """
    return str(
        FayeError(
            ErrorCode.CONNTYPE_MISMATCH,
            list(map(str, params)),
            "Connection types not supported",
        ),
    )


def ext_mismatch(*params: str | int) -> str:
    """Create extension mismatch error.

    Args:
    ----
        *params: Error parameters

    Returns:
    -------
        str: Formatted error string

    """
    return str(
        FayeError(ErrorCode.EXT_MISMATCH, list(map(str, params)), "Extension mismatch"),
    )


def bad_request(*params: str | int) -> str:
    """Create bad request error.

    Args:
    ----
        *params: Error parameters

    Returns:
    -------
        str: Formatted error string

    """
    return str(FayeError(ErrorCode.BAD_REQUEST, list(map(str, params)), "Bad request"))


def client_unknown(*params: str | int) -> str:
    """Create unknown client error.

    Args:
    ----
        *params: Error parameters

    Returns:
    -------
        str: Formatted error string

    """
    return str(
        FayeError(ErrorCode.CLIENT_UNKNOWN, list(map(str, params)), "Unknown client"),
    )


def parameter_missing(*params: str | int) -> str:
    """Create missing parameter error.

    Args:
    ----
        *params: Error parameters

    Returns:
    -------
        str: Formatted error string

    """
    return str(
        FayeError(
            ErrorCode.PARAMETER_MISSING,
            list(map(str, params)),
            "Missing required parameter",
        ),
    )


def channel_forbidden(*params: str | int) -> str:
    """Create forbidden channel error.

    Args:
    ----
        *params: Error parameters

    Returns:
    -------
        str: Formatted error string

    """
    return str(
        FayeError(
            ErrorCode.CHANNEL_FORBIDDEN,
            list(map(str, params)),
            "Forbidden channel",
        ),
    )


def channel_unknown(*params: str | int) -> str:
    """Create unknown channel error.

    Args:
    ----
        *params: Error parameters

    Returns:
    -------
        str: Formatted error string

    """
    return str(
        FayeError(ErrorCode.CHANNEL_UNKNOWN, list(map(str, params)), "Unknown channel"),
    )


def channel_invalid(*params: str | int) -> str:
    """Create invalid channel error.

    Args:
    ----
        *params: Error parameters

    Returns:
    -------
        str: Formatted error string

    """
    return str(
        FayeError(ErrorCode.CHANNEL_INVALID, list(map(str, params)), "Invalid channel"),
    )


def ext_unknown(*params: str | int) -> str:
    """Create unknown extension error.

    Args:
    ----
        *params: Error parameters

    Returns:
    -------
        str: Formatted error string

    """
    return str(
        FayeError(ErrorCode.EXT_UNKNOWN, list(map(str, params)), "Unknown extension"),
    )


def publish_failed(*params: str | int) -> str:
    """Create publish failed error.

    Args:
    ----
        *params: Error parameters

    Returns:
    -------
        str: Formatted error string

    """
    return str(
        FayeError(
            ErrorCode.PUBLISH_FAILED,
            list(map(str, params)),
            "Failed to publish",
        ),
    )


def server_error(*params: str | int) -> str:
    """Create server error.

    Args:
    ----
        *params: Error parameters

    Returns:
    -------
        str: Formatted error string

    """
    return str(
        FayeError(
            ErrorCode.SERVER_ERROR,
            list(map(str, params)),
            "Internal server error",
        ),
    )


# Parse error string into FayeError object
def parse_error(error_str: str | None) -> FayeError:
    """Parse error string into FayeError object.

    Args:
    ----
        error_str: Error string in format "code:params:message"

    Returns:
    -------
        FayeError object

    """
    min_error_parts = 3

    if not error_str:
        return FayeError(ErrorCode.SERVER_ERROR, [], error_str or "")

    parts = error_str.split(":")
    if len(parts) < min_error_parts:
        return FayeError(ErrorCode.SERVER_ERROR, [], error_str)

    try:
        code = int(parts[0])
        context = parts[1].split(",") if parts[1] else []
        message = parts[2]
        return FayeError(code, context, message)
    except (ValueError, IndexError):
        return FayeError(ErrorCode.SERVER_ERROR, [], error_str)


__all__ = [
    "FayeError",
    "HandshakeError",
    "ProtocolError",
    "TransportError",
    "parse_error",
    "version_mismatch",
    "conntype_mismatch",
    "ext_mismatch",
    "bad_request",
    "client_unknown",
    "parameter_missing",
    "channel_forbidden",
    "channel_unknown",
    "channel_invalid",
    "ext_unknown",
    "publish_failed",
    "server_error",
]
