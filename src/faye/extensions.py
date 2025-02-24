"""Extensions module for Faye client following the official Faye protocol."""

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

from .protocol import Message

logger = logging.getLogger(__name__)

T = TypeVar("T")
ExtensionCallback = Callable[[Message | None], Awaitable[Message | None]]


class FayeClient(Protocol):
    """Protocol defining the required interface for a Faye client."""

    async def add_extension(self, extension: "Extension") -> None:
        """Add an extension to the client."""
        ...

    async def remove_extension(self, extension: "Extension") -> None:
        """Remove an extension from the client."""
        ...


class Extension:
    """Base extension class following official Faye protocol."""

    async def added(self, client: FayeClient) -> None:
        """Add this extension to the client."""

    async def removed(self, client: FayeClient) -> None:
        """Remove this extension from the client."""

    async def process_outgoing(self, message: Message) -> Message | None:
        """Process outgoing message.

        Args:
        ----
            message: Message to process

        Returns:
        -------
            Processed message or None to halt pipeline

        """
        return message

    async def process_incoming(self, message: Message) -> Message | None:
        """Process incoming message.

        Args:
        ----
            message: Message to process

        Returns:
        -------
            Processed message or None to halt pipeline

        """
        return message

    async def outgoing(self, message: Message, callback: ExtensionCallback) -> None:
        """Process outgoing message with callback.

        This is used by the extension pipeline for chaining extensions.
        For simple extensions, override process_outgoing instead.
        """
        processed = await self.process_outgoing(message)
        if processed is not None:
            await callback(processed)

    async def incoming(self, message: Message, callback: ExtensionCallback) -> None:
        """Process incoming message with callback.

        This is used by the extension pipeline for chaining extensions.
        For simple extensions, override process_incoming instead.
        """
        processed = await self.process_incoming(message)
        if processed is not None:
            await callback(processed)


class Extensible:
    """Mixin class for adding extension support to clients."""

    def __init__(self) -> None:
        """Initialize extensible support."""
        self._extensions: list[Extension] = []

    async def add_extension(self, extension: Extension) -> None:
        """Add an extension to the pipeline.

        Args:
        ----
            extension: Extension instance to add

        """
        self._extensions.append(extension)
        await extension.added(self)

    async def remove_extension(self, extension: Extension) -> None:
        """Remove an extension from the pipeline.

        Args:
        ----
            extension: Extension instance to remove

        """
        if extension in self._extensions:
            self._extensions.remove(extension)
            await extension.removed(self)

    async def pipe_through_extensions(
        self,
        stage: str,
        message: Message,
        callback: Callable[[Message | None], Awaitable[T]],
    ) -> T:
        """Pipe message through extension pipeline.

        Args:
        ----
            stage: Pipeline stage ('incoming' or 'outgoing')
            message: Message to process
            callback: Final callback to call with processed message

        Returns:
        -------
            Result from callback

        """
        logger.debug(f"Passing through {stage} extensions: {message}")

        if not self._extensions:
            return await callback(message)

        # Create copy of extensions to avoid modification during iteration
        extensions = self._extensions.copy()

        async def pipe(msg: Message | None) -> T:
            if msg is None:
                return await callback(None)

            if not extensions:
                return await callback(msg)

            extension = extensions.pop(0)
            stage_fn = getattr(extension, stage, None)

            if not stage_fn:
                return await pipe(msg)

            async def next_extension(processed_msg: Message | None) -> T:
                return await pipe(processed_msg)

            await stage_fn(msg, next_extension)
            return await callback(msg)

        return await pipe(message)


class LoggingExtension(Extension):
    """Extension for logging messages."""

    def __init__(self, logger_instance: logging.Logger | None = None) -> None:
        """Initialize logging extension."""
        self.logger = logger_instance or logging.getLogger(__name__)

    async def incoming(self, message: Message, callback: ExtensionCallback) -> None:
        """Log and process incoming message."""
        self.logger.debug(f"Incoming: {message.to_dict()}")
        await callback(message)

    async def outgoing(self, message: Message, callback: ExtensionCallback) -> None:
        """Log and process outgoing message."""
        self.logger.debug(f"Outgoing: {message.to_dict()}")
        await callback(message)


class SigningExtension(Extension):
    """Extension for signing messages."""

    def __init__(self, token: str) -> None:
        """Initialize signing extension."""
        self.token = token

    async def outgoing(self, message: Message, callback: ExtensionCallback) -> None:
        """Sign outgoing message."""
        if not message.ext:
            message.ext = {}
        message.ext["token"] = self.token
        await callback(message)


__all__ = ["Extension", "Extensible", "LoggingExtension", "SigningExtension"]
