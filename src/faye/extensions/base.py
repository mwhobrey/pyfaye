from abc import ABC, abstractmethod
from typing import Any

from faye.protocol import Message


class Extension(ABC):
    """Base class for implementing Faye protocol extensions.

    Extensions can modify or intercept messages as they flow through the client.
    Implement outgoing() and incoming() methods to process messages in both directions.

    Example:
    -------
        >>> class LoggingExtension(Extension):
        ...     async def outgoing(self, message: Message) -> Optional[Message]:
        ...         print(f"Sending: {message}")
        ...         return message
        ...
        ...     async def incoming(self, message: Message) -> Optional[Message]:
        ...         print(f"Received: {message}")
        ...         return message

    """

    @abstractmethod
    async def outgoing(self, message: Message) -> Message | None:
        """Process outgoing messages before they are sent.

        Args:
        ----
            message: The message being sent

        Returns:
        -------
            Message: The modified message to send
            None: To halt message processing

        Note:
        ----
            Return None to prevent the message from being sent.
            Any exception will be logged but allow message to proceed.

        """
        pass

    @abstractmethod
    async def incoming(self, message: Message) -> Message | None:
        """Process incoming messages as they are received.

        Args:
        ----
            message: The received message

        Returns:
        -------
            Message: The modified message to process
            None: To halt message processing

        Note:
        ----
            Return None to prevent further processing of the message.
            Any exception will be logged but allow message to proceed.

        """
        pass

    def add_ext(self, message: Message) -> None:
        """Add extension data to message's ext field.

        Args:
        ----
            message: The message to add extension data to

        Note:
        ----
            Creates ext dict if it doesn't exist.
            Updates existing ext data with extension's data.

        """
        if not message.ext:
            message.ext = {}
        message.ext.update(self.get_ext())

    def get_ext(self) -> dict[str, Any]:
        """Get extension data to be included in messages.

        Returns:
        -------
            Dict containing extension data to add to message ext field

        Note:
        ----
            Override this method to provide custom extension data.
            Default implementation returns empty dict.

        """
        return {}
