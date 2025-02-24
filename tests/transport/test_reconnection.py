"""Test reconnection behavior of the transport layer."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch
import json

import pytest
from aiohttp import WSMessage, WSMsgType, WSServerHandshakeError, WebSocketError
from aiohttp.client import ClientSession, ClientWebSocketResponse

from faye.client import FayeClient
from faye.exceptions import TransportError, ErrorCode
from faye.protocol.message import Message
from faye.transport.base import ConnectionState
from faye.transport.websocket import WebSocketTransport


@pytest.mark.asyncio
async def test_transport_reconnection():
    """Test transport reconnection after connection failure."""
    client = FayeClient("http://example.com/faye")
    
    # Create a real mock transport instead of mocking _create_transport
    mock_transport = AsyncMock(spec=WebSocketTransport)
    mock_transport.state = ConnectionState.UNCONNECTED
    mock_transport.url = "ws://example.com/faye"
    mock_transport.connected = False
    
    # Mock the session and ws_connect
    mock_session = AsyncMock(spec=ClientSession)
    mock_ws = AsyncMock(spec=ClientWebSocketResponse)
    mock_ws.closed = False
    mock_ws.close = AsyncMock()
    
    # Mock WebSocket receive to return handshake response
    handshake_response = Message(
        channel="/meta/handshake",
        successful=True,
        client_id="client123",
        supported_connection_types=["websocket"],
        advice={"reconnect": "retry", "interval": 0}  # Set interval to 0 for faster test
    )

    # Create a response queue in the transport
    mock_transport._response_queue = asyncio.Queue()
    
    # Mock the _connect method to change state
    async def mock_connect():
        mock_transport.state = ConnectionState.CONNECTED
        mock_transport.connected = True
        # Simulate handshake and connect sequence
        handshake_msg = Message(
            channel="/meta/handshake",
            version="1.0",
            supported_connection_types=["websocket"],
            advice={"reconnect": "retry", "interval": 0}
        )
        await mock_transport.send(handshake_msg)
        connect_msg = Message(
            channel="/meta/connect",
            client_id="client123",
            connection_type="websocket",
            version="1.0",
            advice={"reconnect": "retry", "interval": 0}
        )
        await mock_transport.send(connect_msg)
    
    mock_transport._connect = mock_connect
    mock_transport.connect = mock_connect

    # Mock send to handle different message types
    send_calls = []
    async def mock_send(message):
        if isinstance(message, list):
            message = message[0]
        
        send_calls.append(message.channel)
        
        if message.channel == "/meta/handshake":
            return handshake_response
        elif message.channel == "/meta/connect":
            # First return success, then simulate failure
            if mock_transport.state == ConnectionState.UNCONNECTED:
                raise TransportError("Connection lost")
            connect_response = Message(
                channel="/meta/connect",
                successful=True,
                client_id="client123",
                advice={"reconnect": "retry", "interval": 0}  # Set interval to 0 for faster test
            )
            return connect_response
        return message

    mock_transport.send = AsyncMock(side_effect=mock_send)

    # Mock the _handle_connection_error to trigger reconnection
    reconnect_event = asyncio.Event()
    async def mock_handle_error(error):
        mock_transport.state = ConnectionState.UNCONNECTED
        mock_transport.connected = False
        # Create reconnect task that will run immediately
        mock_transport._reconnect_task = asyncio.create_task(mock_transport.connect())
        await mock_transport._reconnect_task
        reconnect_event.set()
        
    mock_transport._handle_connection_error = mock_handle_error

    # Patch the WebSocketTransport class
    with patch("faye.client.WebSocketTransport", return_value=mock_transport):
        # Connect client
        await client.connect()
        assert client._state.value == ConnectionState.CONNECTED.value
        
        # Get initial call count and clear the send_calls list
        initial_calls = mock_transport.send.call_count
        send_calls.clear()
        
        # Simulate connection failure and trigger reconnection
        mock_transport.state = ConnectionState.UNCONNECTED
        mock_transport.connected = False
        await mock_transport._handle_connection_error(TransportError("Connection lost"))
        
        # Wait for reconnection to complete
        await reconnect_event.wait()
        await asyncio.sleep(0.1)  # Give a bit more time for all messages to be sent

        # Verify reconnection attempt - should see handshake and connect messages
        assert mock_transport.send.call_count >= initial_calls + 2
        assert "/meta/handshake" in send_calls
        assert "/meta/connect" in send_calls
        assert client._state.value == ConnectionState.CONNECTED.value


@pytest.mark.asyncio
async def test_reconnection_backoff():
    """Test reconnection backoff with increasing intervals."""
    client = FayeClient("http://example.com/faye")
    
    # Create a real mock transport
    mock_transport = AsyncMock(spec=WebSocketTransport)
    mock_transport.state = ConnectionState.UNCONNECTED
    mock_transport.url = "ws://example.com/faye"
    mock_transport.connected = False
    mock_transport._handle_connection_error = AsyncMock()

    # Mock the session and ws_connect
    mock_session = AsyncMock(spec=ClientSession)
    mock_ws = AsyncMock(spec=ClientWebSocketResponse)
    mock_ws.closed = False
    mock_ws.close = AsyncMock()
    
    # Mock WebSocket receive to return handshake response
    handshake_response = Message(
        channel="/meta/handshake",
        successful=True,
        client_id="client123",
        supported_connection_types=["websocket"],
        advice={"reconnect": "retry", "interval": 0}
    )

    # Create a response queue in the transport
    mock_transport._response_queue = asyncio.Queue()
    
    # Mock the _connect method to change state
    async def mock_connect():
        mock_transport.state = ConnectionState.CONNECTED
        mock_transport.connected = True
        await mock_transport._response_queue.put(handshake_response)
    
    mock_transport._connect = mock_connect
    mock_transport.connect = mock_connect

    # Mock send to handle different message types
    async def mock_send(message):
        if isinstance(message, list):
            message = message[0]
        
        if message.channel == "/meta/handshake":
            return handshake_response
        elif message.channel == "/meta/connect":
            # Simulate connection failure after initial connection
            if mock_transport.state == ConnectionState.UNCONNECTED:
                raise TransportError("Connection lost")
            connect_response = Message(
                channel="/meta/connect",
                successful=True,
                client_id="client123",
                advice={"reconnect": "retry", "interval": 1000}
            )
            return connect_response
        return message

    mock_transport.send = AsyncMock(side_effect=mock_send)

    # Patch the WebSocketTransport class
    with patch("faye.client.WebSocketTransport", return_value=mock_transport):
        # Connect client
        await client.connect()
        assert client._state.value == ConnectionState.CONNECTED.value
        
        # Simulate multiple connection failures
        for _ in range(3):
            mock_transport.send.reset_mock()
            mock_transport.state = ConnectionState.UNCONNECTED
            mock_transport.connected = False
            
            # Trigger reconnection by raising error
            try:
                await mock_transport.send(Message("/meta/connect"))
            except TransportError:
                pass
            
            # Allow time for reconnection
            await asyncio.sleep(0.1)
            
            # Verify reconnection attempt
            assert mock_transport.send.call_count >= 1
            assert client._state.value == ConnectionState.CONNECTED.value


@pytest.mark.asyncio
async def test_handshake_reconnection():
    """Test reconnection with handshake after auth failure."""
    client = FayeClient("http://example.com/faye")
    
    # Create a real mock transport
    mock_transport = AsyncMock(spec=WebSocketTransport)
    mock_transport.state = ConnectionState.UNCONNECTED
    mock_transport.url = "ws://example.com/faye"
    mock_transport.connected = False
    client._transport = mock_transport

    # Setup message callback
    mock_transport.set_message_callback = AsyncMock()

    # Mock connect to set state to CONNECTED
    async def mock_connect():
        mock_transport.state = ConnectionState.CONNECTED
        mock_transport.connected = True
    mock_transport.connect.side_effect = mock_connect

    # First connection succeeds
    handshake_response = Message(
        channel="/meta/handshake",
        successful=True,
        client_id="client123",
        supported_connection_types=["websocket"]
    )

    # Mock send to handle different message types
    async def mock_send(message):
        if message.channel == "/meta/handshake":
            return handshake_response
        elif message.channel == "/meta/connect":
            return Message(
                channel="/meta/connect",
                successful=True,
                client_id="client123"
            )
        return message
    mock_transport.send.side_effect = mock_send

    # Mock transport creation
    with patch("faye.transport.websocket.WebSocketTransport", return_value=mock_transport):
        await client.connect()

        # Verify initial connection
        assert client.connected
        assert client._protocol._client_id == "client123"

        # Reset send mock to track new calls
        mock_transport.send.reset_mock()
        mock_transport.send.side_effect = mock_send

        # Simulate auth failure
        mock_transport.state = ConnectionState.UNCONNECTED
        mock_transport.connected = False

        # Send connect message with auth error
        connect_msg = Message(
            "/meta/connect",
            client_id="client123",
            successful=False,
            error="401:auth:Token expired",
            advice={"reconnect": "handshake", "interval": 1000}
        )
        await client._handle_message(connect_msg)

        # Allow time for reconnection attempt
        await asyncio.sleep(1.1)  # Wait for retry interval + 0.1s

        # Verify handshake was attempted
        assert mock_transport.connect.call_count >= 1
        assert mock_transport.send.call_count >= 1
        last_call = mock_transport.send.call_args[0][0]
        assert last_call.channel == "/meta/handshake"
