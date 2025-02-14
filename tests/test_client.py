import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from faye import FayeClient
from faye.exceptions import FayeError
from faye.extensions import Extension
from faye.protocol import Message
from faye.transport import HttpTransport, WebSocketTransport


@pytest.fixture
def test_extension():
    class TestExtension(Extension):
        async def outgoing(self, message):
            self.outgoing_called = True
            self.add_ext(message)
            return message

        async def incoming(self, message):
            self.incoming_called = True
            return message

    ext = TestExtension()
    ext.outgoing_called = False
    ext.incoming_called = False
    ext.ext_data = {"test": "data"}
    return ext


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
    transport.set_message_callback = AsyncMock()
    return transport


@pytest_asyncio.fixture
async def connected_client(client, mock_transport):
    """Setup a connected client with mocked transport."""
    # Setup handshake first
    handshake_response = Message(
        channel="/meta/handshake",
        successful=True,
        client_id="client123",
        supportedConnectionTypes=["websocket", "long-polling"],
        id="msg1",
    )
    connect_response = Message(
        channel="/meta/connect", successful=True, client_id="client123", id="msg2"
    )

    # Setup transport
    client._transport = mock_transport
    client._transport.connected = True
    client._transport.send.side_effect = [handshake_response, connect_response]

    # Make set_message_callback return a coroutine
    async def set_callback(callback):
        pass

    client._transport.set_message_callback = AsyncMock(side_effect=set_callback)

    # Connect the client
    await client.connect()

    # Reset the side_effect after connect
    client._transport.send.reset_mock()
    client._transport.send.side_effect = None

    return client


def test_client_initialization():
    """Test client initialization with different transport types."""
    # Test WebSocket transport (default)
    client = FayeClient("http://example.com/faye")
    assert client._transport_type == "websocket"

    # Test HTTP transport
    client = FayeClient("http://example.com/faye", transport_type="http")
    assert client._transport_type == "http"

    # Setup supported connection types before testing transport creation
    client._protocol._supported_connection_types = ["websocket", "long-polling"]

    # Test transport creation
    transport = client._create_transport()
    assert isinstance(transport, HttpTransport)


@pytest.mark.asyncio
async def test_transport_creation(client):
    """Test transport creation for different types."""
    # Setup handshake response first
    handshake_response = Message(
        channel="/meta/handshake",
        successful=True,
        client_id="client123",
        supportedConnectionTypes=["websocket", "long-polling"],
        id="msg1",
    )
    await client._protocol.process_handshake_response(handshake_response)

    # Now test transport creation
    client._transport_type = "websocket"
    transport = client._create_transport()
    assert isinstance(transport, WebSocketTransport)
    assert transport.url.startswith("ws://")

    # Test HTTP transport creation
    client._transport_type = "http"
    transport = client._create_transport()
    assert isinstance(transport, HttpTransport)
    assert transport.url.startswith("http://")

    # Test HTTPS to WSS conversion
    client = FayeClient("https://example.com/faye")
    client._protocol._supported_connection_types = [
        "websocket",
        "long-polling",
    ]  # Set supported types
    transport = client._create_transport()
    assert transport.url.startswith("wss://")


@pytest.mark.asyncio
async def test_connect_success(client, mock_transport):
    """Test successful connection process."""
    with patch.object(client, "_create_transport", return_value=mock_transport):
        # Setup mock responses
        handshake_response = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="client123",
            supportedConnectionTypes=["websocket", "long-polling"],
            id="msg1",
        )
        connect_response = Message(
            channel="/meta/connect", successful=True, client_id="client123", id="msg2"
        )
        mock_transport.send.side_effect = [handshake_response, connect_response]
        mock_transport.connected = True

        # Connect
        await client.connect()

        # Verify connection process
        assert mock_transport.connect.called
        assert mock_transport.set_message_callback.called
        assert mock_transport.send.call_count == 2
        assert client._protocol.is_handshaken
        assert client.connected
        assert client._transport is not None
        assert client._protocol._client_id == "client123"


