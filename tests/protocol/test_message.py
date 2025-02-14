from unittest.mock import AsyncMock

import pytest
from faye import FayeClient
from faye.protocol.message import Message, MessageFactory


def test_message_creation():
    """Test basic message creation with required fields."""
    msg = Message(channel="/test/channel", id="test-id")
    assert msg.channel == "/test/channel"
    assert msg.id == "test-id"
    assert msg.client_id is None
    assert msg.version == "1.0"


def test_message_from_dict():
    """Test message creation from dictionary."""
    data = {
        "channel": "/test/channel",
        "data": {"test": "data"},
        "client_id": "client123",
        "id": "msg1",
        "successful": True,
    }
    msg = Message.from_dict(data)
    assert msg.channel == "/test/channel"
    assert msg.data == {"test": "data"}
    assert msg.client_id == "client123"


def test_message_to_dict():
    """Test converting message to dictionary."""
    msg = Message(channel="/test/channel", client_id="client123", data={"key": "value"})
    data = msg.to_dict()
    assert data["channel"] == "/test/channel"
    assert data["client_id"] == "client123"
    assert data["data"] == {"key": "value"}
    assert "error" not in data  # None values should be excluded


def test_message_type_properties():
    """Test message type identification properties."""
    handshake = Message(channel="/meta/handshake")
    connect = Message(channel="/meta/connect")
    subscribe = Message(channel="/meta/subscribe")
    unsubscribe = Message(channel="/meta/unsubscribe")
    disconnect = Message(channel="/meta/disconnect")
    service = Message(channel="/service/test")

    assert handshake.is_handshake
    assert connect.is_connect
    assert subscribe.is_subscribe
    assert unsubscribe.is_unsubscribe
    assert disconnect.is_disconnect
    assert service.is_service

    assert all(
        msg.is_meta for msg in [handshake, connect, subscribe, unsubscribe, disconnect]
    )
    assert not service.is_meta


def test_message_validation():
    """Test message validation rules."""
    # Test invalid channel
    msg = Message(channel="")
    errors = msg.validate()
    assert "Message must have a channel" in errors

    # Test channel format
    msg = Message(channel="invalid")
    errors = msg.validate()
    assert "Channel must start with /" in errors

    # Test subscribe without subscription
    msg = Message(channel="/meta/subscribe", client_id="client123")
    errors = msg.validate()
    assert "/meta/subscribe message must have a subscription field" in errors

    # Test meta message without id
    msg = Message(channel="/meta/connect", id="")
    errors = msg.validate()
    assert "Meta messages must have an id" in errors

    # Test missing client_id
    msg = Message(channel="/test/channel")
    errors = msg.validate()
    assert "Message must have a client_id (except for handshake/disconnect)" in errors


class TestMessageFactory:
    """Test message factory methods."""

    def test_handshake(self):
        """Test handshake message creation."""
        ext = {"auth": {"token": "123"}}
        msg = MessageFactory.handshake(ext=ext)
        assert msg.channel == "/meta/handshake"
        assert msg.ext == ext
        assert msg.version == "1.0"
        assert msg.minimum_version == "1.0"
        assert "websocket" in msg.supportedConnectionTypes

    def test_connect(self):
        """Test connect message creation."""
        msg = MessageFactory.connect("client123")
        assert msg.channel == "/meta/connect"
        assert msg.client_id == "client123"

    def test_disconnect(self):
        """Test disconnect message creation."""
        msg = MessageFactory.disconnect("client123")
        assert msg.channel == "/meta/disconnect"
        assert msg.client_id == "client123"

    def test_subscribe(self):
        """Test subscribe message creation."""
        msg = MessageFactory.subscribe("client123", "/test/channel")
        assert msg.channel == "/meta/subscribe"
        assert msg.client_id == "client123"
        assert msg.subscription == "/test/channel"

    def test_unsubscribe(self):
        """Test unsubscribe message creation."""
        msg = MessageFactory.unsubscribe("client123", "/test/channel")
        assert msg.channel == "/meta/unsubscribe"
        assert msg.client_id == "client123"
        assert msg.subscription == "/test/channel"

    def test_publish(self):
        """Test publish message creation."""
        data = {"content": "test message"}
        msg = MessageFactory.publish("/test/channel", data, client_id="client123")
        assert msg.channel == "/test/channel"
        assert msg.client_id == "client123"
        assert msg.data == data


def test_channel_pattern_matching():
    """Test channel pattern matching."""
    message = Message(channel="/foo/bar/baz")

    # Exact matches
    assert message.matches("/foo/bar/baz")
    assert not message.matches("/foo/bar")
    assert not message.matches("/foo/bar/baz/qux")

    # Wildcard matches
    assert message.matches("/foo/*/baz")
    assert message.matches("/*/*/baz")
    assert not message.matches("/foo/*/qux")

    # Globbing matches
    assert message.matches("/foo/**")
    assert message.matches("/**")
    assert message.matches("/foo/**/baz")
    assert not message.matches("/qux/**")

    # Invalid patterns
    assert not message.matches("foo/bar/baz")  # Must start with /
    assert not message.matches("/foo/*/")  # No trailing slash
    assert not message.matches("/foo/*bar")  # * must be full segment


@pytest.mark.asyncio
async def test_subscription_matching():
    """Test subscription matching in client."""
    client = FayeClient("http://example.com/faye")

    # Setup subscriptions with different patterns
    callbacks = {"/foo/bar": AsyncMock(), "/foo/*": AsyncMock(), "/foo/**": AsyncMock()}

    for channel, callback in callbacks.items():
        client._subscriptions[channel] = callback

    # Test message routing
    message = Message(channel="/foo/bar", data="test1")
    await client._handle_message(message)
    callbacks["/foo/bar"].assert_called_once_with(message)
    callbacks["/foo/*"].assert_called_once_with(message)
    callbacks["/foo/**"].assert_called_once_with(message)

    # Test nested channel
    message = Message(channel="/foo/bar/baz", data="test2")
    await client._handle_message(message)
    callbacks["/foo/**"].assert_called_with(
        message
    )  # Only globbing pattern should match


@pytest.mark.asyncio
async def test_message_handling():
    """Test message handling."""
    client = FayeClient("http://example.com/faye")
    client._transport = AsyncMock()

    message = Message(channel="/test/channel", data="test")
    await client._handle_message(message)
    # Add assertions here
