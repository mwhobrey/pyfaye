from typing import Any
from unittest.mock import AsyncMock

import pytest
from faye.client import FayeClient
from faye.extensions.base import Extension
from faye.protocol import Message


@pytest.fixture
def test_extension():
    """Create a test extension instance."""

    class TestExtension(Extension):
        def __init__(self):
            self.outgoing_called = False
            self.incoming_called = False
            self.ext_data = {"test": "data"}

        async def outgoing(self, message: Message) -> Message | None:
            self.outgoing_called = True
            self.add_ext(message)
            return message

        async def incoming(self, message: Message) -> Message | None:
            self.incoming_called = True
            return message

        def get_ext(self) -> dict[str, Any]:
            return self.ext_data

    return TestExtension()


@pytest.mark.asyncio
async def test_extension_pipeline(test_extension):
    """Test extension processing pipeline."""
    client = FayeClient("http://example.com/faye")
    client.add_extension(test_extension)

    # Setup mock transport
    client._transport = AsyncMock()
    client._transport.send.return_value = Message(channel="/test", successful=True)

    # Send message through pipeline
    message = Message(channel="/test", data="test")
    response = await client.send(message)

    assert test_extension.outgoing_called
    assert test_extension.incoming_called
    assert message.ext == test_extension.ext_data
    assert response.successful


@pytest.fixture
def test_extensions():
    """Create multiple test extension instances."""

    class TestExtension(Extension):
        def __init__(self):
            self.outgoing_called = False
            self.incoming_called = False
            self.ext_data = {"test": "data"}

        async def outgoing(self, message: Message) -> Message | None:
            self.outgoing_called = True
            self.add_ext(message)
            return message

        async def incoming(self, message: Message) -> Message | None:
            self.incoming_called = True
            return message

        def get_ext(self) -> dict[str, Any]:
            return self.ext_data

    return [TestExtension() for _ in range(3)]


@pytest.mark.asyncio
async def test_multiple_extensions(test_extensions):
    """Test multiple extensions processing in order."""
    client = FayeClient("http://example.com/faye")

    # Add multiple extensions
    for ext in test_extensions:
        client.add_extension(ext)

    message = Message(channel="/test", data="test")
    await client._process_outgoing(message)

    # Verify extensions were called in order
    for ext in test_extensions:
        assert ext.outgoing_called