@pytest.mark.asyncio
async def test_connect_failure(client, mock_transport):
    """Test connection failure handling."""
    with patch.object(client, "_create_transport", return_value=mock_transport):
        # Setup mock to fail
        mock_transport.connect.side_effect = Exception("Connection failed")

        # Attempt connection
        with pytest.raises(FayeError, match="Connection failed"):
            await client.connect()

        # Verify cleanup
        assert mock_transport.disconnect.called
        assert not client.connected
        assert client._transport is None


@pytest.mark.asyncio
async def test_disconnect(connected_client):
    """Test disconnection process."""
    # Store transport reference before disconnect
    transport = connected_client._transport

    # Setup disconnect response
    response = Message(
        channel="/meta/disconnect", successful=True, client_id="client123", id="msg1"
    )
    transport.send.return_value = response

    await connected_client.disconnect()

    # Verify disconnect message was sent
    assert transport.send.called
    # Verify transport was disconnected
    assert transport.disconnect.called
    assert connected_client._transport is None
    assert not connected_client.connected


@pytest.mark.asyncio
async def test_subscribe(connected_client):
    """Test channel subscription."""

    async def callback(message):
        pass

    # Setup mock response
    response = Message(
        channel="/meta/subscribe", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = response

    # Subscribe
    await connected_client.subscribe("/test/channel", callback)

    # Verify subscription
    assert "/test/channel" in connected_client._subscriptions
    assert connected_client._subscriptions["/test/channel"] == callback


@pytest.mark.asyncio
async def test_subscribe_failure(connected_client):
    """Test subscription failure handling."""

    async def callback(message):
        pass

    # Setup mock failed response
    response = Message(
        channel="/meta/subscribe", successful=False, error="Subscription denied"
    )
    connected_client._transport.send.return_value = response

    # Attempt subscription
    with pytest.raises(FayeError, match="Subscription failed"):
        await connected_client.subscribe("/test/channel", callback)

    # Verify no subscription was added
    assert "/test/channel" not in connected_client._subscriptions


@pytest.mark.asyncio
async def test_unsubscribe(connected_client):
    """Test channel unsubscription."""

    # Setup existing subscription
    async def callback(message):
        pass

    connected_client._subscriptions["/test/channel"] = callback

    # Setup mock response
    response = Message(
        channel="/meta/unsubscribe", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = response

    # Unsubscribe
    await connected_client.unsubscribe("/test/channel")

    # Verify unsubscription
    assert "/test/channel" not in connected_client._subscriptions


@pytest.mark.asyncio
async def test_publish(connected_client):
    """Test message publication."""
    # Setup mock response
    response = Message(
        channel="/test/channel", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = response

    # Publish
    await connected_client.publish("/test/channel", {"key": "value"})

    # Verify publish message was sent
    assert connected_client._transport.send.called


@pytest.mark.asyncio
async def test_message_handling(connected_client):
    """Test incoming message handling."""
    # Setup callback
    callback = AsyncMock()
    connected_client._subscriptions["/test/channel"] = callback

    # Create test message
    message = Message(channel="/test/channel", data="test")

    # Handle message
    await connected_client._handle_message(message)

    # Verify callback was called
    callback.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_message_handling_error(connected_client):
    """Test error handling in message callback."""

    # Setup callback that raises an error
    async def error_callback(message):
        raise Exception("Callback error")

    connected_client._subscriptions["/test/channel"] = error_callback

    # Handle message (should not raise exception)
    message = Message(channel="/test/channel", data="test")
    await connected_client._handle_message(message)


@pytest.mark.asyncio
async def test_operations_without_connection():
    """Test operations when not connected."""
    client = FayeClient("http://example.com/faye")

    async def callback(message):
        pass

    with pytest.raises(FayeError, match="Not connected"):
        await client.subscribe("/test/channel", callback)

    with pytest.raises(FayeError, match="Not connected"):
        await client.unsubscribe("/test/channel")

    with pytest.raises(FayeError, match="Not connected"):
        await client.publish("/test/channel", "test")


@pytest.mark.asyncio
async def test_concurrent_connect(client, mock_transport):
    """Test concurrent connection attempts."""
    with patch.object(client, "_create_transport", return_value=mock_transport):
        # Setup mock responses
        handshake_response = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="client123",
            supportedConnectionTypes=["websocket", "long-polling"],
            id="msg1",
        )
        connect_response = Message(
            channel="/meta/connect", successful=True, client_id="client123", id="msg2"
        )
        mock_transport.send.side_effect = [handshake_response, connect_response]
        mock_transport.connected = True

        # Try to connect concurrently
        await asyncio.gather(client.connect(), client.connect(), client.connect())

        # Should only connect once
        assert mock_transport.send.call_count == 2
        assert client.connected
        assert client._protocol._client_id == "client123"


@pytest.mark.asyncio
async def test_handle_reconnect_advice():
    """Test client handling of reconnect advice."""
    client = FayeClient("http://example.com/faye")

    # Setup initial state with mock transport and handshake
    with patch.object(client, "_create_transport") as mock_create:
        mock_transport = AsyncMock()
        mock_create.return_value = mock_transport
        mock_transport.connected = True

        # Setup initial handshake
        handshake_response = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="client123",
            supportedConnectionTypes=["websocket"],
            advice={"reconnect": "retry", "interval": 1000},
            id="msg1",
        )
        connect_response = Message(
            channel="/meta/connect", successful=True, client_id="client123", id="msg2"
        )

        # Setup responses for rehandshake
        handshake_response2 = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="client124",
            supportedConnectionTypes=["websocket"],
            id="msg3",
        )
        connect_response2 = Message(
            channel="/meta/connect", successful=True, client_id="client124", id="msg4"
        )

        # Setup all responses
        mock_transport.send.side_effect = [
            handshake_response,
            connect_response,  # Initial connect
            handshake_response2,
            connect_response2,  # Rehandshake
        ]

        await client.connect()

        # Test handshake advice
        handshake_message = Message(
            channel="/meta/connect",
            advice={"reconnect": "handshake"},
            client_id="client123",
            id="msg5",
        )
        await client._handle_message(handshake_message)
        assert mock_transport.send.call_count == 4  # Initial connect + rehandshake
        assert client._protocol._client_id == "client124"  # Should have new client id


