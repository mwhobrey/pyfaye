"""Faye client extensions package."""

from .base import Extension
from .auth import AuthenticationExtension
from .logging import LoggingExtension
from .timeout import TimeoutExtension
from .retry import RetryExtension

__all__ = [
    "Extension",
    "AuthenticationExtension",
    "LoggingExtension",
    "TimeoutExtension",
    "RetryExtension",
]
