"""
Provider Router — Milestone 7 update
=====================================
Changes from Milestone 6:

1. WebUIProvider registered as a third provider.
2. generate() now returns tuple[str, str] — (reply, actual_provider_used).
   The actual provider may differ from the requested one if fallback occurred.
3. generate() gains an optional provider_override parameter.
4. ProviderWebUIHandoff is NOT caught here — it propagates to the caller.
5. history_lock threading.Lock passed in from main() and used to guard
   all multi-step history mutations in the HTTP server.
"""

import logging
import threading
from providers.base_provider import (
    BaseProvider,
    Message,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderWebUIHandoff,   # not caught — allowed to propagate
)
from providers.openai_compatible_provider import OpenAICompatibleProvider
from providers.webui_provider   import WebUIProvider
from providers.model_registry   import ModelRegistry, estimate_tokens

logger = logging.getLogger("assistant")


class ProviderRouter:
    """
    Routes generate() calls to the best available provider.

    Routing decision order (Milestone 7):
        1. If provider_override is set, try that provider first.
        2. Estimate token count for the full request.
        3. Ask ModelRegistry which provider can handle it.
        4. Try providers in order; on ProviderError, record and continue.
        5. ProviderWebUIHandoff is NOT caught — it propagates as-is.
        6. If all API providers fail, try webui as final fallback.
        7. Returns tuple[str, str]: (reply, actual_provider_name).
    """

    def __init__(self, config: dict):
        self._config        = config
        self._default_name  = config.get("default_provider",  "groq").lower()
        self._fallback_name = config.get("fallback_provider", "google").lower()
        self._max_tokens    = config.get("max_tokens",   2048)
        self._temperature   = config.get("temperature",  0.7)

        self._providers: dict[str, BaseProvider] = {}
        self._registry = ModelRegistry(self._config)
        self._init_providers()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_providers(self) -> None:
        """
        Milestone 10: build one generic OpenAICompatibleProvider per ACTIVE
        registry row (keyed by provider_key — the first active row wins when a
        provider has several models). webui is always added as the special,
        keyless final fallback. A provider with no API key, or a row that
        cannot be built, is skipped exactly as before.
        """
        for key, spec in self._registry.specs.items():
            # webui is a virtual provider — no key, no base_url, handled specially.
            if spec.provider == "webui":
                if "webui" not in self._providers:
                    self._providers["webui"] = WebUIProvider(self._config)
                    logger.info("[Router] Provider ready: webui")
                continue

            if spec.status != "active":
                continue
            if not spec.base_url:
                continue
            # Only the canonical provider per provider_key is routed in this slice.
            if spec.provider in self._providers:
                logger.info(
                    f"[Router] '{spec.provider}:{spec.model_id}' registered but not "
                    f"routed (canonical row already built)."
                )
                continue

            api_key = self._config.get(f"{spec.provider}_api_key", "")
            if not str(api_key).strip():
                logger.info(f"[Router] {spec.provider} skipped — no '{spec.provider}_api_key' in settings.")
                continue

            try:
                self._providers[spec.provider] = OpenAICompatibleProvider(spec, api_key, self._config)
                logger.info(f"[Router] Provider ready: {spec.provider} ({spec.model_id})")
            except ProviderAuthError as exc:
                logger.warning(f"[Router] {spec.provider} skipped — auth error: {exc}")
            except ProviderError as exc:
                logger.warning(f"[Router] {spec.provider} skipped — error: {exc}")

        # Guarantee webui exists even if it has no registry row.
        if "webui" not in self._providers:
            self._providers["webui"] = WebUIProvider(self._config)
            logger.info("[Router] Provider ready: webui (fallback)")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int | None = None,
        temperature: float | None = None,
        provider_override: str | None = None,
    ) -> tuple[str, str]:
        """
        Generate a reply from the best available provider.

        Args:
            messages:          Conversation history (oldest first).
            system_prompt:     System-level instruction.
            max_tokens:        Response token budget.
            temperature:       Sampling temperature.
            provider_override: Name of provider to try first. Falls through
                               to normal routing if it fails. Pass "webui"
                               to force an immediate handoff.

        Returns:
            (reply_text, actual_provider_name)
            actual_provider_name may differ from provider_override if
            fallback occurred.

        Raises:
            ProviderWebUIHandoff: When the webui provider is reached.
                                  Contains the packaged context prompt.
            ProviderError:        When all non-webui providers have failed.
        """
        mt   = max_tokens  if max_tokens  is not None else self._max_tokens
        temp = temperature if temperature is not None else self._temperature

        est_tokens = estimate_tokens(messages, system_prompt)
        logger.info(f"[Router] Request ~{est_tokens} tokens (budget: {mt})")

        # Build provider order
        preferred_order = [self._default_name]
        if self._fallback_name != self._default_name:
            preferred_order.append(self._fallback_name)

        if provider_override:
            override = provider_override.lower()
            # Put override first; keep others as fallbacks (excluding duplicates)
            order = [override] + [p for p in preferred_order if p != override]
            logger.info(f"[Router] Provider override: {override}")
        else:
            best = self._registry.best_provider_for(est_tokens, preferred_order, mt)
            if best:
                order = [best] + [p for p in preferred_order if p != best]
            else:
                logger.warning("[Router] No provider pre-selected — trying all in order.")
                order = preferred_order

        # Always add webui as the final fallback (if not already in order)
        if "webui" not in order:
            order.append("webui")

        last_error: Exception | None = None

        for name in order:
            provider = self._providers.get(name)
            if provider is None:
                logger.warning(f"[Router] '{name}' not initialised — skipping.")
                continue

            try:
                logger.info(f"[Router] Sending to: {name}")
                result = provider.generate(messages, system_prompt, mt, temp)
                # result is a str from all real providers
                return result, name

            except ProviderWebUIHandoff:
                # Not an error — propagate immediately to the caller
                raise

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
                if "413" in err_str or "too large" in err_str or "context" in err_str:
                    print(f"\n[{name}] Request too large — switching provider...")
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
        # Report the configured default/fallback plus webui, and any other
        # active provider that was built — preserving the old shape (groq,
        # google, webui all appear) for startup diagnostics and the `status` cmd.
        names: list[str] = []
        for name in (self._default_name, self._fallback_name, "webui"):
            if name not in names:
                names.append(name)
        for name in self._providers:
            if name not in names:
                names.append(name)
        return {name: (name in self._providers) for name in names}

    def capability_report(self) -> str:
        return self._registry.capability_report()

    def session_error_summary(self) -> str:
        return self._registry.error_log.summary()

    @property
    def available_providers(self) -> list[str]:
        # webui is always available but not a "real" API provider
        return [n for n in self._providers if n != "webui"]

    @property
    def registry(self) -> ModelRegistry:
        return self._registry
