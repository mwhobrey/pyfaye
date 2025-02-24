"""Retry extension for Faye client."""

from typing import Any, Optional

from ..protocol import Message
from .base import Extension


class RetryExtension(Extension):
    """Extension for handling message retry logic."""

    def __init__(self, max_attempts: int = 3, interval: float = 1.0) -> None:
        """Initialize retry extension.

        Args:
            max_attempts: Maximum retry attempts (default: 3)
            interval: Base interval between retries in seconds (default: 1.0)
        """
        self.max_attempts = max_attempts
        self.interval = interval
        self._attempts: dict[str, int] = {}

    def outgoing(
        self, message: Message, request: Optional[Message] = None
    ) -> Optional[Message]:
        """Handle outgoing message retries.

        Args:
            message: Message to process
            request: Original request (unused)

        Returns:
            Processed message or None to halt retry
        """
        # Don't retry handshake or meta messages
        if message.channel.startswith("/meta/"):
            return message

        if message.id not in self._attempts:
            self._attempts[message.id] = 1
        else:
            self._attempts[message.id] += 1

        if self._attempts[message.id] > self.max_attempts:
            return None

        if not message.ext:
            message.ext = {}
        message.ext["retry"] = {
            "attempt": str(self._attempts[message.id]),
            "max": str(self.max_attempts),
            "interval": str(int(self.interval * 1000)),  # Convert to ms
        }
        return message

    def incoming(self, message: Message, request: Optional[Message] = None) -> Message:
        """Handle retry responses.

        Args:
            message: Response message
            request: Original request

        Returns:
            Processed message
        """
        if message.successful:
            if message.id in self._attempts:
                del self._attempts[message.id]
        elif message.error:
            # Check if error is retryable
            error_str = str(message.error).lower()
            if any(x in error_str for x in ["timeout", "connection", "unavailable"]):
                return message
            # Non-retryable error, clear attempts
            if message.id in self._attempts:
                del self._attempts[message.id]
        return message