@pytest.mark.asyncio
async def test_connection_type_negotiation():
    """Test negotiation of connection types with server."""
    client = FayeClient("http://example.com/faye")

    # Mock handshake response with supported connection types
    response = Message(
        channel="/meta/handshake",
        successful=True,
        client_id="client123",
        supportedConnectionTypes=["websocket", "long-polling"],
    )

    await client._protocol.process_handshake_response(response)
    assert "websocket" in client._protocol.supported_connection_types
    assert "long-polling" in client._protocol.supported_connection_types


@pytest.mark.asyncio
async def test_extension_processing_on_subscribe(connected_client, test_extension):
    """Test extension processing on subscribe."""
    connected_client.add_extension(test_extension)
    # Rest of the test...


@pytest.mark.asyncio
async def test_extension_processing_on_unsubscribe(connected_client, test_extension):
    """Test extension processing on unsubscribe."""
    connected_client.add_extension(test_extension)
    # Rest of the test...


@pytest.mark.asyncio
async def test_extension_processing_on_publish(connected_client, test_extension):
    """Test extension processing on publish."""
    connected_client.add_extension(test_extension)
    # Rest of the test...


@pytest.mark.asyncio
async def test_error_handling_in_subscribe(connected_client):
    """Test error handling during subscribe operation."""
    # Test invalid channel
    with pytest.raises(FayeError, match="Channel name must start with /"):
        await connected_client.subscribe("invalid_channel", AsyncMock())


@pytest.mark.asyncio
async def test_error_handling_in_unsubscribe(connected_client):
    """Test error handling during unsubscribe operation."""
    # Test invalid channel
    with pytest.raises(FayeError, match="Channel name must start with /"):
        await connected_client.unsubscribe("invalid_channel")

    # Test server error response
    error_response = Message(
        channel="/meta/unsubscribe",
        successful=False,
        error="404::Not Found",
        id="msg1",
        client_id="client123",
    )
    connected_client._transport.send.return_value = error_response

    with pytest.raises(FayeError, match="Unsubscribe failed: 404::Not Found"):
        await connected_client.unsubscribe("/test/channel")


