"""
Generic OpenAI-Compatible Provider — Milestone 10
==================================================
The keystone of M10: a single adapter that speaks the OpenAI Chat Completions
API against ANY OpenAI-compatible endpoint. One instance is built per active
row in AI/System/Provider-Registry.md — no Python file per provider.

Constructed from a ModelSpec (which carries base_url + model_id) plus the
matching API key. Uses the `openai` SDK with base_url=<row.base_url>.

Adding a provider is now a Markdown edit, not a new class.

Install: pip install openai
"""

import logging

from assistant_core.providers.base_provider import (
    BaseProvider,
    Message,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)
from assistant_core.providers.model_registry import ModelSpec

logger = logging.getLogger("assistant")


class OpenAICompatibleProvider(BaseProvider):
    """Adapter for any OpenAI-compatible endpoint, built from a registry row."""

    def __init__(self, spec: ModelSpec, api_key: str, config: dict | None = None):
        """
        Args:
            spec:    The registry ModelSpec — supplies base_url, model_id, provider name.
            api_key: The API key read from settings as '<provider_key>_api_key'.
            config:  The full settings dict (kept for BaseProvider compatibility).
        """
        super().__init__(config or {})

        self._name     = spec.provider
        self._model    = spec.model_id
        self._base_url = spec.base_url

        api_key = (api_key or "").strip()
        if not api_key:
            raise ProviderAuthError(
                f"{self._name} API key is missing.\n"
                f"Add it to config/settings.json under '{self._name}_api_key'."
            )

        if not self._base_url:
            raise ProviderError(
                f"{self._name} has no base_url in the provider registry — cannot build adapter."
            )

        # Import here so the rest of the app works even if openai isn't installed.
        try:
            from openai import OpenAI
        except ImportError:
            raise ProviderError(
                "The 'openai' library is not installed.\n"
                "Run: pip install openai"
            )

        # Per-request timeout (config `request_timeout`, default 45s) + fail fast so a
        # hung/slow provider raises and the router falls back instead of stalling the turn.
        timeout = (config or {}).get("request_timeout", 45)
        self._client = OpenAI(api_key=api_key, base_url=self._base_url,
                              timeout=timeout, max_retries=1)

    @property
    def name(self) -> str:
        return self._name

    def generate(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Send messages to the OpenAI-compatible endpoint and return the reply text."""

        # Build the message list in the format the Chat Completions API expects.
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            api_messages.append({"role": msg.role, "content": msg.content})

        logger.info(
            f"[{self._name}] Sending request — model: {self._model}, "
            f"messages: {len(api_messages)} (base_url={self._base_url})"
        )

        # Import the typed exception classes locally — keeps module import light
        # and avoids a hard dependency at module load time.
        from openai import (
            APIStatusError,
            AuthenticationError,
            RateLimitError,
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=api_messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            reply = response.choices[0].message.content
            logger.info(f"[{self._name}] Response received — {len(reply or '')} characters")
            return reply or ""   # content can be None (length cap / content filter) — return a string

        except AuthenticationError as exc:
            logger.error(f"[{self._name}] Auth error: {exc}")
            raise ProviderAuthError(
                f"{self._name} rejected the API key. "
                f"Check config/settings.json → '{self._name}_api_key'."
            ) from exc

        except RateLimitError as exc:
            logger.warning(f"[{self._name}] Rate limit hit: {exc}")
            raise ProviderRateLimitError(
                f"{self._name} rate limit reached."
            ) from exc

        except APIStatusError as exc:
            status = getattr(exc, "status_code", None)
            if status == 401:
                logger.error(f"[{self._name}] Auth error (401): {exc}")
                raise ProviderAuthError(
                    f"{self._name} rejected the API key (401). "
                    f"Check config/settings.json → '{self._name}_api_key'."
                ) from exc
            if status == 429:
                logger.warning(f"[{self._name}] Rate limit (429): {exc}")
                raise ProviderRateLimitError(
                    f"{self._name} rate limit reached (429)."
                ) from exc
            logger.error(f"[{self._name}] API error (status={status}): {exc}")
            raise ProviderError(f"{self._name} error (status={status}): {exc}") from exc

        except Exception as exc:
            logger.error(f"[{self._name}] Unexpected error: {exc}")
            raise ProviderError(f"{self._name} error: {exc}") from exc

    def describe_image(self, image_b64: str, mime: str, prompt: str,
                       max_tokens: int = 1024) -> str:
        """M19 — one vision call: send a base64 image + prompt to this (multimodal)
        model using the OpenAI vision message format. Returns the model's text."""
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                    ],
                }],
                max_tokens=max_tokens,
                temperature=0.2,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning(f"[{self._name}] Vision call failed: {exc}")
            raise ProviderError(f"{self._name} vision error: {exc}") from exc
