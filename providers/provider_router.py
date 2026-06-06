"""
Provider Router — Milestone 4 upgrade
======================================
Now consults ModelRegistry before every request to:
  1. Estimate token count proactively (prevents 413 errors)
  2. Skip providers that can't handle the request size
  3. Skip providers with recent rate-limit hits
  4. Record all errors so future requests route better

The rest of the codebase is unchanged — it still calls router.generate().
"""

import logging
from providers.base_provider import (
    BaseProvider,
    Message,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)
from providers.groq_provider   import GroqProvider
from providers.google_provider import GoogleProvider
from providers.model_registry  import ModelRegistry, estimate_tokens

logger = logging.getLogger("assistant")

# Add new providers here only — nothing else needs to change
_PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {
    "groq":   GroqProvider,
    "google": GoogleProvider,
}


class ProviderRouter:
    """
    Routes generate() calls to the best available provider.

    Routing decision order (Milestone 4):
        1. Estimate token count for the full request.
        2. Ask ModelRegistry which provider can handle it.
        3. Try that provider; on any error, record it and try the next.
        4. If all providers fail, raise ProviderError.
    """

    def __init__(self, config: dict):
        self._config        = config
        self._default_name  = config.get("default_provider",  "groq").lower()
        self._fallback_name = config.get("fallback_provider", "google").lower()
        self._max_tokens    = config.get("max_tokens",   2048)
        self._temperature   = config.get("temperature",  0.7)

        self._providers: dict[str, BaseProvider] = {}
        self._registry = ModelRegistry()
        self._init_providers()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_providers(self) -> None:
        for name in [self._default_name, self._fallback_name]:
            if name in self._providers:
                continue
            cls = _PROVIDER_CLASSES.get(name)
            if cls is None:
                logger.warning(f"[Router] Unknown provider '{name}' — skipping.")
                continue
            try:
                self._providers[name] = cls(self._config)
                logger.info(f"[Router] Provider ready: {name}")
            except ProviderAuthError as exc:
                logger.warning(f"[Router] {name} skipped — auth error: {exc}")
            except ProviderError as exc:
                logger.warning(f"[Router] {name} skipped — error: {exc}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        mt   = max_tokens  if max_tokens  is not None else self._max_tokens
        temp = temperature if temperature is not None else self._temperature

        # ── Step 1: estimate token cost of this request ──────────────────
        est_tokens = estimate_tokens(messages, system_prompt)
        logger.info(f"[Router] Request estimated at ~{est_tokens} tokens (response budget: {mt})")

        # ── Step 2: ask the registry for the best provider ───────────────
        preferred_order = [self._default_name]
        if self._fallback_name != self._default_name:
            preferred_order.append(self._fallback_name)

        # Build the full order: registry-preferred first, then any remaining
        best = self._registry.best_provider_for(est_tokens, preferred_order, mt)
        if best:
            # Put registry's pick first, keep rest as fallbacks
            order = [best] + [p for p in preferred_order if p != best]
        else:
            # Registry found nothing suitable — try everything anyway
            # (maybe the estimates are wrong; let the API decide)
            logger.warning("[Router] No provider pre-selected by registry — trying all in order.")
            order = preferred_order

        # ── Step 3: attempt each provider in order ───────────────────────
        last_error: Exception | None = None

        for name in order:
            provider = self._providers.get(name)
            if provider is None:
                logger.warning(f"[Router] Provider '{name}' not initialised — skipping.")
                continue

            try:
                logger.info(f"[Router] Sending to: {name}")
                result = provider.generate(messages, system_prompt, mt, temp)
                return result

            except ProviderRateLimitError as exc:
                print(f"\n[{name}] Rate limit — switching provider...")
                logger.warning(f"[Router] {name} rate-limited.")
                self._registry.error_log.record(name, "rate_limit", est_tokens)
                last_error = exc
                continue

            except ProviderAuthError as exc:
                print(f"\n[{name}] Auth error — check API key in settings.json.")
                logger.error(f"[Router] {name} auth error: {exc}")
                self._registry.error_log.record(name, "auth", est_tokens)
                last_error = exc
                continue

            except ProviderError as exc:
                err_str = str(exc).lower()
                # Detect context-too-large even when provider raises generic ProviderError
                if "413" in err_str or "too large" in err_str or "context" in err_str:
                    print(f"\n[{name}] Request too large — switching to larger-context provider...")
                    logger.warning(f"[Router] {name} context-too-large: {exc}")
                    self._registry.error_log.record(name, "context_too_large", est_tokens)
                else:
                    print(f"\n[{name}] Provider error — trying next...")
                    logger.error(f"[Router] {name} error: {exc}")
                    self._registry.error_log.record(name, "other", est_tokens)
                last_error = exc
                continue

        raise ProviderError(f"All providers failed. Last error: {last_error}")

    # ------------------------------------------------------------------
    # Status / reporting
    # ------------------------------------------------------------------

    def status(self) -> dict[str, bool]:
        return {name: (name in self._providers) for name in _PROVIDER_CLASSES}

    def capability_report(self) -> str:
        """Full model capability + error log report for the 'models' command."""
        return self._registry.capability_report()

    def session_error_summary(self) -> str:
        return self._registry.error_log.summary()

    @property
    def available_providers(self) -> list[str]:
        return list(self._providers.keys())

    @property
    def registry(self) -> ModelRegistry:
        return self._registry
