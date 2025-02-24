# PyFaye

An asynchronous Python client for the [Faye](https://faye.jcoglan.com/) publish-subscribe messaging protocol.

## Features

- Asynchronous implementation using `asyncio` and `aiohttp`/`websockets`
- Support for both WebSocket and HTTP Long-Polling transports
- Automatic transport selection and fallback
- Extensible architecture with support for custom extensions
- Channel subscription management
- Message validation and channel validation
- Automatic reconnection with exponential backoff
- Comprehensive error handling and type hints

## Installation

Install using pip:
```bash
pip install pyfaye
```

Or with Poetry:
```bash
poetry add pyfaye
```

## Quick Start

```python
import asyncio
from faye import FayeClient

async def main():
    # Create a client (defaults to WebSocket transport)
    client = FayeClient("http://your-faye-server/faye")
    
    # Connect to server
    await client.connect()
    
    # Subscribe to a channel
    async def message_handler(message):
        print(f"Received message: {message.data}")
    
    await client.subscribe("/some/channel", message_handler)
    
    # Publish a message
    await client.publish("/some/channel", {"message": "Hello, World!"})
    
    # Disconnect when done
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

## Advanced Usage

### Custom Extensions

```python
from faye import Extension, Message

class SigningExtension(Extension):
    def __init__(self, token: str):
        self.token = token

    async def process_outgoing(self, message: Message) -> Message | None:
        """Sign outgoing messages."""
        if not message.ext:
            message.ext = {}
        message.ext["token"] = self.token
        return message

# Create client with extension
client = FayeClient("http://your-faye-server/faye")
client.add_extension(SigningExtension("your-auth-token"))
await client.connect()
```

### Message Batching

```python
from faye import Message

# Create multiple messages
messages = [
    Message("/channel/1", data={"seq": 1}),
    Message("/channel/2", data={"seq": 2})
]

# Send messages in batch
responses = await client.batch(messages)
```

### Transport Selection

```python
# Use HTTP Long-Polling transport
client = FayeClient("http://your-faye-server/faye", transport_type="long-polling")

# Use WebSocket transport (default)
client = FayeClient("http://your-faye-server/faye", transport_type="websocket")
```

## API Reference

### FayeClient

The main client class for interacting with a Faye server.

#### Constructor

```python
FayeClient(
    url: str,
    transport_type: str = "websocket",
    extensions: list[Extension] | None = None
)
```

- `url`: Faye server URL
- `transport_type`: Transport type to use ("websocket" or "long-polling")
- `extensions`: Optional list of extensions to use

#### Properties

- `client_id`: The client ID assigned by the server (read-only)
- `connected`: Whether the client is currently connected (read-only)
- `state`: Current connection state as string (read-only)

#### Methods

- `async connect() -> None`: Connect to the Faye server
- `async disconnect() -> None`: Disconnect from the server
- `async subscribe(channel: str, callback: Callable[[Message], Awaitable[None]]) -> None`: Subscribe to a channel
- `async unsubscribe(channel: str) -> None`: Unsubscribe from a channel
- `async publish(channel: str, data: dict[str, Any] | str) -> None`: Publish data to a channel
- `async batch(messages: list[Message]) -> list[Message | None]`: Send multiple messages in batch
- `add_extension(extension: Extension) -> None`: Add an extension to the client
- `remove_extension(extension: Extension) -> None`: Remove an extension from the client

### Message

The message class representing Faye protocol messages.

```python
Message(
    channel: str,
    client_id: str | None = None,
    data: dict[str, Any] | str | None = None,
    error: str | None = None,
    ext: dict[str, Any] | None = None,
    message_id: str | None = None,
    version: str | None = None,
    minimum_version: str | None = None,
    supported_connection_types: list[str] | None = None,
    connection_type: str | None = None,
    subscription: str | None = None,
    successful: bool | None = None,
    advice: dict[str, Any] | None = None
)
```

#### Factory Methods

- `handshake(ext: dict[str, Any] | None = None) -> Message`
- `connect(client_id: str, connection_type: str = "websocket") -> Message`
- `disconnect(client_id: str) -> Message`
- `subscribe(client_id: str, subscription: str) -> Message`
- `unsubscribe(client_id: str, subscription: str) -> Message`
- `publish(channel: str, data: dict[str, Any], client_id: str) -> Message`

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/mwhobrey/pyfaye.git
cd pyfaye

# Install dependencies
poetry install

# Run tests
poetry run pytest
```

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=faye

# Run specific test file
poetry run pytest tests/transport/test_websocket.py
```

### Code Quality

```bash
# Run all checks
poetry run prerelease

# Format code
poetry run black src/

# Run linter
poetry run ruff check src/

# Run type checker
poetry run pytype src/
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. When contributing:

1. Fork the repository
2. Create a feature branch
3. Add tests for any new functionality
4. Ensure all tests pass and code quality checks succeed
5. Submit a pull request

For bug reports or feature requests, please open an issue on GitHub.
