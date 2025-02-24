"""Logging extension for Faye client."""

import logging
from typing import Any

from .base import Extension
from ..protocol import Message

logger = logging.getLogger(__name__)


class LoggingExtension(Extension):
    """Extension for logging messages."""

    def __init__(self, logger: Any = None) -> None:
        """Initialize logging extension."""
        self.logger = logger or logging.getLogger(__name__)

    async def outgoing(
        self, message: Message, request: Message | None = None
    ) -> Message | None:
        """Log and process outgoing message."""
        self.logger.debug(f"Outgoing: {message.to_dict()}")
        return message

    async def incoming(
        self, message: Message, request: Message | None = None
    ) -> Message | None:
        """Log and process incoming message."""
        self.logger.debug(f"Incoming: {message.to_dict()}")
        return message
