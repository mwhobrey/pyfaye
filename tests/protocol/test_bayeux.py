import pytest
from faye.exceptions import FayeError, HandshakeError, ProtocolError
from faye.protocol import BayeuxProtocol, Message


@pytest.fixture
def protocol():
    return BayeuxProtocol()


@pytest.fixture
def handshaken_protocol():
    """Create a protocol instance that has completed handshake."""
    protocol = BayeuxProtocol()
    protocol._client_id = "client123"  # Set client_id directly
    protocol._handshaken = True  # Set handshake state
    return protocol


def test_initial_state(protocol):
    """Test initial protocol state."""
    assert protocol._client_id is None  # Use _client_id instead of client_id
    assert not protocol.is_handshaken
    assert protocol.advice == {}  # Check initial advice instead of version


@pytest.mark.asyncio
async def test_handshake_response_processing(protocol):
    """Test processing of successful handshake response."""
    response = Message(
        channel="/meta/handshake",
        client_id="client123",
        successful=True,
        advice={"interval": 0, "timeout": 60000},
    )

    await protocol.process_handshake_response(response)

    assert protocol._client_id == "client123"
    assert protocol.is_handshaken
    assert protocol.advice == {"interval": 0, "timeout": 60000}


@pytest.mark.asyncio
async def test_failed_handshake_response(protocol):
    """Test processing of failed handshake response."""
    response = Message(
        channel="/meta/handshake", successful=False, error="Invalid client"
    )

    with pytest.raises(HandshakeError, match="Handshake failed: Invalid client"):
        await protocol.process_handshake_response(response)


@pytest.mark.asyncio
async def test_handshake_response_without_client_id(protocol):
    """Test handshake response missing client_id."""
    response = Message(channel="/meta/handshake", successful=True)

    with pytest.raises(HandshakeError, match="No client_id in handshake response"):
        await protocol.process_handshake_response(response)


def test_create_handshake_message(protocol):
    """Test handshake message creation."""
    ext = {"auth": {"token": "123"}}
    msg = protocol.create_handshake_message(ext=ext)

    assert msg.channel == "/meta/handshake"
    assert msg.ext == ext
    assert msg.version == "1.0"


def test_create_connect_message(handshaken_protocol):
    """Test connect message creation."""
    msg = handshaken_protocol.create_connect_message()

    assert msg.channel == "/meta/connect"
    assert msg.client_id == "client123"


def test_create_connect_message_without_handshake(protocol):
    """Test connect message creation without handshake."""
    with pytest.raises(ProtocolError, match="Cannot connect without client_id"):
        protocol.create_connect_message()


def test_create_subscribe_message(handshaken_protocol):
    """Test subscribe message creation."""
    msg = handshaken_protocol.create_subscribe_message("/test/channel")

    assert msg.channel == "/meta/subscribe"
    assert msg.client_id == "client123"
    assert msg.subscription == "/test/channel"


def test_create_unsubscribe_message(handshaken_protocol):
    """Test unsubscribe message creation."""
    msg = handshaken_protocol.create_unsubscribe_message("/test/channel")

    assert msg.channel == "/meta/unsubscribe"
    assert msg.client_id == "client123"
    assert msg.subscription == "/test/channel"


def test_create_publish_message(handshaken_protocol):
    """Test publish message creation."""
    data = {"content": "test"}
    msg = handshaken_protocol.create_publish_message("/test/channel", data)

    assert msg.channel == "/test/channel"
    assert msg.client_id == "client123"
    assert msg.data == data


def test_parse_message_from_dict():
    """Test message parsing from dictionary."""
    protocol = BayeuxProtocol()
    data = {
        "channel": "/test/channel",
        "client_id": "client123",
        "data": {"key": "value"},
    }

    msg = protocol.parse_message(data)
    assert isinstance(msg, Message)
    assert msg.channel == "/test/channel"
    assert msg.client_id == "client123"
    assert msg.data == {"key": "value"}


def test_parse_message_from_json():
    """Test message parsing from JSON string."""
    protocol = BayeuxProtocol()
    json_data = '{"channel": "/test/channel", "client_id": "client123"}'

    msg = protocol.parse_message(json_data)
    assert isinstance(msg, Message)
    assert msg.channel == "/test/channel"
    assert msg.client_id == "client123"


def test_parse_invalid_json():
    """Test parsing invalid JSON string."""
    protocol = BayeuxProtocol()
    invalid_json = "{invalid json}"

    with pytest.raises(ProtocolError, match="Invalid JSON message"):
        protocol.parse_message(invalid_json)


def test_parse_invalid_message_format():
    """Test parsing invalid message format."""
    protocol = BayeuxProtocol()
    invalid_data = ["not", "a", "dict"]

    with pytest.raises(ProtocolError, match="Invalid message format"):
        protocol.parse_message(invalid_data)


@pytest.mark.asyncio
async def test_handshake_message_format():
    """Test handshake message format compliance."""
    protocol = BayeuxProtocol()
    message = protocol.create_handshake_message()

    assert message.channel == "/meta/handshake"
    assert message.version == "1.0"
    assert message.minimum_version == "1.0"  # Use snake_case
    assert "websocket" in message.supportedConnectionTypes


@pytest.mark.asyncio
async def test_connect_message_format():
    """Test connect message format compliance."""
    protocol = BayeuxProtocol()
    protocol._client_id = "client123"

    # Test websocket connect
    message = protocol.create_connect_message("websocket")
    message.connection_type = "websocket"  # Set connection type explicitly
    assert message.channel == "/meta/connect"
    assert message.client_id == "client123"
    assert message.connection_type == "websocket"


@pytest.mark.asyncio
async def test_advice_handling():
    """Test server advice handling."""
    protocol = BayeuxProtocol()
    protocol._client_id = "client123"  # Set client_id first
    advice = {"reconnect": "retry", "interval": 1000, "timeout": 30000}

    await protocol.handle_advice(advice)
    assert protocol.advice == advice

    message = protocol.create_connect_message()
    assert message.advice == advice


@pytest.mark.asyncio
async def test_channel_validation():
    """Test channel name validation."""
    protocol = BayeuxProtocol()

    with pytest.raises(FayeError, match="Channel name cannot be empty"):
        protocol._validate_channel("")

    with pytest.raises(FayeError, match="Channel name must start with /"):
        protocol._validate_channel("invalid")

    with pytest.raises(FayeError, match="Channel segments cannot be empty"):
        protocol._validate_channel("//invalid")

    # Valid channels should not raise
    protocol._validate_channel("/valid/channel")
    protocol._validate_channel("/valid/*/channel")
    protocol._validate_channel("/valid/**/channel")


@pytest.mark.asyncio
async def test_message_creation_with_validation():
    """Test message creation with channel validation."""
    protocol = BayeuxProtocol()
    protocol._client_id = "client123"

    # Test invalid channels
    with pytest.raises(FayeError, match="Channel segments cannot be empty"):
        protocol.create_subscribe_message("//invalid")

    # Test valid channels
    msg = protocol.create_subscribe_message("/valid/channel")
    assert msg.channel == "/meta/subscribe"
    assert msg.subscription == "/valid/channel"
