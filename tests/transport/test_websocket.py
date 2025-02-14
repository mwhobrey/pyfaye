import asyncio
import json
import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from aiohttp import ClientWebSocketResponse, WSMsgType, WSServerHandshakeError
from faye.exceptions import TransportError
from faye.protocol import Message
from faye.transport import WebSocketTransport
from websockets.exceptions import WebSocketException

logger = logging.getLogger(__name__)


@pytest_asyncio.fixture(scope="function")
async def transport():
    return WebSocketTransport("ws://example.com/faye")


@pytest_asyncio.fixture(scope="function")
async def mock_websocket():
    ws = AsyncMock(spec=ClientWebSocketResponse)
    ws.closed = False
    ws.close = AsyncMock()
    ws.receive = AsyncMock()
    ws.receive_json = AsyncMock()
    ws.send_json = AsyncMock()

    # Setup default message behavior
    msg = AsyncMock()
    msg.type = WSMsgType.TEXT
    msg.data = "{}"
    ws.receive.return_value = msg

    # Create a simple async iterator
    async def async_iter(*args):
        try:
            if hasattr(ws.receive, "side_effect"):
                if isinstance(ws.receive.side_effect, (list, tuple)):
                    for item in ws.receive.side_effect:
                        if isinstance(item, Exception):
                            raise item
                        if isinstance(item, AsyncMock):
                            yield item  # Already a message mock
                        else:
                            # Create a message mock
                            msg = AsyncMock()
                            msg.type = getattr(item, "type", WSMsgType.TEXT)
                            msg.data = getattr(item, "data", "{}")
                            msg.extra = getattr(item, "extra", None)
                            yield msg
                else:
                    if isinstance(ws.receive.side_effect, Exception):
                        raise ws.receive.side_effect
                    if isinstance(ws.receive.side_effect, AsyncMock):
                        yield ws.receive.side_effect
                    else:
                        yield await ws.receive()
            else:
                yield await ws.receive()
        except Exception as e:
            if isinstance(e, (asyncio.CancelledError, WebSocketException)):
                raise
            if not isinstance(e, StopAsyncIteration):
                logger.error(f"WebSocket iterator error: {e}")
                raise

    # Set up the async iterator
    ws.__aiter__ = async_iter

    return ws


@pytest.fixture(scope="function")
def mock_session():
    session = AsyncMock()
    session.ws_connect = AsyncMock()
    session.close = AsyncMock()
    # Setup default successful response
    session.ws_connect.side_effect = None
    return session


