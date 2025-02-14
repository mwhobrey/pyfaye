from unittest.mock import AsyncMock

import pytest
from faye.exceptions import AuthenticationError
from faye.extensions.authentication import AuthenticationExtension
from faye.protocol import Message


@pytest.fixture
def auth_extension():
    return AuthenticationExtension("test_token")


@pytest.mark.asyncio
async def test_auth_extension_outgoing():
    """Test authentication extension adds token to outgoing messages."""
    extension = AuthenticationExtension("test_token")

    # Test handshake message
    handshake_msg = Message(channel="/meta/handshake", ext={})
    processed = await extension.outgoing(handshake_msg)
    assert processed.ext == {"auth": {"token": "test_token"}}

    # Test connect message (shouldn't add auth)
    connect_msg = Message(channel="/meta/connect", client_id="client123", ext={})
    processed = await extension.outgoing(connect_msg)
    assert not processed.ext  # Should be empty

    # Test other messages (shouldn't add auth)
    publish_msg = Message(channel="/test", client_id="client123", ext={})
    processed = await extension.outgoing(publish_msg)
    assert not processed.ext


@pytest.mark.asyncio
async def test_auth_extension_incoming():
    """Test authentication extension handles auth errors."""
    extension = AuthenticationExtension("test_token")

    # Test successful message
    success_msg = Message(channel="/meta/connect", successful=True)
    processed = await extension.incoming(success_msg)
    assert processed == success_msg

    # Test auth error
    error_msg = Message(
        channel="/meta/connect", successful=False, ext={"auth_error": "Invalid token"}
    )
    with pytest.raises(AuthenticationError, match="Invalid token"):
        await extension.incoming(error_msg)


@pytest.mark.asyncio
async def test_auth_extension_integration():
    """Test authentication extension integrated with client."""
    from faye import FayeClient

    client = FayeClient("http://example.com/faye")
    client._transport = AsyncMock()

    # Add auth extension
    auth = AuthenticationExtension("test_token")
    client.add_extension(auth)

    # Mock the client's _apply_extensions method
    original_send = client._transport.send

    async def send_with_extensions(message):
        # Apply extensions before sending
        for ext in client._extensions:
            message = await ext.outgoing(message)
        return await original_send(message)

    client._transport.send = send_with_extensions

    # Mock the protocol's create_handshake_message
    def create_handshake_message(ext=None):
        return Message(
            channel="/meta/handshake",
            ext=ext or {},
            supportedConnectionTypes=["websocket"],
        )

    client._protocol.create_handshake_message = create_handshake_message

    # Test handshake with auth
    handshake_response = Message(
        channel="/meta/handshake", successful=True, client_id="client123", ext={}
    )
    original_send.return_value = handshake_response

    await client.connect()

    # Verify handshake message
    handshake_message = original_send.call_args_list[0][0][0]
    assert handshake_message.channel == "/meta/handshake"
    assert isinstance(handshake_message.ext, dict), f"ext is {handshake_message.ext}"
    assert "auth" in handshake_message.ext, f"ext contents: {handshake_message.ext}"
    assert handshake_message.ext["auth"] == {"token": "test_token"}

    # Verify connect message
    connect_message = original_send.call_args_list[1][0][0]
    assert connect_message.channel == "/meta/connect"
    assert isinstance(connect_message.ext, dict)
    assert not connect_message.ext.get("auth")
