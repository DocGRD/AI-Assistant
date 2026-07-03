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
            ProviderRateLimitError:  if the provider throttles the request.
            ProviderAuthError:       if the API key is missing or invalid.
            ProviderWebUIHandoff:    if the WebUI virtual provider is selected.
                                     NOT a subclass of ProviderError — callers
                                     must handle this separately.
            ProviderError:           for any other provider-side failure.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name used in logs."""
        ...


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class ProviderError(Exception):
    """Base class for all provider errors (auth, rate-limit, generic)."""


class ProviderRateLimitError(ProviderError):
    """Raised when a provider returns a rate-limit / quota error."""


class ProviderAuthError(ProviderError):
    """Raised when the API key is missing or rejected."""


class ProviderWebUIHandoff(Exception):
    """
    Raised by WebUIProvider when the user has chosen (or been routed to)
    the web UI mode.  This is NOT a subclass of ProviderError — it is a
    successful routing decision, not a failure.

    The router does NOT catch this; it propagates directly to the caller
    (terminal chat loop, HTTP server, or vault watcher) so each can handle
    the handoff in the way appropriate for its interface.

    Attributes:
        packaged_prompt: Complete context block ready to paste into any
                         web AI (ChatGPT, Claude, Gemini, DeepSeek, etc.)
    """

    def __init__(self, packaged_prompt: str):
        self.packaged_prompt = packaged_prompt
        super().__init__("Web UI handoff required")
