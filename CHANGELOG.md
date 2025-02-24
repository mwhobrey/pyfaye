# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2024-02-24

### Added
- Initial release of PyFaye
- Asynchronous Faye client implementation using asyncio
- Support for WebSocket and HTTP Long-Polling transports
- Automatic transport selection with configurable type
- Channel subscription management
- Message validation and channel validation
- Extension system for customizing client behavior
- Message batching support
- Comprehensive test suite with 72% coverage
- Full async/await support
- Type hints throughout codebase
- Automatic reconnection with exponential backoff

### Supported Features
- Bayeux/Faye protocol implementation
- Handshake and connection management
- Subscribe/unsubscribe operations
- Message publishing and batching
- Channel validation
- Extension pipeline
- Transport abstraction layer
- Error handling and recovery
- Automatic reconnection
- Configurable retry intervals and timeouts

[0.1.0]: https://github.com/mwhobrey/pyfaye/releases/tag/v0.1.0 