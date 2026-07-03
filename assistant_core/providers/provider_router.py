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
from assistant_core.providers.base_provider import (
    BaseProvider,
    Message,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderWebUIHandoff,   # not caught — allowed to propagate
)
from assistant_core.providers.openai_compatible_provider import OpenAICompatibleProvider
from assistant_core.providers.webui_provider   import WebUIProvider
from assistant_core.providers.model_registry   import ModelRegistry, estimate_tokens

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

    @property
    def config(self) -> dict:
        """The settings dict the router was built from (read-only convenience)."""
        return self._config

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
        Milestone 10 (final): build one generic OpenAICompatibleProvider per
        ACTIVE registry ROW — so a provider with several models (e.g. Groq's 70B
        and 8B) yields several independent route targets. Each is keyed by its
        registry.specs key: the first row for a provider takes the bare
        provider_key ("groq"); a further row is keyed "<provider>:<model_id>"
        ("groq:llama-3.1-8b-instant"). Candidate/deprecated rows (status != active)
        are never built, so the router can never select them. webui is the
        special keyless final fallback.
        """
        for key, spec in self._registry.specs.items():
            # webui is a virtual provider — no key, no base_url, handled specially.
            if spec.provider == "webui":
                if "webui" not in self._providers:
                    self._providers["webui"] = WebUIProvider(self._config)
                    logger.info("[Router] Provider ready: webui")
                continue

            if spec.status != "active":
                logger.info(f"[Router] {key} registered ({spec.status}) — not routed.")
                continue
            if not spec.base_url:
                continue

            api_key = self._config.get(f"{spec.provider}_api_key", "")
            if not str(api_key).strip():
                logger.info(f"[Router] {key} skipped — no '{spec.provider}_api_key' in settings.")
                continue

            try:
                self._providers[key] = OpenAICompatibleProvider(spec, api_key, self._config)
                logger.info(f"[Router] Provider ready: {key} ({spec.model_id})")
            except ProviderAuthError as exc:
                logger.warning(f"[Router] {key} skipped — auth error: {exc}")
            except ProviderError as exc:
                logger.warning(f"[Router] {key} skipped — error: {exc}")

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
        private: bool = False,
        allow_webui_on_private: bool = False,
        allow_webui: bool = True,
    ) -> tuple[str, str]:
        """
        Generate a reply from the best available provider.

        Args:
            messages:          Conversation history (oldest first).
            system_prompt:     System-level instruction.
            max_tokens:        Response token budget.
            temperature:       Sampling temperature.
            provider_override: Route key to try first. Falls through to normal
                               routing if it fails. Pass "webui" to force a handoff.
                               Ignored when `private` and the override trains on data.
            private:           If True, privacy is applied FIRST — only models with
                               trains_on_data == "no" are eligible, and the WebUI
                               handoff is offered only when allow_webui_on_private.
            allow_webui_on_private: User opt-in to allow the WebUI fallback for a
                               private request (it would expose content to a web AI).

        Returns:
            (reply_text, actual_route_key)

        Raises:
            ProviderWebUIHandoff: When the webui provider is reached.
            ProviderError:        When all eligible providers have failed (for a
                                  private request with no WebUI opt-in, this is the
                                  signal for the caller to offer the choice).
        """
        mt   = max_tokens  if max_tokens  is not None else self._max_tokens
        temp = temperature if temperature is not None else self._temperature

        est_tokens  = estimate_tokens(messages, system_prompt)
        high_volume = (est_tokens + mt) >= self._registry.LARGE_TOKENS
        logger.info(
            f"[Router] Request ~{est_tokens} tokens (budget: {mt}, private={private}, "
            f"high_volume={high_volume})"
        )

        available = self.available_models  # built, non-webui route keys

        if provider_override:
            override = provider_override.lower()
            ov_spec  = self._registry.specs.get(override)
            # Privacy wins over a manual override.
            if private and ov_spec is not None and (ov_spec.trains_on_data or "").lower() != "no":
                logger.warning(
                    f"[Router] Override '{override}' ignored — trains_on_data="
                    f"{ov_spec.trains_on_data!r} not allowed for a private request."
                )
                order = self._registry.route_order(available, private, est_tokens, mt, high_volume)
            else:
                rest  = self._registry.route_order(available, private, est_tokens, mt, high_volume)
                order = [override] + [p for p in rest if p != override]
                logger.info(f"[Router] Provider override: {override}")
        else:
            order = self._registry.route_order(available, private, est_tokens, mt, high_volume)

        # WebUI is the final fallback — but only when the caller allows it (edits
        # disable it so they can build their own edit-handoff), and for a private
        # request only with opt-in (a handoff means pasting content into a web AI).
        if allow_webui and ((not private) or allow_webui_on_private):
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
                self._registry.error_log.record_success(name)
                return result, name

            except ProviderWebUIHandoff:
                # Not an error — propagate immediately to the caller
                raise

            except ProviderRateLimitError as exc:
                print(f"\n[{name}] Rate limit — switching provider...")
                logger.warning(f"[Router] {name} rate-limited.")
                self._record_failure(name, "rate_limit", est_tokens)
                last_error = exc
                continue

            except ProviderAuthError as exc:
                print(f"\n[{name}] Auth error — check API key in settings.json.")
                logger.error(f"[Router] {name} auth error: {exc}")
                self._record_failure(name, "auth", est_tokens)
                last_error = exc
                continue

            except ProviderError as exc:
                err_str = str(exc).lower()
                if "413" in err_str or "too large" in err_str or "context" in err_str:
                    print(f"\n[{name}] Request too large — switching provider...")
                    logger.warning(f"[Router] {name} context-too-large: {exc}")
                    self._record_failure(name, "context_too_large", est_tokens)
                else:
                    print(f"\n[{name}] Provider error — trying next...")
                    logger.error(f"[Router] {name} error: {exc}")
                    self._record_failure(name, "other", est_tokens)
                last_error = exc
                continue

        raise ProviderError(f"All providers failed. Last error: {last_error}")

    # ------------------------------------------------------------------
    # Health flagging (Milestone 10) — driven by real traffic only
    # ------------------------------------------------------------------

    def _record_failure(self, name: str, error_type: str, est_tokens: int) -> None:
        """Record a real-traffic failure and raise health/floor flags when crossed."""
        log = self._registry.error_log
        log.record(name, error_type, est_tokens)
        if log.just_went_unhealthy(name):
            msg = f"[Router] ⚠ Provider '{name}' marked UNHEALTHY after repeated failures — skipping it."
            logger.warning(msg)
            print(f"\n{msg}")
        healthy = self._registry.healthy_active_provider_keys(self.available_models)
        if len(healthy) < 3:
            msg = (
                f"[Router] ⚠ Provider floor breached — only {len(healthy)} healthy active "
                f"provider(s): {', '.join(sorted(healthy)) or 'none'} (target ≥3)."
            )
            logger.warning(msg)
            print(f"\n{msg}")

    # ------------------------------------------------------------------
    # Status / reporting
    # ------------------------------------------------------------------

    def status(self) -> dict[str, bool]:
        # Report the configured default/fallback plus webui, and every built
        # route key — preserving the old shape (groq, google, webui all appear)
        # for startup diagnostics and the `status` command.
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

    def startup_report(self) -> str:
        """
        Render the live provider registry for run_startup_diagnostics: last-updated
        date, active route targets (with health flags), registered candidates, and a
        warning when fewer than 3 active providers exist.
        """
        reg   = self._registry
        built = set(self.available_models)
        active_rows:    list[tuple[str, "object"]] = []
        candidate_rows: list[tuple[str, "object"]] = []
        for key, spec in reg.specs.items():
            if spec.provider == "webui":
                continue
            if spec.status == "active":
                active_rows.append((key, spec))
            elif spec.status == "candidate":
                candidate_rows.append((key, spec))

        lines = ["", f"  Provider Registry (updated: {reg.last_updated})"]
        lines.append("  " + "-" * 60)
        lines.append(f"  {'ROUTE KEY':<30}{'TRAINS':<8}{'STATE'}")
        for key, spec in active_rows:
            if key not in built:
                state = "active - no key (not built)"
            elif not reg.error_log.is_healthy(key):
                state = "active - UNHEALTHY"
            else:
                state = "active - ready"
            lines.append(f"  {key:<30}{(spec.trains_on_data or '?'):<8}{state}")
        for key, spec in candidate_rows:
            lines.append(f"  {key:<30}{(spec.trains_on_data or '?'):<8}candidate - registered, not routed")

        distinct_active = {spec.provider for _, spec in active_rows}
        if len(distinct_active) < 3:
            lines.append(f"  ⚠ Only {len(distinct_active)} active provider(s) — target is ≥3.")
        healthy = reg.healthy_active_provider_keys(self.available_models)
        if len(healthy) < 3:
            lines.append(
                f"  ⚠ Floor: {len(healthy)} healthy active provider(s) "
                f"({', '.join(sorted(healthy)) or 'none'}) — target ≥3."
            )
        lines.append("  " + "-" * 60)
        return "\n".join(lines)

    @property
    def available_models(self) -> list[str]:
        """All built route keys (per-model), excluding the webui fallback."""
        return [n for n in self._providers if n != "webui"]

    @property
    def available_providers(self) -> list[str]:
        # Back-compat alias — webui is always available but not a "real" API provider.
        return self.available_models

    @property
    def registry(self) -> ModelRegistry:
        return self._registry
