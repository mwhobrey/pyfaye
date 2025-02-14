from typing import Any

from faye.exceptions import AuthenticationError
from faye.protocol import Message

from .base import Extension


class AuthenticationExtension(Extension):
    """Extension for adding authentication tokens to Faye messages.

    This extension adds authentication tokens to handshake messages and
    handles authentication errors from the server. It implements the standard
    Faye authentication extension pattern.

    Args:
    ----
        token: The authentication token to use

    Example:
    -------
        >>> client = FayeClient("http://server.com/faye")
        >>> auth = AuthenticationExtension("your-auth-token")
        >>> client.add_extension(auth)
        >>> await client.connect()  # Token will be added to handshake

    Note:
    ----
        The token is only added to handshake messages to establish the initial
        authenticated connection. The server is expected to maintain the
        authentication state after successful handshake.

    """

    def __init__(self, token: str) -> None:
        """Initialize the authentication extension.

        Args:
        ----
            token: The authentication token to use for all connections

        """
        self.token = token

    async def outgoing(self, message: Message) -> Message:
        """Add authentication token to outgoing handshake messages.

        Adds the auth token to the message's ext field only for handshake
        messages. All other messages pass through unmodified.

        Args:
        ----
            message: The outgoing message

        Returns:
        -------
            Message: The message with auth token added (for handshake)
            or unmodified message (for all others)

        Note:
        ----
            The auth token is added in the format:
            {"ext": {"auth": {"token": "your-token"}}}

        """
        if message.channel == "/meta/handshake":  # Only add to handshake
            if message.ext is None:
                message.ext = {}
            message.ext["auth"] = {"token": self.token}
        return message

    async def incoming(self, message: Message) -> Message:
        """Handle authentication errors in incoming messages.

        Checks incoming messages for authentication errors and raises
        an AuthenticationError if one is found.

        Args:
        ----
            message: The incoming message

        Returns:
        -------
            Message: The unmodified message if no auth errors

        Raises:
        ------
            AuthenticationError: If the message contains an auth_error

        Note:
        ----
            Expects auth errors in the format:
            {"ext": {"auth_error": "error message"}}

        """
        if message.ext is None:
            return message
        if not message.successful and message.ext.get("auth_error"):
            raise AuthenticationError(message.ext["auth_error"])
        return message

    def get_ext(self) -> dict[str, Any]:
        """Get authentication extension data.

        Returns
        -------
            Dict containing the auth token in the format:
            {"auth": {"token": "your-token"}}

        """
        return {"auth": {"token": self.token}}
