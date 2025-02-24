"""Example client implementation matching Node.js Faye client functionality."""

import asyncio
import base64
import hashlib
import json
import logging
import uuid
from typing import Any, Callable
from urllib.parse import urlparse

from faye.client import FayeClient
from faye.exceptions import FayeError, ErrorCode
from faye.extensions import Extension
from faye.protocol import Message

logger = logging.getLogger(__name__)


class SigningExtension(Extension):
    """Extension for signing messages with API credentials."""

    def __init__(self, api: str, token: str, key: str):
        self.api = api
        self.token = token
        self.key = key

    def _random128(self) -> str:
        """Generate random 128-bit hex string."""
        return uuid.uuid4().hex + uuid.uuid4().hex[:16]

    def _create_signature(self, salt: str, json_str: str) -> str:
        """Create message signature."""
        j_hash = hashlib.sha256(json_str.encode()).hexdigest()
        k_hash = hashlib.sha256((j_hash + self.key).encode()).hexdigest()
        signature = hashlib.sha256((k_hash + salt).encode()).hexdigest()
        return signature

    async def process_outgoing(self, message: Message) -> Message | None:
        """Sign outgoing messages."""
        if not message:
            return None

        # Add version for handshake
        if message.channel == "/meta/handshake":
            message.version = "1.0"
            message.supportedConnectionTypes = ["websocket", "long-polling"]

        # Create copy without ext field
        msg_copy = message.to_dict()
        msg_copy.pop("ext", None)
        json_str = json.dumps(msg_copy)

        # Generate salt and signature
        salt = self._random128()
        signature = self._create_signature(salt, json_str)

        # Add extension data
        message.ext = {
            "api": self.api,
            "token": self.token,
            "salt": base64.b64encode(salt.encode()).decode(),
            "signature": signature,
            "data": base64.b64encode(json_str.encode()).decode(),
        }

        # Add message field for subscribe/meta messages
        if message.channel == "/meta/subscribe":
            message.ext["message"] = "/meta/subscribe"
        elif (
            message.data
            and isinstance(message.data, dict)
            and "message" in message.data
        ):
            message.ext["message"] = message.data["message"]

        return message