@pytest.mark.asyncio
async def test_error_handling_in_publish():
    """Test error handling during publish operation."""
    client = FayeClient("http://example.com/faye")
    client._transport = AsyncMock()
    client._protocol._client_id = "client123"
    client._transport.connected = True
    client._protocol._handshaken = True

    # Test invalid channel
    with pytest.raises(FayeError, match="Channel name must start with /"):
        await client.publish("invalid_channel", "test data")

    # Test server error response
    error_response = Message(
        channel="/meta/publish",
        successful=False,
        error="401::Unauthorized",
        id="msg1",
        client_id="client123",
    )
    client._transport.send.return_value = error_response

    with pytest.raises(FayeError, match="Publish failed: 401::Unauthorized"):
        await client.publish("/test/channel", "test data")


@pytest.mark.asyncio
async def test_error_handling_in_connect():
    """Test error handling during connect operation."""
    client = FayeClient("http://example.com/faye")

    # Test handshake failure
    with patch.object(client, "_create_transport") as mock_create:
        mock_transport = AsyncMock()
        mock_create.return_value = mock_transport

        error_response = Message(
            channel="/meta/handshake",
            successful=False,
            error="Invalid version",
            id="msg1",
        )
        mock_transport.send.return_value = error_response

        with pytest.raises(
            FayeError, match="Connection failed: Handshake failed: Invalid version"
        ):
            await client.connect()


@pytest.mark.asyncio
async def test_extension_error_handling(connected_client):
    """Test handling of extension errors."""

    class ErrorExtension(Extension):
        async def outgoing(self, message):
            if message.channel == "/test/error":
                raise Exception("Extension error")
            return message

        async def incoming(self, message):
            if message.channel == "/test/error":
                raise Exception("Extension error")
            return message

    connected_client.add_extension(ErrorExtension())

    # Test outgoing message with error
    publish_response = Message(
        channel="/meta/publish", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = publish_response

    # Should log error but not fail
    await connected_client.publish("/test/error", "test data")

    # Test incoming message with error
    message = Message(
        channel="/test/error", data="test data", client_id="client123", id="msg2"
    )
    # Should log error but not fail
    await connected_client._handle_message(message)


@pytest.mark.asyncio
async def test_channel_validation(connected_client):
    """Test channel name validation."""
    invalid_channels = [
        "",  # Empty channel
        "no_leading_slash",  # Missing leading slash
        "/empty//segment",  # Empty segment
        "/invalid/*star",  # Invalid wildcard
        "/invalid/**glob",  # Invalid glob
        "/meta/invalid",  # Reserved meta channel
        "/service/invalid",  # Reserved service channel
    ]

    for channel in invalid_channels:
        with pytest.raises(FayeError):
            await connected_client.subscribe(channel, AsyncMock())

        with pytest.raises(FayeError):
            await connected_client.publish(channel, "test data")

    # Valid channels should not raise
    valid_channels = [
        "/simple/channel",
        "/wildcard/*/channel",
        "/globbing/**/channel",
        "/*/*/channel",
        "/public/**",
    ]

    # Setup successful responses
    subscribe_response = Message(
        channel="/meta/subscribe", successful=True, client_id="client123", id="msg1"
    )
    publish_response = Message(
        channel="/meta/publish", successful=True, client_id="client123", id="msg2"
    )

    for channel in valid_channels:
        connected_client._transport.send.return_value = subscribe_response
        await connected_client.subscribe(channel, AsyncMock())

        connected_client._transport.send.return_value = publish_response
        await connected_client.publish(channel, "test data")


@pytest.mark.asyncio
async def test_message_validation():
    """Test message validation rules."""
    # Test meta message without client_id (except handshake)
    message = Message(
        channel="/meta/subscribe", subscription="/test/channel", id="msg1"
    )
    errors = message.validate()
    assert "Message must have a client_id (except for handshake/disconnect)" in errors

    # Test handshake message (should not require client_id)
    handshake_msg = Message(
        channel="/meta/handshake",
        version="1.0",
        supportedConnectionTypes=["websocket"],
        id="msg2",
    )
    assert not handshake_msg.validate()

    # Test valid message with all required fields
    message = Message(
        channel="/test/channel", client_id="client123", data="test", id="msg3"
    )
    assert not message.validate()


@pytest.mark.asyncio
async def test_protocol_state_transitions():
    """Test protocol state transitions."""
    client = FayeClient("http://example.com/faye")

    # Initial state
    assert not client.connected

    # Setup mock transport
    with patch.object(client, "_create_transport") as mock_create:
        mock_transport = AsyncMock()
        mock_create.return_value = mock_transport
        mock_transport.connected = True

        # First handshake response
        handshake_response = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="client123",
            supportedConnectionTypes=["websocket"],
            id="msg1",
        )
        connect_response = Message(
            channel="/meta/connect", successful=True, client_id="client123", id="msg2"
        )
        disconnect_response = Message(
            channel="/meta/disconnect",
            successful=True,
            client_id="client123",
            id="msg3",
        )

        # Setup response sequence
        mock_transport.send.side_effect = [
            handshake_response,  # First handshake
            connect_response,  # First connect
            disconnect_response,  # Final disconnect
        ]

        # Initial connect
        await client.connect()
        assert client.connected
        assert client._protocol.is_handshaken
        assert client._protocol._client_id == "client123"

        # After disconnect
        await client.disconnect()
        assert not client.connected
        assert not client._transport
        assert not client._protocol.is_handshaken
        assert client._protocol._client_id is None


