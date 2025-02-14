import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from aiohttp import ClientError, ClientResponse, ClientSession
from faye.exceptions import TransportError
from faye.protocol import BayeuxProtocol, Message
from faye.transport import HttpTransport


@pytest_asyncio.fixture(scope="function")
async def transport():
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
        session.closed = False

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
        assert isinstance(transport._polling_task, asyncio.Task)


@pytest.mark.asyncio(loop_scope="function")
async def test_connect_timeout(transport):
    """Test connection timeout handling."""
    with patch("faye.transport.http.ClientSession") as mock_session_class:
        mock_session_class.side_effect = asyncio.TimeoutError()

        with pytest.raises(TransportError, match="Connection timed out"):
            await transport.connect()


@pytest.mark.asyncio(loop_scope="function")
async def test_connect_failure(transport):
    """Test HTTP connection failure."""
    with patch("faye.transport.http.ClientSession") as mock_session_class:
        mock_session_class.side_effect = ClientError()

        with pytest.raises(TransportError, match="Failed to connect"):
            await transport.connect()


@pytest.mark.asyncio
async def test_disconnect(transport, mock_session):
    """Test HTTP transport disconnection."""
    transport._session = mock_session
    transport._connected = True
    transport._polling_task = asyncio.create_task(asyncio.sleep(0))

    await transport.disconnect()

    mock_session.close.assert_called_once()
    assert not transport.connected
    assert transport._session is None
    assert transport._polling_task is None


@pytest.mark.asyncio
async def test_disconnect_with_error(transport, mock_session):
    """Test disconnection when close raises an error."""
    transport._session = mock_session
    transport._connected = True
    transport._polling_task = asyncio.create_task(asyncio.sleep(0))

    async def raise_error():
        raise ClientError("Test error")

    mock_session.close = AsyncMock(side_effect=raise_error)

    with pytest.raises(TransportError, match="Failed to disconnect: Test error"):
        await transport.disconnect()

    # Clean up the polling task
    if transport._polling_task:
        transport._polling_task.cancel()
        with suppress(asyncio.CancelledError):
            await transport._polling_task

    # Clean up the connector
    if not mock_session.connector.close.called:
        await mock_session.connector.close()


@pytest.mark.asyncio(loop_scope="function")
async def test_send_message(transport, mock_session):
    """Test sending message over HTTP."""
    transport._session = mock_session
    transport._connected = True

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

    response = await transport.send(message)
    assert response.channel == "/test"
    assert response.successful


@pytest.mark.asyncio
async def test_send_message_batch(transport, mock_session):
    """Test sending multiple messages in batch."""
    transport._session = mock_session
    transport._connected = True

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
    response.json = AsyncMock(side_effect=[responses])  # Return list of responses

    # Create a context manager directly on the mock_session
    post_context = AsyncMock()
    post_context.__aenter__ = AsyncMock(return_value=response)
    post_context.__aexit__ = AsyncMock(return_value=None)
    mock_session.post.return_value = post_context

    # Send messages in batch
    response = await transport.send(messages)
    assert response.channel == "/test1"
    assert response.successful

    assert mock_session.post.call_count == 1


@pytest.mark.asyncio
async def test_send_without_connection(transport):
    """Test sending message without connection."""
    with pytest.raises(TransportError, match="Not connected"):
        await transport.send(Message(channel="/test"))


@pytest.mark.asyncio
async def test_send_with_network_error(transport, mock_session):
    """Test sending message with network error."""
    transport._session = mock_session
    transport._connected = True
    mock_session.post.side_effect = ClientError()

    with pytest.raises(TransportError, match="Failed to send message"):
        await transport.send(Message(channel="/test"))


@pytest.mark.asyncio(loop_scope="function")
async def test_polling(transport, mock_session):
    """Test long-polling mechanism."""
    try:
        transport._session = mock_session
        transport._connected = True
        callback = AsyncMock()
        await transport.set_message_callback(callback)

        # Setup polling response
        response = AsyncMock(spec=ClientResponse)
        response.raise_for_status = Mock()
        response.json = AsyncMock(
            return_value=[
                {
                    "channel": "/test",
                    "data": "test",
                    "successful": True,
                    "clientId": "client1",
                    "id": "msg1",
                }
            ]
        )

        # Create a context manager directly on the mock_session
        post_context = AsyncMock()
        post_context.__aenter__ = AsyncMock(return_value=response)
        post_context.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = post_context

        # Start polling
        transport._start_polling()
        await asyncio.sleep(0.1)

        # Wait for callback
        for _ in range(10):
            if callback.called:
                break
            await asyncio.sleep(0.1)

        assert callback.called
    finally:
        # Clean up
        await transport.disconnect()


@pytest.mark.asyncio
async def test_polling_with_multiple_messages(transport, mock_session):
    """Test polling with multiple messages in response."""
    try:
        transport._session = mock_session
        transport._connected = True
        callback = AsyncMock()
        await transport.set_message_callback(callback)

        messages = [
            {
                "channel": "/test1",
                "data": "test1",
                "successful": True,
                "clientId": "client1",
                "advice": None,
                "error": None,
                "ext": None,
                "id": "msg1",
                "version": "1.0",
            },
            {
                "channel": "/test2",
                "data": "test2",
                "successful": True,
                "clientId": "client1",
                "advice": None,
                "error": None,
                "ext": None,
                "id": "msg2",
                "version": "1.0",
            },
        ]

        # Setup response
        response = AsyncMock(spec=ClientResponse)
        response.raise_for_status = Mock()
        response.json = AsyncMock(return_value=messages)

        # Create a context manager directly on the mock_session
        post_context = AsyncMock()
        post_context.__aenter__ = AsyncMock(return_value=response)
        post_context.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = post_context

        # Start polling
        transport._start_polling()
        await asyncio.sleep(0.1)

        # Wait for callbacks
        for _ in range(30):
            if callback.call_count >= 2:
                break
            await asyncio.sleep(0.1)

        assert (
            callback.call_count == 2
        ), f"Expected 2 callbacks, got {callback.call_count}"
    finally:
        # Clean up
        await transport.disconnect()


@pytest.mark.asyncio
async def test_polling_error_handling(transport, mock_session):
    """Test error handling in polling loop."""
    transport._session = mock_session
    transport._connected = True

    # Setup post to raise an error
    post_context = AsyncMock()
    post_context.__aenter__ = AsyncMock(side_effect=ClientError())
    post_context.__aexit__ = AsyncMock()
    mock_session.post = Mock(return_value=post_context)

    # Start polling
    transport._start_polling()
    await asyncio.sleep(0.1)  # Wait for first poll attempt

    # Wait for post to be called
    for _ in range(10):
        if mock_session.post.call_count > 0:
            break
        await asyncio.sleep(0.1)

    # Cleanup
    transport._polling_task.cancel()
    with suppress(asyncio.CancelledError):
        await transport._polling_task

    # Close the session
    await mock_session.__aexit__(None, None, None)

    assert mock_session.post.call_count > 0, "POST request was not made"
