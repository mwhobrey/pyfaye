from unittest.mock import AsyncMock

import pytest
from faye import FayeClient
from faye.exceptions import HandshakeError
from faye.protocol import Message


@pytest.mark.asyncio
async def test_version_negotiation():
    """Test protocol version negotiation during handshake."""
    client = FayeClient("http://example.com/faye")
    client._transport = AsyncMock()

    # Test supported version
    response = Message(
        channel="/meta/handshake",
        successful=True,
        client_id="client123",
        version="1.0",
        supportedConnectionTypes=["websocket"],
    )
    await client._protocol.process_handshake_response(response)
    assert client._protocol.is_handshaken

    # Test unsupported version
    response = Message(
        channel="/meta/handshake",
        successful=False,
        error="Version 2.0 not supported",
        supportedVersions=["1.0"],
    )
    with pytest.raises(HandshakeError, match="Version 2.0 not supported"):
        await client._protocol.process_handshake_response(response)


@pytest.mark.asyncio
async def test_minimum_version_handling():
    """Test minimum version handling during handshake."""
    client = FayeClient("http://example.com/faye")
    client._transport = AsyncMock()

    # Create a proper Message response with a dictionary for advice
    handshake_response = Message(
        channel="/meta/handshake",
        successful=True,
        version="1.0",
        supportedConnectionTypes=["websocket"],
        client_id="client123",
        minimum_version="1.0",
        advice={"reconnect": "retry", "interval": 1000},
    )

    # Setup the mock transport
    client._transport.send.return_value = handshake_response

    await client.connect()

    # Verify the handshake message
    handshake_call = client._transport.send.call_args_list[0]
    handshake_msg = handshake_call[0][0]
    assert handshake_msg.minimum_version == "1.0"
    assert handshake_msg.version == "1.0"


@pytest.mark.asyncio
async def test_version_mismatch():
    """Test version mismatch handling."""
    client = FayeClient("http://example.com/faye")
    client._transport = AsyncMock()

    # Server requires higher minimum version
    response = Message(
        channel="/meta/handshake",
        successful=False,
        error="Minimum version 1.1 required",
        minimum_version="1.1",
    )
    with pytest.raises(HandshakeError, match="Minimum version 1.1 required"):
        await client._protocol.process_handshake_response(response)
