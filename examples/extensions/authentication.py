from typing import Any

from faye.exceptions import FayeError
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

    def outgoing(
        self, message: Message, request: Message | None = None
    ) -> Message | None:
        """Add authentication token to outgoing handshake messages.

        Adds the auth token to the message's ext field only for handshake
        messages. All other messages pass through unmodified.

        Args:
        ----
            message: The outgoing message
            request: The request message (optional)

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

    async def process_incoming(self, message: Message) -> Message | None:
        """Process incoming messages and check for authentication errors.

        Args:
            message: Message to process

        Returns:
            Processed message or None if rejected

        Raises:
            FayeError: If the message contains an auth_error (401)
        """
        if message.ext and "auth_error" in message.ext:
            raise FayeError(401, ["auth"], message.ext["auth_error"])  # Unauthorized
        return message

    def get_ext(self) -> dict[str, Any]:
        """Get authentication extension data.

        Returns
        -------
            Dict containing the auth token in the format:
            {"auth": {"token": "your-token"}}

        """
        return {"auth": {"token": self.token}}
