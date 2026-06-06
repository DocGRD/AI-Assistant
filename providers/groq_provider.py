"""
Groq Provider
Connects to Groq's API using the official groq Python SDK.

Free models (as of mid-2026):
    llama3-70b-8192
    llama3-8b-8192
    mixtral-8x7b-32768
    gemma2-9b-it

Rate limits (free tier):
    ~30 requests/minute
    ~14,400 requests/day

Install: pip install groq
"""

import time
import logging

from providers.base_provider import (
    BaseProvider,
    Message,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)

logger = logging.getLogger("assistant")


class GroqProvider(BaseProvider):
    """Adapter for the Groq API."""

    def __init__(self, config: dict):
        super().__init__(config)

        api_key = config.get("groq_api_key", "").strip()
        if not api_key:
            raise ProviderAuthError(
                "Groq API key is missing.\n"
                "Add it to config/settings.json under 'groq_api_key'.\n"
                "Get a free key at https://console.groq.com"
            )

        # Import here so the rest of the app works even if groq isn't installed
        try:
            from groq import Groq
        except ImportError:
            raise ProviderError(
                "The 'groq' library is not installed.\n"
                "Run: pip install groq"
            )

        self._client = Groq(api_key=api_key)
        self._model = config.get("groq_model", "llama3-70b-8192")

    @property
    def name(self) -> str:
        return "Groq"

    def generate(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        """Send messages to Groq and return the response text."""

        # Build the message list in the format Groq expects
        groq_messages = []

        if system_prompt:
            groq_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            groq_messages.append({"role": msg.role, "content": msg.content})

        logger.info(f"[Groq] Sending request — model: {self._model}, messages: {len(groq_messages)}")

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=groq_messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            reply = response.choices[0].message.content
            logger.info(f"[Groq] Response received — {len(reply)} characters")
            return reply

        except Exception as exc:
            error_text = str(exc).lower()

            # Rate limit detection
            if "rate limit" in error_text or "429" in error_text or "quota" in error_text:
                logger.warning(f"[Groq] Rate limit hit: {exc}")
                raise ProviderRateLimitError(
                    "Groq rate limit reached. The assistant will wait and retry."
                ) from exc

            # Auth errors
            if "401" in error_text or "invalid api key" in error_text or "authentication" in error_text:
                logger.error(f"[Groq] Auth error: {exc}")
                raise ProviderAuthError(
                    "Groq rejected the API key. Check config/settings.json → 'groq_api_key'."
                ) from exc

            # Anything else
            logger.error(f"[Groq] Unexpected error: {exc}")
            raise ProviderError(f"Groq error: {exc}") from exc

    def generate_with_retry(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        retries: int = 3,
        wait_seconds: int = 60,
    ) -> str:
        """
        Calls generate() with automatic retry on rate-limit errors.
        On each rate-limit hit it waits wait_seconds before retrying.
        """
        for attempt in range(1, retries + 1):
            try:
                return self.generate(messages, system_prompt, max_tokens, temperature)
            except ProviderRateLimitError:
                if attempt < retries:
                    print(f"\n[Groq] Rate limit hit. Waiting {wait_seconds}s before retry {attempt}/{retries - 1}...")
                    time.sleep(wait_seconds)
                else:
                    print("\n[Groq] Rate limit hit. All retries exhausted.")
                    raise
