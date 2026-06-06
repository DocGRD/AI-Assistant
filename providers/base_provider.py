"""
Base Provider
Every AI provider adapter must inherit from this class.
Adding a new provider = subclass this, implement generate().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Message:
    """A single message in a conversation."""
    role: str       # "user" | "assistant" | "system"
    content: str


class BaseProvider(ABC):
    """Abstract base class for AI provider adapters."""

    def __init__(self, config: dict):
        """
        config: the full settings dict from ConfigManager.
        Each provider pulls only the keys it needs.
        """
        self.config = config

    @abstractmethod
    def generate(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        """
        Send messages to the provider and return the response text.

        Args:
            messages:      Conversation history (oldest first).
            system_prompt: Optional system-level instruction.
            max_tokens:    Maximum tokens in the response.
            temperature:   Sampling temperature (0.0 = deterministic).

        Returns:
            The assistant's reply as a plain string.

        Raises:
            ProviderRateLimitError: if the provider throttles the request.
            ProviderAuthError:      if the API key is missing or invalid.
            ProviderError:          for any other provider-side failure.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name used in logs."""
        ...


# ---------------------------------------------------------------------------
# Custom exceptions — lets the router handle errors without importing
# provider-specific libraries.
# ---------------------------------------------------------------------------

class ProviderError(Exception):
    """Base class for all provider errors."""


class ProviderRateLimitError(ProviderError):
    """Raised when a provider returns a rate-limit / quota error."""


class ProviderAuthError(ProviderError):
    """Raised when the API key is missing or rejected."""
