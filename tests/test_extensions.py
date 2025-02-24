"""Test extension functionality."""

import pytest
from unittest.mock import AsyncMock

from faye.extensions import Extension
from faye.protocol import Message


@pytest.fixture
def extension():
    """Create test extension."""
    return Extension()


@pytest.mark.asyncio
async def test_extension_outgoing():
    """Test extension outgoing message processing."""
    ext = Extension()
    message = Message("/test/channel")
    processed = await ext.process_outgoing(message)
    assert processed == message


@pytest.mark.asyncio
async def test_extension_incoming():
    """Test extension incoming message processing."""
    ext = Extension()
    message = Message("/test/channel")
    processed = await ext.process_incoming(message)
    assert processed == message


@pytest.mark.asyncio
async def test_extension_added():
    """Test extension added callback."""
    ext = Extension()
    client = AsyncMock()
    await ext.added(client)
    # Base extension doesn't do anything in added


@pytest.mark.asyncio
async def test_extension_removed():
    """Test extension removed callback."""
    ext = Extension()
    client = AsyncMock()
    await ext.removed(client)
    # Base extension doesn't do anything in removed


@pytest.mark.asyncio
async def test_extension_outgoing_callback():
    """Test extension outgoing with callback."""
    ext = Extension()
    message = Message("/test/channel")
    callback = AsyncMock()
    await ext.outgoing(message, callback)
    callback.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_extension_incoming_callback():
    """Test extension incoming with callback."""
    ext = Extension()
    message = Message("/test/channel")
    callback = AsyncMock()
    await ext.incoming(message, callback)
    callback.assert_called_once_with(message)
