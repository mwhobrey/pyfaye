# PyFaye

An asynchronous Python client for the [Faye](https://faye.jcoglan.com/) publish-subscribe messaging protocol.

## Features

- Asynchronous implementation using `asyncio` and `aiohttp`/`websockets`
- Support for both WebSocket and HTTP Long-Polling transports
- Automatic transport selection and fallback
- Extensible architecture with support for custom extensions
- Built-in authentication extension
- Channel subscription management
- Message validation and channel validation
- Comprehensive test coverage

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
    # Create a client
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

### Authentication

```python
from faye import FayeClient
from faye.extensions.authentication import AuthenticationExtension

# Create client with authentication
client = FayeClient("http://your-faye-server/faye")
auth = AuthenticationExtension("your-auth-token")
client.add_extension(auth)

await client.connect()
```

### Custom Extensions

```python
from faye.extensions.base import Extension
from faye.protocol import Message
from typing import Optional

class LoggingExtension(Extension):
    async def outgoing(self, message: Message) -> Optional[Message]:
        print(f"Outgoing: {message}")
        return message
    
    async def incoming(self, message: Message) -> Optional[Message]:
        print(f"Incoming: {message}")
        return message

client = FayeClient("http://your-faye-server/faye")
client.add_extension(LoggingExtension())
```

## API Reference

### FayeClient

- `FayeClient(url: str, **options)`
  - `url`: Faye server URL
  - `options`:
    - `connection_types`: List of supported connection types (default: ["websocket", "long-polling"])
    - `retry_delay`: Delay between retries in seconds (default: 1.0)
    - `timeout`: Request timeout in seconds (default: 120.0)

#### Methods

- `connect() -> None`: Connect to the Faye server
- `disconnect() -> None`: Disconnect from the server
- `subscribe(channel: str, callback: Callable) -> None`: Subscribe to a channel
- `unsubscribe(channel: str) -> None`: Unsubscribe from a channel
- `publish(channel: str, data: Any) -> None`: Publish data to a channel
- `add_extension(extension: Extension) -> None`: Add an extension to the client

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/pyfaye.git
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
poetry run pytest tests/protocol/test_bayeux.py
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