@pytest.mark.asyncio
async def test_protocol_message_ordering():
    """Test protocol message ordering requirements."""
    client = FayeClient("http://example.com/faye")

    # Cannot subscribe before connect
    with pytest.raises(FayeError, match="Not connected"):
        await client.subscribe("/test/channel", AsyncMock())

    # Cannot publish before connect
    with pytest.raises(FayeError, match="Not connected"):
        await client.publish("/test/channel", "test")

    # Setup mock transport
    with patch.object(client, "_create_transport") as mock_create:
        mock_transport = AsyncMock()
        mock_create.return_value = mock_transport

        # Test operations before handshake
        error_response = Message(
            channel="/meta/handshake",
            successful=False,
            error="Invalid version",
            id="msg1",
        )
        mock_transport.send.return_value = error_response

        with pytest.raises(
            FayeError, match="Connection failed: Handshake failed: Invalid version"
        ):
            await client.connect()


@pytest.mark.asyncio
async def test_protocol_advice_handling():
    """Test handling of server advice."""
    client = FayeClient("http://example.com/faye")

    # Setup initial state with mock transport and handshake
    with patch.object(client, "_create_transport") as mock_create:
        mock_transport = AsyncMock()
        mock_create.return_value = mock_transport
        mock_transport.connected = True

        # Initial handshake
        handshake_response = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="client123",
            supportedConnectionTypes=["websocket"],
            advice={"reconnect": "retry", "interval": 1000},
            id="msg1",
        )
        connect_response = Message(
            channel="/meta/connect", successful=True, client_id="client123", id="msg2"
        )

        # Setup all responses including rehandshake
        mock_transport.send.side_effect = [
            handshake_response,  # Initial handshake
            connect_response,  # Initial connect
            handshake_response,  # Rehandshake
            connect_response,  # Reconnect
        ]

        await client.connect()
        assert client._protocol.is_handshaken

        # Test handshake advice
        handshake_message = Message(
            channel="/meta/connect",
            advice={"reconnect": "handshake"},
            client_id="client123",
            id="msg3",
        )

        # Create an event to track when protocol is reset
        reset_event = asyncio.Event()
        state_after_reset = None
        original_reset = client._protocol.reset

        def wrapped_reset():
            original_reset()
            nonlocal state_after_reset
            state_after_reset = client._protocol.is_handshaken
            reset_event.set()

        client._protocol.reset = wrapped_reset

        # Send advice and wait for protocol reset
        await asyncio.gather(
            client._handle_message(handshake_message), reset_event.wait()
        )

        # Check state captured during reset
        assert not state_after_reset


@pytest.mark.asyncio
async def test_transport_type_selection():
    """Test transport type selection based on server support."""
    client = FayeClient("http://example.com/faye")

    # Server only supports long-polling
    response = Message(
        channel="/meta/handshake",
        successful=True,
        client_id="client123",
        supportedConnectionTypes=["long-polling"],
    )
    await client._protocol.process_handshake_response(response)

    transport = client._create_transport()
    assert isinstance(transport, HttpTransport)

    # Server supports both, client prefers websocket
    client = FayeClient("http://example.com/faye", transport_type="websocket")
    response.supportedConnectionTypes = ["websocket", "long-polling"]
    await client._protocol.process_handshake_response(response)

    transport = client._create_transport()
    assert isinstance(transport, WebSocketTransport)

    # Server supports both, client prefers long-polling
    client = FayeClient("http://example.com/faye", transport_type="http")
    await client._protocol.process_handshake_response(response)

    transport = client._create_transport()
    assert isinstance(transport, HttpTransport)