@pytest.mark.asyncio(loop_scope="function")
async def test_connect_success(transport, mock_websocket, mock_session):
    """Test successful WebSocket connection."""
    transport._session = mock_session  # Set session directly
    mock_session.ws_connect.return_value = mock_websocket
    mock_session.ws_connect.side_effect = None
    mock_websocket.closed = False  # Ensure websocket appears connected

    await transport.connect()

    assert transport.connected
    mock_session.ws_connect.assert_called_once_with(
        transport.url, protocols=["faye-websocket"], heartbeat=30.0
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_connect_timeout(transport):
    """Test connection timeout handling."""

    async def delayed_connect(*args, **kwargs):
        await asyncio.sleep(0.2)  # Simulate delay
        return AsyncMock()

    mock_connect = AsyncMock(side_effect=delayed_connect)
    with patch("websockets.connect", mock_connect):
        with pytest.raises(TransportError, match="Connection timed out"):
            await transport.connect(timeout=0.1)


@pytest.mark.asyncio(loop_scope="function")
async def test_connect_failure(transport, mock_session):
    """Test WebSocket connection failure."""
    transport._session = mock_session  # Set session directly

    error = WSServerHandshakeError(
        request_info=Mock(), history=None, status=404, message="Invalid response status"
    )
    mock_session.ws_connect.side_effect = error

    with pytest.raises(
        TransportError, match="WebSocket connection failed: Invalid response status"
    ):
        await transport.connect()

    assert not transport.connected
    assert transport._ws is None


@pytest.mark.asyncio(loop_scope="function")
async def test_disconnect(transport, mock_websocket):
    """Test WebSocket disconnection."""
    transport._ws = mock_websocket
    transport._connected = True

    await transport.disconnect()

    mock_websocket.close.assert_called_once()
    assert not transport.connected
    assert transport._ws is None


@pytest.mark.asyncio(loop_scope="function")
async def test_disconnect_with_error(transport, mock_websocket):
    """Test disconnection when close raises an error."""
    transport._ws = mock_websocket
    transport._connected = True
    mock_websocket.close.side_effect = WebSocketException("Close failed")

    with pytest.raises(TransportError, match="Failed to disconnect: Close failed"):
        await transport.disconnect()


@pytest.mark.asyncio(loop_scope="function")
async def test_send_message(transport, mock_websocket):
    """Test sending message over WebSocket."""
    transport._ws = mock_websocket
    transport._connected = True

    message = Message(channel="/test", data="test")
    response_data = {"channel": "/test", "successful": True}
    mock_websocket.receive_json.return_value = response_data

    response = await transport.send(message)

    mock_websocket.send_json.assert_called_with([message.to_dict()])
    assert response.channel == "/test"
    assert response.successful


@pytest.mark.asyncio(loop_scope="function")
async def test_send_message_batch(transport, mock_websocket):
    """Test sending multiple messages in batch."""
    transport._ws = mock_websocket
    transport._connected = True

    messages = [
        Message(channel="/test1", data="test1"),
        Message(channel="/test2", data="test2"),
    ]

    # Setup responses
    responses = [
        {"channel": "/test1", "successful": True},
        {"channel": "/test2", "successful": True},
    ]
    mock_websocket.receive_json.side_effect = responses

    for msg in messages:
        response = await transport.send(msg)
        assert response.successful
        assert response.channel == msg.channel

    assert mock_websocket.send_json.call_count == 2


@pytest.mark.asyncio(loop_scope="function")
async def test_send_without_connection(transport):
    """Test sending message without connection."""
    with pytest.raises(TransportError, match="Not connected"):
        await transport.send(Message(channel="/test"))


@pytest.mark.asyncio(loop_scope="function")
async def test_send_with_network_error(transport, mock_websocket):
    """Test sending message with network error."""
    transport._ws = mock_websocket
    transport._connected = True
    mock_websocket.send_json.side_effect = WebSocketException("Network error")

    with pytest.raises(TransportError, match="Failed to send message: Network error"):
        await transport.send(Message(channel="/test"))


@pytest.mark.asyncio(loop_scope="function")
async def test_message_handler(transport, mock_websocket):
    """Test message handler."""
    transport._ws = mock_websocket
    transport._connected = True

    callback = AsyncMock()
    await transport.set_message_callback(callback)

    # Simulate text message
    msg = AsyncMock()
    msg.type = WSMsgType.TEXT
    msg.data = json.dumps({"channel": "/test", "data": "test"})
    mock_websocket.receive.side_effect = [msg, asyncio.CancelledError()]

    await transport._handle_messages()

    callback.assert_called_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_message_handler_invalid_json(transport, mock_websocket):
    """Test handling of invalid JSON messages."""
    transport._ws = mock_websocket
    transport._connected = True

    callback = AsyncMock()
    await transport.set_message_callback(callback)

    # Simulate invalid JSON message
    msg = AsyncMock()
    msg.type = WSMsgType.TEXT
    msg.data = "invalid json"
    mock_websocket.receive.return_value = msg

    # Start message handler
    task = asyncio.create_task(transport._handle_messages())
    await asyncio.sleep(0)
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    callback.assert_not_called()


@pytest.mark.asyncio(loop_scope="function")
async def test_message_handler_connection_lost(transport, mock_websocket):
    """Test message handler when connection is lost."""
    transport._ws = mock_websocket
    transport._connected = True

    # Create a close message that will be sent before the connection is lost
    close_msg = AsyncMock()
    close_msg.type = WSMsgType.CLOSE
    close_msg.data = 1006  # Abnormal closure
    close_msg.extra = "Connection lost"

    # Set up the sequence: first a close message, then the exception
    mock_websocket.receive.side_effect = [
        close_msg,
        WebSocketException("Connection lost"),
    ]

    await transport._handle_messages()

    assert not transport._connected
    assert transport._close_code == 1006
    assert transport._close_reason == "Connection lost"


@pytest.mark.asyncio(loop_scope="function")
async def test_reconnection_after_failure(transport, mock_session, mock_websocket):
    """Test reconnection after connection failure."""
    transport._session = mock_session

    # First attempt fails
    mock_session.ws_connect.side_effect = WebSocketException("First attempt failed")
    with pytest.raises(
        TransportError, match="WebSocket connection failed: First attempt failed"
    ):
        await transport.connect()

    # Second attempt succeeds
    mock_session.ws_connect.side_effect = None
    mock_session.ws_connect.return_value = mock_websocket
    mock_websocket.closed = False

    # Create a new session since the first one would have been closed
    transport._session = mock_session
    await transport.connect()

    assert transport.connected
    assert mock_session.ws_connect.call_count == 2


@pytest.mark.asyncio(loop_scope="function")
async def test_websocket_protocol_negotiation(transport, mock_session, mock_websocket):
    """Test WebSocket protocol negotiation."""
    transport._session = mock_session
    mock_session.ws_connect.return_value = mock_websocket
    mock_session.ws_connect.side_effect = None
    mock_websocket.closed = False

    await transport.connect()

    mock_session.ws_connect.assert_called_once_with(
        transport.url, protocols=["faye-websocket"], heartbeat=30.0
    )
    assert transport.connected


@pytest.mark.asyncio(loop_scope="function")
async def test_message_batching(transport, mock_websocket):
    """Test message batching."""
    transport._ws = mock_websocket
    transport._connected = True

    # Setup batch response
    batch_response = [
        {"channel": "/test1", "data": "test1"},
        {"channel": "/test2", "data": "test2"},
    ]

    msg = AsyncMock()
    msg.type = WSMsgType.TEXT
    msg.data = json.dumps(batch_response)

    # Set up the mock to return our message and then end iteration
    mock_websocket.receive.side_effect = [msg, StopAsyncIteration]

    callback = AsyncMock()
    await transport.set_message_callback(callback)

    await transport._handle_messages()

    assert callback.call_count == 2
    assert callback.call_args_list[0].args[0].channel == "/test1"
    assert callback.call_args_list[1].args[0].channel == "/test2"


@pytest.mark.asyncio(loop_scope="function")
async def test_connection_failure_handling(transport, mock_session):
    """Test WebSocket connection failure handling."""
    transport._session = mock_session

    # Create a specific error instance
    from aiohttp import ClientResponse, WSServerHandshakeError

    mock_response = Mock(spec=ClientResponse)
    mock_response.status = 404
    mock_response.url = transport.url

    error = WSServerHandshakeError(
        request_info=mock_response,
        history=None,
        status=404,
        message="Invalid response status",
    )
    mock_session.ws_connect.side_effect = error

    with pytest.raises(TransportError) as exc_info:
        await transport.connect()

    assert str(exc_info.value) == "WebSocket connection failed: Invalid response status"
    assert not transport.connected
    assert transport._ws is None


@pytest.mark.asyncio(loop_scope="function")
async def test_websocket_close_handling(transport, mock_websocket):
    """Test WebSocket close handling."""
    transport._ws = mock_websocket
    transport._connected = True
    mock_websocket.closed = False

    # Create a sequence of messages ending with a close
    close_msg = AsyncMock()
    close_msg.type = WSMsgType.CLOSE
    close_msg.data = 1000
    close_msg.extra = "Normal close"

    # Set up the mock to return our close message and then raise CancelledError
    mock_websocket.receive.side_effect = [close_msg, asyncio.CancelledError()]

    await transport._handle_messages()

    assert not transport.connected
    assert transport._close_code == 1000
    assert transport._close_reason == "Normal close"


@pytest.mark.asyncio
class TestWebSocketTransport:
    @pytest.mark.asyncio
    async def test_handle_text_message(self):
        """Test handling of text messages."""
        transport = WebSocketTransport("ws://test")
        messages_received = []

        async def callback(message):
            messages_received.append(message)

        transport._message_callback = callback

        # Test single message
        await transport._handle_text_message('{"channel": "/test", "data": "hello"}')
        assert len(messages_received) == 1
        assert messages_received[0].channel == "/test"
        assert messages_received[0].data == "hello"

        # Test message array
        messages_received.clear()
        await transport._handle_text_message(
            '[{"channel": "/test1"}, {"channel": "/test2"}]'
        )
        assert len(messages_received) == 2
        assert messages_received[0].channel == "/test1"
        assert messages_received[1].channel == "/test2"

        # Test invalid JSON
        messages_received.clear()
        await transport._handle_text_message(
            "invalid json"
        )  # Should log error but not raise
        assert len(messages_received) == 0

        # Test without callback set
        transport._message_callback = None
        await transport._handle_text_message('{"channel": "/test"}')  # Should not raise

    @pytest.mark.asyncio
    async def test_handle_close_message(self):
        """Test handling of close messages."""
        transport = WebSocketTransport("ws://test")
        transport._connected = True

        # Create mock close message
        class MockCloseMessage:
            type = WSMsgType.CLOSE
            data = 1000  # Normal closure
            extra = "Test close"

        msg = MockCloseMessage()

        # Test close handling
        await transport._handle_close_message(msg)

        assert not transport._connected
        assert transport._close_code == 1000
        assert transport._close_reason == "Test close"

    @pytest.mark.asyncio
    async def test_handle_messages_routing(self):
        """Test message type routing in handle_messages."""
        transport = WebSocketTransport("ws://test")
        transport._ws = AsyncMock()
        transport._connected = True

        # Mock message stream
        messages = [
            # Text message
            AsyncMock(type=WSMsgType.TEXT, data='{"channel": "/test"}'),
            # Close message
            AsyncMock(type=WSMsgType.CLOSE, data=1000, extra="Test close"),
            # Error message
            AsyncMock(type=WSMsgType.ERROR, data="Test error"),
        ]

        transport._ws.__aiter__.return_value = messages

        # Track handled messages
        handled_text = []

        async def callback(message):
            handled_text.append(message)

        transport._message_callback = callback

        # Run message handler
        await transport._handle_messages()

        # Verify message handling
        assert len(handled_text) == 1  # One text message handled
        assert handled_text[0].channel == "/test"
        assert not transport._connected  # Connection closed after error
        assert transport._close_code == 1000
        assert transport._close_reason == "Test close"
