"""Base extension class for Faye client."""

import logging
from abc import ABC, abstractmethod
from typing import Any, TypeVar, Generic, Callable, Awaitable, Sequence, Optional, cast

from ..protocol import Message

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Extension(Generic[T]):
    """Base extension class following the official Faye protocol."""

    def __init__(self) -> None:
        """Initialize extension."""
        self._extensions: Sequence[Extension[T]] = []

    @abstractmethod
    def outgoing(
        self, message: Optional[Message], request: Message | None = None
    ) -> Optional[Message]:
        """Process outgoing message."""
        pass

    @abstractmethod
    def incoming(
        self, message: Optional[Message], request: Message | None = None
    ) -> Optional[Message]:
        """Process incoming message."""
        pass

    async def added(self) -> None:
        """Called when extension is added to client."""
        pass

    async def removed(self) -> None:
        """Called when extension is removed from client."""
        pass

    async def pipe_through(
        self,
        stage: str,
        message: Message,
        request: Any | None = None,
        callback: Callable[[Message], Awaitable[None]] | None = None,
    ) -> Message | None:
        """Process message through extension pipeline.

        Args:
            stage: Pipeline stage ('incoming' or 'outgoing')
            message: Message being processed
            request: Original request (for incoming messages)
            callback: Continuation callback for pipeline

        Returns:
            Processed message or None to halt pipeline
        """
        try:
            method = getattr(self, stage)
            result = method(message, request)

            # Handle both sync and async results
            if hasattr(result, "__await__"):
                result = await result

            if result is not None and callback is not None:
                await callback(result)
            return result

        except Exception as e:
            logger.error(f"Extension error: {e}")
            if callback is not None:
                await callback(message)
            return message

    async def process_outgoing(self, message: Message) -> Message | None:
        """Process outgoing message."""
        return message

    async def process_incoming(self, message: Message) -> Message | None:
        """Process incoming message."""
        return message

    def add_ext(self, message: Message) -> None:
        """Add extension data to message.

        Args:
            message: Message to add extension data to
        """
        if not message.ext:
            message.ext = {}
        message.ext.update(self.get_ext())

    def get_ext(self) -> dict[str, Any]:
        """Get extension data for messages.

        Returns:
            Extension data to add to message ext field
        """
        return {}

    async def pipe_through_extensions(
        self, message: Optional[Message], stage: str
    ) -> Optional[Message]:
        """Pipe a message through the extension pipeline."""
        logger.debug(f"{stage}: {message}")

        if not self._extensions:
            return message

        extensions = list(self._extensions)

        async def pipe(msg: Optional[Message], ext_idx: int) -> Optional[Message]:
            if ext_idx >= len(extensions):
                return msg

            extension = extensions[ext_idx]
            stage_func = getattr(extension, stage)

            processed = await stage_func(msg)
            if processed is None:
                return None

            return await pipe(processed, ext_idx + 1)

        return await pipe(message, 0)
