"""Extensions package for Faye client."""

from .authentication import AuthenticationExtension
from .base import Extension

__all__ = ["Extension", "AuthenticationExtension"]
