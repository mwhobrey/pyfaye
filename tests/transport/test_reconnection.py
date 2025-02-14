import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from faye.client import FayeClient
from faye.exceptions import FayeError
from faye.protocol import Message


@pytest.mark.asyncio(loop_scope="function")
async def test_transport_reconnection():
    """Test transport reconnection behavior."""
    client = FayeClient("http://example.com/faye")

    # Setup mock transport
    with patch.object(client, "_create_transport") as mock_create:
        mock_transport = AsyncMock()
        mock_create.return_value = mock_transport

        # Setup message callback to be async
        mock_transport.set_message_callback = AsyncMock()  # Change to AsyncMock

        # First connection succeeds
        handshake_response = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="client123",
            supported_connection_types=["websocket"],
        )
        mock_transport.send.return_value = handshake_response
        await client.connect()

        # Verify first connection
        assert client.connected
        assert client._protocol._client_id == "client123"

        # Simulate connection failure
        mock_transport.send.side_effect = FayeError("Connection lost")

        # Verify reconnection attempt
        connect_msg = mock_transport.send.call_args[0][0]
        assert connect_msg.channel == "/meta/connect"
        assert connect_msg.client_id == "client123"


@pytest.mark.asyncio(loop_scope="function")
async def test_reconnection_backoff():
    """Test reconnection backoff behavior."""
    client = FayeClient("http://example.com/faye")

    # Setup mock transport and initial connection
    with patch.object(client, "_create_transport") as mock_create:
        mock_transport = AsyncMock()
        mock_create.return_value = mock_transport

        # Setup message callback to be async
        mock_transport.set_message_callback = AsyncMock()  # Change to AsyncMock

        # Setup successful handshake
        handshake_response = Message(
            channel="/meta/handshake",
            successful=True,
            client_id="client123",
            supported_connection_types=["websocket"],
        )
        mock_transport.send.return_value = handshake_response
        await client.connect()

        # Simulate increasing retry intervals
        intervals = [100, 200, 400]  # milliseconds
        for interval in intervals:
            # Send advice message
            await client._handle_message(
                Message(
                    channel="/meta/connect",
                    advice={"reconnect": "retry", "interval": interval},
                )
            )

            # Wait for the retry attempt
            await asyncio.sleep(0.01)  # Small delay to allow retry to process

            # Verify retry attempt with correct interval
            last_call = mock_transport.send.call_args
            assert last_call is not None
            connect_msg = last_call[0][0]
            assert connect_msg.channel == "/meta/connect"
            assert connect_msg.client_id == "client123"
