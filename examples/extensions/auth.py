"""Authentication extension for Faye client."""

from typing import Any, Optional

from ..exceptions import FayeError
from ..protocol import Message
from .base import Extension


class AuthenticationExtension(Extension):
    """Extension for adding authentication tokens to messages."""

    def __init__(self, token: str, token_key: str = "token") -> None:
        """Initialize authentication extension.

        Args:
            token: Authentication token
            token_key: Key to use in ext field
        """
        self.token = token
        self.token_key = token_key

    def outgoing(self, message: Message, request: Optional[Message] = None) -> Message:
        """Add auth token to outgoing messages.

        Args:
            message: Message to authenticate
            request: Original request (unused)

        Returns:
            Message with auth token added
        """
        if not message.ext:
            message.ext = {}
        if "auth" not in message.ext:
            message.ext["auth"] = {}

        # Ensure ext.auth is a dict
        if isinstance(message.ext["auth"], str):
            message.ext["auth"] = {}

        message.ext["auth"][self.token_key] = self.token
        return message

    def incoming(self, message: Message, request: Optional[Message] = None) -> Message:
        """Process auth responses.

        Args:
            message: Response message
            request: Original request

        Returns:
            Processed message

        Raises:
            FayeError: If authentication failed (401)
        """
        if message.ext:
            auth = message.ext.get("auth")
            if auth is False or (isinstance(auth, dict) and auth.get("failed")):
                details = auth if isinstance(auth, dict) else None
                raise FayeError(
                    401,  # Unauthorized
                    ["auth", self.token],
                    (
                        f"Authentication failed: {details}"
                        if details
                        else "Authentication failed"
                    ),
                )
        return message
