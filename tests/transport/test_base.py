from typing import Any
from unittest.mock import AsyncMock

import pytest
from faye.exceptions import TransportError
from faye.protocol import Message
from faye.transport import Transport


class DummyTransport(Transport):
    """Dummy transport for testing base class functionality."""

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send(self, message: dict[str, Any]) -> Message:
        if not self._connected:
            raise TransportError("Not connected")
        return Message(channel="/test", successful=True)

    async def set_message_callback(self, callback):
        """Set callback for incoming messages."""
        self._message_callback = callback


@pytest.fixture
def transport():
    return DummyTransport("http://example.com")


@pytest.mark.asyncio
async def test_message_callback(transport):
    """Test message callback handling."""
    callback = AsyncMock()
    message = Message(channel="/test", data="test")

    await transport.set_message_callback(callback)
    await transport.handle_message(message)

    callback.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_message_callback_error(transport):
    """Test error handling in message callback."""

    async def error_callback(message):
        raise ValueError("Test error")

    await transport.set_message_callback(error_callback)

    with pytest.raises(TransportError, match="Message callback error: Test error"):
        await transport.handle_message(Message(channel="/test"))


def test_connected_property(transport):
    """Test connected property reflects internal state."""
    assert not transport.connected
    transport._connected = True
    assert transport.connected
