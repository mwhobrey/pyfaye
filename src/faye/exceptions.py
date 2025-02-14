class FayeError(Exception):
    """Base exception class for all Faye client errors.

    This is the parent class for all custom exceptions raised by the Faye client.
    Catch this to handle any Faye-related error.

    Example:
    -------
        >>> try:
        ...     await client.connect()
        ... except FayeError as e:
        ...     print(f"Faye error occurred: {e}")

    """

    pass


class TransportError(FayeError):
    """Error in transport layer communication.

    Raised when there are network-level issues or problems with
    the transport connection (WebSocket/HTTP).

    Example:
    -------
        >>> try:
        ...     await client.connect()
        ... except TransportError as e:
        ...     print(f"Transport error: {e}")
        ...     # Maybe try a different transport type

    """

    pass


class ProtocolError(FayeError):
    """Error in Bayeux protocol handling.

    Raised when there are protocol-level issues such as invalid
    message format or unsupported protocol version.

    Example:
    -------
        >>> try:
        ...     await client.publish("/foo", data)
        ... except ProtocolError as e:
        ...     print(f"Protocol error: {e}")

    """

    pass


class HandshakeError(FayeError):
    """Error during protocol handshake process.

    Raised when the initial protocol handshake with the server fails.
    This could be due to version mismatch, server rejection, etc.

    Example:
    -------
        >>> try:
        ...     await client.connect()
        ... except HandshakeError as e:
        ...     print(f"Handshake failed: {e}")
        ...     # Maybe check server compatibility

    """

    pass


class ConnectionError(ProtocolError):
    """Error maintaining connection with server.

    Raised when an established connection fails or when
    connection attempts are rejected by the server.

    Example:
    -------
        >>> try:
        ...     await client.connect()
        ... except ConnectionError as e:
        ...     print(f"Connection failed: {e}")
        ...     # Maybe implement retry logic

    """

    pass


class SubscriptionError(ProtocolError):
    """Error managing channel subscriptions.

    Raised when subscription operations (subscribe/unsubscribe) fail.
    This could be due to invalid channels or server rejection.

    Example:
    -------
        >>> try:
        ...     await client.subscribe("/private/**", callback)
        ... except SubscriptionError as e:
        ...     print(f"Subscription failed: {e}")
        ...     # Maybe check channel permissions

    """

    pass


class AuthenticationError(FayeError):
    """Error during client authentication.

    Raised when authentication with the server fails.
    This could be due to invalid credentials or expired tokens.

    Example:
    -------
        >>> try:
        ...     auth = AuthenticationExtension("invalid-token")
        ...     client.add_extension(auth)
        ...     await client.connect()
        ... except AuthenticationError as e:
        ...     print(f"Authentication failed: {e}")
        ...     # Maybe refresh token and retry

    """

    pass
