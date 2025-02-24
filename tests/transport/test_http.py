"""Test HTTP transport functionality."""

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from aiohttp import ClientError, ClientResponse, ClientSession
from faye.exceptions import TransportError
from faye.protocol import BayeuxProtocol, Message
from faye.transport import HttpTransport
from faye.transport.base import ConnectionState


@pytest_asyncio.fixture(scope="function")
async def transport():
    """Create test transport."""
    transport = HttpTransport("http://example.com/faye")
    transport._request_timeout = 30.0  # Set default timeout
    transport._protocol = BayeuxProtocol()  # Add protocol
    return transport


@pytest_asyncio.fixture
async def mock_session():
    """Create a mock session with proper async context manager behavior."""
    with (
        patch("aiohttp.client.ClientSession.__init__", return_value=None),
        patch(
            "aiohttp.connector.TCPConnector._resolve_host_with_throttle",
            new_callable=AsyncMock,
        ),
    ):
        session = AsyncMock(spec=ClientSession)
        session.closed = False

        # Setup default response
        response = AsyncMock(spec=ClientResponse)
        response.raise_for_status = Mock()
        response.json = AsyncMock(
            return_value=[{"channel": "/test", "successful": True}]
        )

        # Create a proper async context manager for post
        post_context = AsyncMock()
        post_context.__aenter__ = AsyncMock(return_value=response)
        post_context.__aexit__ = AsyncMock(return_value=None)

        # Setup post method
        session.post = Mock(return_value=post_context)
        session.close = AsyncMock()

        # Add context manager methods to session itself
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        # Setup connector
        connector = AsyncMock()
        connector.close = AsyncMock()
        session.connector = connector

        try:
            yield session
        finally:
            # Cleanup
            try:
                if not session.closed:
                    await session.close()
                if session.connector is not None and hasattr(
                    session.connector, "close"
                ):
                    if not session.connector.close.called:
                        await session.connector.close()
            except Exception:
                # Ignore cleanup errors in fixture
                pass


@pytest.fixture
def mock_response():
    response = AsyncMock(spec=ClientResponse)
    response.raise_for_status = Mock()
    response.json = AsyncMock()
    return response


@pytest.mark.asyncio(loop_scope="function")
async def test_connect(transport):
    """Test HTTP transport connection."""
    with patch("aiohttp.ClientSession") as mock_session_class:
        mock_session = AsyncMock()
        mock_session_class.return_value = mock_session

        await transport.connect()

        assert transport.connected
        assert transport._session is not None
        assert transport._state == ConnectionState.CONNECTED
        assert isinstance(transport._ping_task, asyncio.Task)


@pytest.mark.asyncio(loop_scope="function")
async def test_connect_timeout(transport):
    """Test connection timeout handling."""
    with patch("faye.transport.http.ClientSession") as mock_session_class:
        mock_session_class.side_effect = asyncio.TimeoutError("Connection timed out")

        with pytest.raises(TransportError, match="Failed to create HTTP session: Connection timed out"):
            await transport.connect()


@pytest.mark.asyncio(loop_scope="function")
async def test_connect_failure(transport):
    """Test HTTP connection failure."""
    with patch("faye.transport.http.ClientSession") as mock_session_class:
        mock_session_class.side_effect = ClientError("Failed to connect")

        with pytest.raises(TransportError, match="Failed to create HTTP session: Failed to connect"):
            await transport.connect()


@pytest.mark.asyncio
async def test_disconnect(transport, mock_session):
    """Test HTTP transport disconnection."""
    transport._session = mock_session
    transport._state = ConnectionState.CONNECTED
    transport._ping_task = asyncio.create_task(asyncio.sleep(0))

    await transport.disconnect()

    mock_session.close.assert_called_once()
    assert not transport.connected
    assert transport._session is None
    assert transport._state == ConnectionState.UNCONNECTED


@pytest.mark.asyncio
async def test_disconnect_with_error(transport, mock_session):
    """Test disconnection when close raises an error."""
    transport._session = mock_session
    transport._state = ConnectionState.CONNECTED
    transport._ping_task = asyncio.create_task(asyncio.sleep(0))

    async def raise_error():
        raise ClientError("Test error")

    mock_session.close = AsyncMock(side_effect=raise_error)

    with pytest.raises(TransportError, match="Failed to disconnect: Test error"):
        await transport.disconnect()

    # Clean up the ping task
    if transport._ping_task:
        transport._ping_task.cancel()
        with suppress(asyncio.CancelledError):
            await transport._ping_task


@pytest.mark.asyncio(loop_scope="function")
async def test_send_message(transport, mock_session):
    """Test sending message over HTTP."""
    transport._session = mock_session
    transport._state = ConnectionState.CONNECTED

    message = Message(channel="/test", data="test")
    response_data = [{"channel": "/test", "successful": True}]

    # Setup response
    response = AsyncMock(spec=ClientResponse)
    response.raise_for_status = Mock()
    response.json = AsyncMock(return_value=response_data)

    # Create a context manager directly on the mock_session
    post_context = AsyncMock()
    post_context.__aenter__ = AsyncMock(return_value=response)
    post_context.__aexit__ = AsyncMock(return_value=None)
    mock_session.post.return_value = post_context
    mock_session.closed = False

    response = await transport.send(message)
    assert response.channel == "/test"
    assert response.successful


@pytest.mark.asyncio
async def test_send_message_batch(transport, mock_session):
    """Test sending multiple messages in batch."""
    transport._session = mock_session
    transport._state = ConnectionState.CONNECTED

    messages = [
        Message(channel="/test1", data="test1"),
        Message(channel="/test2", data="test2"),
    ]

    # Setup responses for each message
    responses = [
        {"channel": "/test1", "successful": True, "id": "msg1", "data": "test1"},
        {"channel": "/test2", "successful": True, "id": "msg2", "data": "test2"},
    ]

    # Setup response
    response = AsyncMock(spec=ClientResponse)
    response.raise_for_status = Mock()
    response.json = AsyncMock(return_value=responses)  # Return list of responses

    # Create a context manager directly on the mock_session
    post_context = AsyncMock()
    post_context.__aenter__ = AsyncMock(return_value=response)
    post_context.__aexit__ = AsyncMock(return_value=None)
    mock_session.post.return_value = post_context
    mock_session.closed = False

    # Send messages in batch
    response = await transport.send(messages)
    assert isinstance(response, list)
    assert len(response) == 2
    assert response[0].channel == "/test1"
    assert response[0].successful

    assert mock_session.post.call_count == 1


@pytest.mark.asyncio
async def test_send_without_connection(transport):
    """Test sending message without connection."""
    transport._state = ConnectionState.UNCONNECTED
    transport._session = None  # Ensure session is None

    # Try to send a message
    with pytest.raises(TransportError) as exc_info:
        await transport.send(Message(channel="/test"))
    
    assert str(exc_info.value) == "501:HTTP request failed: 403, message='Forbidden', url='http://example.com/faye'"


@pytest.mark.asyncio
async def test_send_with_network_error(transport, mock_session):
    """Test sending message with network error."""
    transport._session = mock_session
    transport._state = ConnectionState.CONNECTED
    mock_session.post.side_effect = ClientError("Network error")

    with pytest.raises(TransportError, match="HTTP request failed: Network error"):
        await transport.send(Message(channel="/test"))


@pytest.mark.asyncio
async def test_ping(transport, mock_session):
    """Test ping functionality."""
    transport._session = mock_session
    transport._state = ConnectionState.CONNECTED

    # HTTP transport doesn't require ping
    await transport._ping()
    assert transport.connected