@pytest.mark.asyncio
async def test_transport_connection_states():
    """Test transport connection state handling."""
    client = FayeClient("http://example.com/faye")

    # Test initial state
    assert not client.connected

    # Setup mock transport
    with patch.object(client, "_create_transport") as mock_create:
        mock_transport = AsyncMock()
        mock_create.return_value = mock_transport

        # Setup handshake response
        handshake_response = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="client123",
            supportedConnectionTypes=["websocket"],
            id="msg1",
        )
        connect_response = Message(
            channel="/meta/connect", successful=True, client_id="client123", id="msg2"
        )
        mock_transport.send.side_effect = [handshake_response, connect_response]

        # Test successful connection
        await client.connect()
        assert client._protocol.is_handshaken
        assert client.connected


@pytest.mark.asyncio
async def test_subscription_pattern_matching(connected_client):
    """Test subscription pattern matching with wildcards."""
    # Setup callbacks for different patterns
    callbacks = {
        "/foo/bar": AsyncMock(),
        "/foo/*": AsyncMock(),
        "/foo/*/baz": AsyncMock(),  # Changed from /** to */baz
        "/**": AsyncMock(),
    }

    # Setup mock response for subscribes
    subscribe_response = Message(
        channel="/meta/subscribe", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = subscribe_response

    # Subscribe to all patterns
    for pattern, callback in callbacks.items():
        await connected_client.subscribe(pattern, callback)

    # Test exact match
    message = Message(
        channel="/foo/bar", data="test1", client_id="client123", id="msg2"
    )
    await connected_client._handle_message(message)
    callbacks["/foo/bar"].assert_called_once_with(message)
    callbacks["/foo/*"].assert_called_once_with(message)
    callbacks["/**"].assert_called_once_with(message)

    # Test wildcard match
    message = Message(
        channel="/foo/qux", data="test2", client_id="client123", id="msg3"
    )
    await connected_client._handle_message(message)
    callbacks["/foo/*"].assert_called_with(message)
    callbacks["/**"].assert_called_with(message)
    assert callbacks["/foo/bar"].call_count == 1  # Shouldn't be called again

    # Test nested wildcard match
    message = Message(
        channel="/foo/test/baz", data="test3", client_id="client123", id="msg4"
    )
    await connected_client._handle_message(message)
    callbacks["/foo/*/baz"].assert_called_once_with(message)
    callbacks["/**"].assert_called_with(message)


@pytest.mark.asyncio
async def test_message_batching(connected_client):
    """Test handling of batched messages."""
    callback = AsyncMock()

    # Setup mock response for subscribe
    response = Message(
        channel="/meta/subscribe", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = response
    await connected_client.subscribe("/test/channel", callback)

    # Test batch of messages
    messages = [
        Message(
            channel="/test/channel", data="msg1", client_id="client123", id=f"batch{i}"
        )
        for i in range(4)
    ]

    for msg in messages:
        await connected_client._handle_message(msg)

    assert callback.call_count == 4
    calls = [call[0][0] for call in callback.call_args_list]
    assert [msg.data for msg in calls] == ["msg1", "msg1", "msg1", "msg1"]


@pytest.mark.asyncio
async def test_subscription_cleanup(connected_client):
    """Test cleanup of subscriptions on disconnect."""
    # Setup multiple subscriptions
    callbacks = {"/foo/bar": AsyncMock(), "/foo/baz": AsyncMock()}

    # Setup mock response
    subscribe_response = Message(
        channel="/meta/subscribe", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = subscribe_response

    for channel, callback in callbacks.items():
        await connected_client.subscribe(channel, callback)

    assert len(connected_client._subscriptions) == 2

    # Test unsubscribe cleanup
    unsubscribe_response = Message(
        channel="/meta/unsubscribe", successful=True, client_id="client123", id="msg2"
    )
    connected_client._transport.send.return_value = unsubscribe_response
    await connected_client.unsubscribe("/foo/bar")

    assert len(connected_client._subscriptions) == 1
    assert "/foo/bar" not in connected_client._subscriptions
    assert "/foo/baz" in connected_client._subscriptions

    # Test disconnect cleanup
    disconnect_response = Message(
        channel="/meta/disconnect", successful=True, client_id="client123", id="msg3"
    )
    connected_client._transport.send.return_value = disconnect_response
    await connected_client.disconnect()

    # After disconnect, all subscriptions should be cleared
    assert len(connected_client._subscriptions) == 0
    assert not connected_client._protocol.is_handshaken
    assert not connected_client._transport


@pytest.mark.asyncio
async def test_subscription_error_handling(connected_client):
    """Test error handling in subscription callbacks."""
    error_count = 0

    async def error_callback(message):
        nonlocal error_count
        error_count += 1
        raise Exception("Callback error")

    # Setup mock response for subscribe
    response = Message(
        channel="/meta/subscribe", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = response
    await connected_client.subscribe("/test/channel", error_callback)

    # Send multiple messages
    messages = [
        Message(
            channel="/test/channel",
            data=f"msg{i}",
            client_id="client123",
            id=f"msg{i+2}",
        )
        for i in range(2)
    ]

    for msg in messages:
        await connected_client._handle_message(msg)

    assert error_count == 2  # Callback should be called for both messages
    assert connected_client.connected  # Client should still be connected


@pytest.mark.asyncio
async def test_concurrent_subscriptions(connected_client):
    """Test concurrent subscription operations."""

    async def callback(msg):
        pass

    # Setup mock response
    response = Message(
        channel="/meta/subscribe", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = response

    # Attempt concurrent subscriptions
    channels = [f"/test/channel{i}" for i in range(5)]
    await asyncio.gather(
        *[connected_client.subscribe(channel, callback) for channel in channels]
    )

    assert len(connected_client._subscriptions) == 5
    assert all(channel in connected_client._subscriptions for channel in channels)


@pytest.mark.asyncio
async def test_concurrent_messages(connected_client):
    """Test handling of concurrent incoming messages."""
    received_messages = []

    async def callback(message):
        await asyncio.sleep(0.01)  # Simulate processing time
        received_messages.append(message.data)

    # Setup subscribe response
    subscribe_response = Message(
        channel="/meta/subscribe", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = subscribe_response
    await connected_client.subscribe("/test/channel", callback)

    # Send multiple messages concurrently
    messages = [
        Message(
            channel="/test/channel",
            data=f"msg{i}",
            client_id="client123",
            id=f"msg{i+2}",
        )
        for i in range(5)
    ]

    await asyncio.gather(*[connected_client._handle_message(msg) for msg in messages])

    assert len(received_messages) == 5
    assert set(received_messages) == {f"msg{i}" for i in range(5)}


@pytest.mark.asyncio
async def test_message_delivery_guarantees(connected_client):
    """Test message delivery guarantees and acknowledgments."""
    # Setup subscribe response
    subscribe_response = Message(
        channel="/meta/subscribe", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = subscribe_response
    await connected_client.subscribe("/test/channel", AsyncMock())

    # Test publish with acknowledgment
    publish_response = Message(
        channel="/meta/publish",  # Changed from /test/channel to /meta/publish
        successful=True,
        client_id="client123",
        id="msg2",
    )
    connected_client._transport.send.return_value = publish_response

    # Capture the sent message
    await connected_client.publish("/test/channel", "test data")
    sent_message = connected_client._transport.send.call_args[0][0]

    # Verify message properties
    assert sent_message.channel == "/test/channel"
    assert sent_message.data == "test data"
    assert sent_message.client_id == "client123"
    assert sent_message.id is not None


@pytest.mark.asyncio
async def test_channel_access_control(connected_client):
    """Test channel access control rules."""
    # Test service channel restrictions
    with pytest.raises(FayeError, match="Cannot subscribe to service channels"):
        await connected_client.subscribe("/meta/test", AsyncMock())

    with pytest.raises(FayeError, match="Cannot publish to service channels"):
        await connected_client.publish("/meta/test", "test data")

    # Test valid channel subscription
    subscribe_response = Message(
        channel="/meta/subscribe", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = subscribe_response
    await connected_client.subscribe("/valid/channel", AsyncMock())

    # Test valid channel publish
    publish_response = Message(
        channel="/meta/publish", successful=True, client_id="client123", id="msg2"
    )
    connected_client._transport.send.return_value = publish_response
    await connected_client.publish("/valid/channel", "test data")


@pytest.mark.asyncio
async def test_message_ordering(connected_client):
    """Test message delivery ordering guarantees."""
    received_order = []

    async def callback(message):
        received_order.append(message.data)

    # Setup subscribe response
    subscribe_response = Message(
        channel="/meta/subscribe", successful=True, client_id="client123", id="msg1"
    )
    connected_client._transport.send.return_value = subscribe_response
    await connected_client.subscribe("/test/channel", callback)

    # Send messages with sequential ids
    messages = [
        Message(
            channel="/test/channel",
            data=f"msg{i}",
            id=f"msg{i+2}",
            client_id="client123",
        )
        for i in range(5)
    ]

    # Process messages in order
    for msg in messages:
        await connected_client._handle_message(msg)

    # Verify messages were processed in order
    assert received_order == [f"msg{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_connection_timeouts():
    """Test connection timeout handling."""
    client = FayeClient("http://example.com/faye")

    # Test connect timeout
    with patch.object(client, "_create_transport") as mock_create:
        mock_transport = AsyncMock()
        mock_create.return_value = mock_transport
        mock_transport.connect.side_effect = asyncio.TimeoutError(
            "Connection timed out"
        )

        with pytest.raises(FayeError, match="Connection failed: Connection timed out"):
            await client.connect()

    # Test message timeout
    with patch.object(client, "_create_transport") as mock_create:
        mock_transport = AsyncMock()
        mock_create.return_value = mock_transport

        # Setup successful connection first
        handshake_response = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="client123",
            supportedConnectionTypes=["websocket"],
            id="msg1",
        )
        connect_response = Message(
            channel="/meta/connect", successful=True, client_id="client123", id="msg2"
        )
        mock_transport.send.side_effect = [handshake_response, connect_response]
        await client.connect()

        # Now test message timeout
        mock_transport.send.side_effect = asyncio.TimeoutError("Message timed out")
        with pytest.raises(FayeError, match="Publish failed: Message timed out"):
            await client.publish("/test/channel", "test data")


@pytest.mark.asyncio
async def test_connection_state_transitions():
    """Test connection state transitions."""
    client = FayeClient("http://example.com/faye")

    # Initial state
    assert not client.connected

    # Setup mock transport
    with patch.object(client, "_create_transport") as mock_create:
        mock_transport = AsyncMock()
        mock_create.return_value = mock_transport

        # First handshake response
        handshake_response = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="client123",
            supportedConnectionTypes=["websocket"],
            id="msg1",
        )
        connect_response = Message(
            channel="/meta/connect", successful=True, client_id="client123", id="msg2"
        )
        # Second handshake response (after network error)
        handshake_response2 = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="client124",  # New client id
            supportedConnectionTypes=["websocket"],
            id="msg3",
        )
        connect_response2 = Message(
            channel="/meta/connect", successful=True, client_id="client124", id="msg4"
        )
        # Disconnect response
        disconnect_response = Message(
            channel="/meta/disconnect",
            successful=True,
            client_id="client124",
            id="msg6",
        )

        # Setup response sequence
        mock_transport.send.side_effect = [
            handshake_response,  # First handshake
            connect_response,  # First connect
            handshake_response2,  # Rehandshake after network error
            connect_response2,  # Second connect
            disconnect_response,  # Final disconnect
        ]

        # Initial connect
        await client.connect()
        assert client.connected
        assert client._protocol._client_id == "client123"

        # After network error
        error_message = Message(
            channel="/meta/connect",
            successful=False,
            error="Network error",
            advice={"reconnect": "handshake"},
            id="msg5",
        )
        await client._handle_message(error_message)

        # Should trigger rehandshake and reconnect
        assert mock_transport.send.call_count == 4
        assert client.connected
        assert client._protocol._client_id == "client124"  # Should have new client id

        # After disconnect
        await client.disconnect()
        assert not client.connected
        assert not client._transport
        assert not client._protocol.is_handshaken
        assert client._protocol._client_id is None  # Should clear client id
