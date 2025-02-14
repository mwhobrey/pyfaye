"""PyFaye - An asynchronous Python client for the Faye pub/sub messaging protocol.

Basic usage:
    >>> from faye import FayeClient
    >>> client = FayeClient("http://your-faye-server/faye")
    >>> await client.connect()
    >>> await client.subscribe("/channel", callback)
"""

from .client import FayeClient
from .exceptions import (
    AuthenticationError,
    ConnectionError,
    FayeError,
    HandshakeError,
    TransportError,
)
from .extensions.authentication import AuthenticationExtension
from .extensions.base import Extension
from .protocol import Message

__version__ = "0.1.0"
__all__ = [
    # Main client
    "FayeClient",
    # Protocol
    "Message",
    # Extensions
    "Extension",
    "AuthenticationExtension",
    # Exceptions
    "FayeError",
    "AuthenticationError",
    "TransportError",
    "HandshakeError",
    "ConnectionError",
]
