"""Test base transport functionality."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from faye.exceptions import TransportError
from faye.protocol import Message
from faye.transport import Transport


class DummyTransport(Transport):
    """Dummy transport for testing."""

    async def _connect(self):
        """Connect the transport."""
        pass

    async def _disconnect(self):
        """Disconnect the transport."""
        pass

    async def _ping(self):
        """Send a ping message."""
        pass

    async def _send(self, message: Message | list[Message]) -> Message | list[Message]:
        """Send a message."""
        if isinstance(message, list):
            return [msg if isinstance(msg, Message) else Message.from_dict(msg) for msg in message]
        return message if isinstance(message, Message) else Message.from_dict(message)


@pytest.fixture
def transport():
    """Create test transport."""
    return DummyTransport("http://example.com")


@pytest.mark.asyncio
async def test_message_callback():
    """Test message callback."""
    transport = DummyTransport("http://example.com")
    callback = AsyncMock()
    await transport.set_message_callback(callback)

    message = Message("/test/channel")
    await transport.handle_message(message)
    callback.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_message_callback_error():
    """Test message callback error handling."""
    transport = DummyTransport("http://example.com")
    callback = AsyncMock(side_effect=Exception("Test error"))
    await transport.set_message_callback(callback)

    message = Message("/test/channel")
    with pytest.raises(TransportError, match="Message callback error: Test error"):
        await transport.handle_message(message)


def test_connected_property():
    """Test connected property."""
    transport = DummyTransport("http://example.com")
    assert not transport.connected  # Should start disconnected
    transport._state = transport.state.CONNECTED
    assert transport.connected  # Should be connected after setting state