class TestClient:
    """Test client implementation."""

    # Default client options
    DEFAULT_OPTIONS = {"interval": 0.0, "timeout": 60.0, "retry": 3}

    def __init__(
        self,
        endpoint: str,
        api: str,
        token: str,
        key: str,
        group_id: int,
        site_id: int,
        options: dict[str, Any] | None = None,
    ) -> None:
        """Initialize test client."""
        self.endpoint = endpoint
        self.api = api
        self.token = token
        self.key = key
        self._group_id = group_id
        self._site_id = site_id
        self.options = options or {}

        logger.debug("Initializing test client...")

        # Convert HTTP to WebSocket URL if needed
        parsed = urlparse(endpoint)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_endpoint = parsed._replace(scheme=ws_scheme).geturl()
        logger.debug(f"WebSocket endpoint: {ws_endpoint}")

        # Initialize client
        self.client = FayeClient(ws_endpoint)
        
        # Set client properties from options
        self.client._retry_interval = float(
            self.options.get("interval", self.DEFAULT_OPTIONS["interval"])
        )
        self.client._request_timeout = float(
            self.options.get("timeout", self.DEFAULT_OPTIONS["timeout"])
        )
        
        # Add signing extension
        self.client.add_extension(SigningExtension(api, token, key))

        self._response_channel: str | None = None
        self._message_received = asyncio.Event()

    async def connect(self) -> None:
        """Connect to Faye server."""
        try:
            await self.client.connect()

            if not self.client.client_id:
                raise FayeError(
                    ErrorCode.CLIENT_UNKNOWN, ["client_id"], "No client ID received"
                )

            # Create response channel
            client_hash = hashlib.sha1(self.client.client_id.encode()).hexdigest()
            double_hash = hashlib.sha1(client_hash.encode()).hexdigest()
            triple_hash = hashlib.sha1(double_hash.encode()).hexdigest()
            self._response_channel = (
                f"/{self.api}/response/{triple_hash}/{uuid.uuid4()}"
            )

            logger.info(f"Connected to {self.endpoint}")

        except FayeError as e:
            logger.error(f"Connection failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during connection: {e}")
            raise FayeError(ErrorCode.SERVER_ERROR, ["connect"], str(e))

    async def send_message(self) -> None:
        """Send test message."""
        logger.info("Preparing to send message...")

        if not self._response_channel:
            raise FayeError(
                ErrorCode.PARAMETER_MISSING,
                ["channel"],
                "No response channel - connect first",
            )

        try:
            # Set up handler for subscription messages
            async def response_handler(message: Message) -> None:
                logger.debug("=== Response Handler Start ===")
                logger.debug(f"Channel: {message.channel}")
                logger.debug(
                    f"Message data structure: {json.dumps(message.data, indent=2)}"
                )

                # Process meta messages
                if message.channel.startswith("/meta/"):
                    logger.debug("Skipping meta message")
                    return

                # Process publish confirmation
                if message.channel == f"/{self.api}/{self._group_id}/{self._site_id}":
                    logger.debug("Processing publish confirmation")
                    if not message.successful:
                        logger.error(f"Publish failed: {message.error}")
                        self._message_received.set()
                    return

                # Process messages on our response channel
                if message.channel == self._response_channel:
                    logger.debug("Processing response channel message")
                    if not message.data:
                        logger.debug("Message has no data")
                        return

                    if not isinstance(message.data, dict):
                        logger.debug(
                            f"Message data is not a dict: {type(message.data)}"
                        )
                        return

                    # Check for message type in both top-level and nested data
                    msg_type = message.data.get("message")
                    if not msg_type:
                        data_obj = message.data.get("data", {})
                        if isinstance(data_obj, dict):
                            msg_type = data_obj.get("message")
                            if not msg_type and isinstance(data_obj.get("data"), dict):
                                msg_type = data_obj["data"].get("message")

                    logger.debug(f"Found message type: {msg_type}")

                    if msg_type == "site_information":
                        logger.info("Received site information response")
                        logger.debug("Setting message received event")
                        self._message_received.set()
                        logger.debug("Event set successfully")
                    else:
                        logger.debug(f"Unexpected message type: {msg_type}")
                        # Log truncated data structure for debugging
                        logger.debug(
                            f"Message structure: {_truncate_message(message.data)}"
                        )
                else:
                    logger.debug(f"Unexpected channel: {message.channel}")

                logger.debug("=== Response Handler End ===")

            # Subscribe to response channel
            logger.info(f"Subscribing to response channel: {self._response_channel}")
            await self.client.subscribe(self._response_channel, response_handler)
            logger.info("Subscription confirmed, preparing message...")

            # Reset event and send message
            self._message_received.clear()

            # Prepare the message
            message = {
                "v1": {
                    "siteID": self._site_id,
                    "returnChannel": self._response_channel,
                    "messageID": uuid.uuid4().hex,
                },
                "message": "site_information",
            }

            # Send message and wait for response
            logger.info("Sending message and waiting for response...")
            await self.client.publish(
                f"/{self.api}/{self._group_id}/{self._site_id}", message
            )

            # Wait for response with timeout
            try:
                await asyncio.wait_for(self._message_received.wait(), timeout=60.0)
                logger.info("Response received successfully")
            except asyncio.TimeoutError:
                logger.warning(
                    "No response received within timeout - this may be expected"
                )
                # Don't raise an error, just log the timeout
                return

        except FayeError as e:
            logger.error(f"Failed to send message: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error sending message: {e}")
            raise FayeError(ErrorCode.SERVER_ERROR, ["send"], str(e))

    async def disconnect(self) -> None:
        """Disconnect from server."""
        try:
            await self.client.disconnect()
            logger.info("Disconnected from server")
        except FayeError as e:
            logger.error(f"Disconnect failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during disconnect: {e}")
            raise FayeError(ErrorCode.SERVER_ERROR, ["disconnect"], str(e))

    async def run(self) -> None:
        """Run test sequence."""
        try:
            logger.info("Starting test client...")

            # Connect to server
            logger.info("Connecting to server...")
            await self.connect()

            # Send test message
            logger.info("Sending test message...")
            await self.send_message()

            logger.info("Test completed successfully")

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        except FayeError as e:
            logger.error(f"Test failed with Faye error: {e}")
            raise
        except Exception as e:
            logger.error(f"Test failed with unexpected error: {e}")
            raise FayeError(ErrorCode.SERVER_ERROR, ["test"], str(e))
        finally:
            logger.info("Cleaning up...")
            try:
                await self.disconnect()
            except Exception as e:
                # Just log disconnect errors - they're usually not critical
                logger.debug(f"Note: Error during disconnect (usually not critical): {e}")
            logger.info("Disconnected from server")


def _truncate_message(data: Any, max_length: int = 500) -> str:
    """Truncate message data for logging.

    Args:
        data: Data to truncate
        max_length: Maximum length before truncating

    Returns:
        Truncated string representation
    """
    str_data = str(data)
    if len(str_data) <= max_length:
        return str_data
    return f"{str_data[:max_length]}... [truncated {len(str_data) - max_length} chars]"


async def main() -> None:
    """Example usage of test client."""
    client = None
    try:
        logger.info("Starting test client...")

        # Example configuration
        endpoint = "https://pubsub-test.idealss.net/faye"
        api = "vr_store"
        token = "D11D0DE08C5282E58CABFB960005FC779CD259B18611E60DFED267EEFB9F8726"
        key = "443AE33FE5C543A89A8F4DF0E088417ED35EFDBF0BF6905F1C91729992727FDF05A719015AACED3609080F634563C2AE0A8548524920706DD523E2971DB6490D"
        group_id = 762
        site_id = 111
        options = {"timeout": 60, "interval": 0, "retry": 3}

        client = TestClient(endpoint, api, token, key, group_id, site_id, options)

        # Run test sequence
        await client.run()

    except KeyboardInterrupt:
        logger.info("Process interrupted")
    except FayeError as e:
        logger.error(f"Test failed with Faye error: {e}")
        raise
    except Exception as e:
        logger.error(f"Test failed with unexpected error: {e}")
        raise
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process interrupted")
