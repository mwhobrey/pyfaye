from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio  # Import pytest_asyncio for async fixtures
from faye import FayeClient
from faye.extensions import Extension
from faye.protocol import Message


@pytest.fixture
def mock_response():
    """Shared mock response fixture."""
    response = AsyncMock()
    response.raise_for_status = Mock()
    response.json = AsyncMock()
    return response


@pytest.fixture
def client():
    return FayeClient("http://example.com/faye")


@pytest.fixture
def mock_transport():
    transport = AsyncMock()
    transport.connected = False
    transport.connect = AsyncMock()
    transport.disconnect = AsyncMock()
    transport.send = AsyncMock()
    return transport


@pytest.fixture
async def connected_client(client, mock_transport):
    client._transport = mock_transport
    client._transport.connected = True
    client._protocol.client_id = "client123"
    client._protocol._handshaken = True
    return client


@pytest.fixture
def test_extension():
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


@pytest_asyncio.fixture(scope="function")
async def mock_session():
    session = AsyncMock()
    session.ws_connect = AsyncMock()
    session.close = AsyncMock()
    # Setup default successful response
    session.ws_connect.side_effect = None
    return session


# Configure pytest-asyncio
def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")

    # Set asyncio mode to "strict"
    config.option.asyncio_mode = "strict"
