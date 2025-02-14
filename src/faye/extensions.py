"""Extensions module for Faye client."""

from faye.extensions.authentication import AuthenticationExtension
from faye.extensions.base import Extension

__all__ = ["Extension", "AuthenticationExtension"]
