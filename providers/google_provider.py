"""
Google AI Provider
Connects to Google AI Studio (Gemini) via the NEW google-genai SDK.

IMPORTANT: google-generativeai is deprecated as of 2026.
The correct package is now: google-genai

Free models (as of June 2026):
    gemini-2.5-flash      -- best free all-rounder, 1M context
    gemini-3.5-flash      -- newest, higher quality (may have lower free quota)
    gemini-2.5-flash-lite -- cheapest, fastest

Free tier limits:
    15 requests/minute
    ~1,000,000 tokens/day (2.5 Flash)

Install: pip install google-genai
Get a free key at: https://aistudio.google.com/app/apikey
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


class GoogleProvider(BaseProvider):
    """Adapter for Google AI Studio (Gemini) using the google-genai SDK."""

    def __init__(self, config: dict):
        super().__init__(config)

        api_key = config.get("google_api_key", "").strip()
        if not api_key:
            raise ProviderAuthError(
                "Google API key is missing.\n"
                "Add it to config/settings.json under 'google_api_key'.\n"
                "Get a free key at https://aistudio.google.com/app/apikey"
            )

        try:
            from google import genai
            from google.genai import types as genai_types
        except ImportError:
            raise ProviderError(
                "The 'google-genai' library is not installed.\n"
                "Run: pip install google-genai\n"
                "Note: the OLD package 'google-generativeai' is deprecated."
            )

        self._client = genai.Client(api_key=api_key)
        self._types = genai_types
        self._model_name = config.get("google_model", "gemini-2.5-flash")

    @property
    def name(self) -> str:
        return "Google"

    def generate(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        """Send messages to Gemini and return the response text."""

        logger.info(f"[Google] Sending request — model: {self._model_name}, messages: {len(messages)}")

        try:
            # Build the contents list — Gemini uses "user" and "model" roles
            contents = []
            for msg in messages:
                gemini_role = "model" if msg.role == "assistant" else "user"
                contents.append(
                    self._types.Content(
                        role=gemini_role,
                        parts=[self._types.Part(text=msg.content)]
                    )
                )

            # Build config
            generate_config = self._types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
            if system_prompt:
                generate_config.system_instruction = system_prompt

            response = self._client.models.generate_content(
                model=self._model_name,
                contents=contents,
                config=generate_config,
            )

            reply = response.text
            logger.info(f"[Google] Response received — {len(reply)} characters")
            return reply

        except Exception as exc:
            error_text = str(exc).lower()

            if "quota" in error_text or "rate" in error_text or "429" in error_text or "resource_exhausted" in error_text:
                logger.warning(f"[Google] Rate limit hit: {exc}")
                raise ProviderRateLimitError(
                    "Google AI rate limit reached."
                ) from exc

            if "api key" in error_text or "401" in error_text or "permission" in error_text or "unauthenticated" in error_text:
                logger.error(f"[Google] Auth error: {exc}")
                raise ProviderAuthError(
                    "Google rejected the API key. Check config/settings.json → 'google_api_key'."
                ) from exc

            if "404" in error_text or "not found" in error_text:
                logger.error(f"[Google] Model not found: {exc}")
                raise ProviderError(
                    f"Google model '{self._model_name}' not found.\n"
                    f"Update 'google_model' in settings.json. Current valid models: gemini-2.5-flash, gemini-3.5-flash"
                ) from exc

            logger.error(f"[Google] Unexpected error: {exc}")
            raise ProviderError(f"Google AI error: {exc}") from exc

    def generate_with_retry(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        retries: int = 3,
        wait_seconds: int = 60,
    ) -> str:
        """Retry on rate-limit errors with a wait between attempts."""
        for attempt in range(1, retries + 1):
            try:
                return self.generate(messages, system_prompt, max_tokens, temperature)
            except ProviderRateLimitError:
                if attempt < retries:
                    print(f"\n[Google] Rate limit hit. Waiting {wait_seconds}s before retry {attempt}/{retries - 1}...")
                    time.sleep(wait_seconds)
                else:
                    print("\n[Google] Rate limit hit. All retries exhausted.")
                    raise
