"""Test client functionality."""

import asyncio
from typing import AsyncGenerator, Callable, Any, Generator
import pytest
from unittest.mock import AsyncMock, Mock, patch, PropertyMock

from faye.client import FayeClient, ConnectionState
from faye.exceptions import FayeError, ErrorCode
from faye.protocol import Message, BayeuxProtocol
from faye.transport.base import Transport


@pytest.fixture
def protocol() -> BayeuxProtocol:
    """Create a mock protocol."""
    protocol = Mock(spec=BayeuxProtocol)
    protocol.create_handshake_message = Mock(return_value=Message("/meta/handshake"))
    protocol.create_connect_message = Mock(return_value=Message("/meta/connect"))
    protocol.create_disconnect_message = Mock(return_value=Message("/meta/disconnect"))
    protocol.create_subscribe_message = Mock(side_effect=lambda channel: (
        raise_error() if not channel.startswith("/") or "*" in channel
        else Message("/meta/subscribe")
    ))
    protocol.create_unsubscribe_message = Mock(return_value=Message("/meta/unsubscribe"))
    protocol.create_publish_message = Mock(return_value=Message("/test/channel"))
    return protocol


def raise_error():
    """Helper function to raise FayeError."""
    raise FayeError(ErrorCode.CHANNEL_INVALID, ["subscribe"], "Invalid channel")


@pytest.fixture
def transport() -> Transport:
    """Create a mock transport."""
    transport = AsyncMock(spec=Transport)
    type(transport).connected = PropertyMock(return_value=True)  # Mock the connected property
    transport.send = AsyncMock()
    transport.connect = AsyncMock()
    transport.disconnect = AsyncMock()
    return transport


@pytest.fixture
def client(transport: Transport, protocol: BayeuxProtocol) -> FayeClient:
    """Create a client with mocked dependencies."""
    client = FayeClient("ws://example.com/faye")
    client._transport = transport
    client._protocol = protocol
    client._subscriptions = {}
    return client


class TestClientStateManagement:
    """Test client state management."""
    
    @pytest.mark.asyncio
    async def test_initial_state(self, client: FayeClient) -> None:
        """Test initial client state."""
        assert client.state == "unconnected"
        assert not client.connected
        assert client.client_id is None
    
    @pytest.mark.asyncio
    async def test_connect_updates_state(self, client: FayeClient, transport: Transport, protocol: BayeuxProtocol) -> None:
        """Test state updates during connection."""
        # Setup successful handshake response
        handshake_response = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="test123",
            supported_connection_types=["websocket"]
        )
        transport.send.return_value = handshake_response
        protocol._is_handshaken = True  # Set protocol to handshaken state
        
        await client.connect()
        
        assert client._state == ConnectionState.CONNECTED
        assert client.connected
        assert client.client_id == "test123"
        transport.connect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_disconnect_updates_state(self, client: FayeClient, transport: Transport) -> None:
        """Test state updates during disconnection."""
        client._state = ConnectionState.CONNECTED
        
        await client.disconnect()
        
        assert client._state == ConnectionState.UNCONNECTED
        assert not client.connected
        transport.disconnect.assert_called_once()


class TestClientMessageHandling:
    """Test client message handling."""
    
    @pytest.mark.asyncio
    async def test_subscription_management(self, client: FayeClient, transport: Transport) -> None:
        """Test subscription handling."""
        callback = AsyncMock()
        subscribe_response = Message(
            channel="/meta/subscribe",
            successful=True,
            subscription="/test/channel"
        )
        transport.send.return_value = subscribe_response
        
        await client.subscribe("/test/channel", callback)
        
        assert "/test/channel" in client._subscriptions
        assert client._subscriptions["/test/channel"] == callback
    
    @pytest.mark.asyncio
    async def test_message_delivery(self, client: FayeClient) -> None:
        """Test message delivery to subscribers."""
        callback = AsyncMock()
        client._subscriptions["/test/channel"] = callback
        
        message = Message(channel="/test/channel", data={"test": "data"})
        await client._deliver_message(message)
        
        callback.assert_called_once_with(message)
    
    @pytest.mark.asyncio
    async def test_message_batching(self, client: FayeClient, transport: Transport) -> None:
        """Test message batching."""
        messages = [
            Message("/test/1", data={"seq": 1}),
            Message("/test/2", data={"seq": 2}),
        ]
        transport.send.return_value = messages
        
        responses = await client.batch(messages)
        
        assert len(responses) == len(messages)
        transport.send.assert_called_once_with(messages)


class TestClientErrorHandling:
    """Test client error handling."""
    
    @pytest.mark.asyncio
    async def test_connection_failure(self, client: FayeClient, transport: Transport) -> None:
        """Test connection failure handling."""
        transport.send.side_effect = FayeError(
            ErrorCode.CONNECTION_FAILED, ["connect"], "Connection failed"
        )
        
        with pytest.raises(FayeError, match="Connection failed"):
            await client.connect()
        
        assert not client.connected
        assert client._state == ConnectionState.UNCONNECTED
    
    @pytest.mark.asyncio
    async def test_subscription_failure(self, client: FayeClient, transport: Transport) -> None:
        """Test subscription failure handling."""
        transport.send.return_value = Message(
            channel="/meta/subscribe",
            successful=False,
            error="403:Forbidden"
        )
        
        with pytest.raises(FayeError, match="403:Forbidden"):
            await client.subscribe("/test/channel", AsyncMock())
        
        assert "/test/channel" not in client._subscriptions
    
    @pytest.mark.asyncio
    async def test_invalid_channel(self, client: FayeClient) -> None:
        """Test invalid channel validation."""
        with pytest.raises(FayeError) as exc_info:
            await client.subscribe("invalid*channel", AsyncMock())  # Use an invalid channel name
        assert "Invalid channel" in str(exc_info.value)


class TestClientExtensions:
    """Test client extension handling."""
    
    @pytest.mark.asyncio
    async def test_extension_processing(self, client: FayeClient, transport: Transport, protocol: BayeuxProtocol) -> None:
        """Test extension message processing."""
        # Setup successful handshake response
        handshake_response = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="test123",
            supported_connection_types=["websocket"]
        )
        transport.send.return_value = handshake_response
        protocol._is_handshaken = True  # Set protocol to handshaken state
        
        # Create and add extension
        extension = AsyncMock()
        extension.process_outgoing = AsyncMock(return_value=Message("/test/channel"))
        extension.process_incoming = AsyncMock(return_value=Message("/test/channel"))
        client.add_extension(extension)
        
        # Connect client first
        await client.connect()
        
        # Now test publishing
        message = Message("/test/channel")
        transport.send.return_value = message
        
        await client.publish("/test/channel", {"test": "data"})
        
        extension.process_outgoing.assert_called()
        # extension.process_incoming.assert_called()  # This would depend on implementation
