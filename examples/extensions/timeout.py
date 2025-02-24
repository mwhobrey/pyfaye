"""Timeout extension for Faye client."""

from typing import Any, Optional

from ..protocol import Message
from .base import Extension


class TimeoutExtension(Extension):
    """Extension for managing message timeouts."""

    def __init__(self, timeout: float = 60.0) -> None:
        """Initialize timeout extension.

        Args:
            timeout: Timeout in seconds (default: 60)
        """
        self.timeout = timeout

    def outgoing(self, message: Message, request: Optional[Message] = None) -> Message:
        """Add timeout to outgoing messages.

        Args:
            message: Message to add timeout to
            request: Original request (unused)

        Returns:
            Message with timeout added
        """
        if not message.ext:
            message.ext = {}
        message.ext["timeout"] = str(int(self.timeout * 1000))  # Convert to ms
        return message

    def incoming(self, message: Message, request: Optional[Message] = None) -> Message:
        """Process timeout responses.

        Args:
            message: Response message
            request: Original request

        Returns:
            Processed message
        """
        if message.ext and "timeout" in message.ext:
            try:
                timeout = int(message.ext["timeout"])
                self.timeout = timeout / 1000  # Convert to seconds
            except (ValueError, TypeError):
                pass
        return message

    def process_outgoing(self, message: Message) -> Message:
        """Process outgoing message."""
        if message.ext and isinstance(message.ext, dict):
            if "timeout" in message.ext:
                try:
                    timeout = int(str(message.ext["timeout"]))  # Convert to str first
                    self.timeout = timeout / 1000  # Convert to seconds
                except (ValueError, TypeError):
                    pass
        return message
