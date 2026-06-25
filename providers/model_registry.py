"""
Model Registry — Milestone 7 update
=====================================
Changes from Milestone 6:
  - Added ModelSpec for "webui" virtual provider.
    Infinite context window and TPM so it always passes routing checks
    and serves as the guaranteed final fallback.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("assistant")


# ---------------------------------------------------------------------------
# Static model specifications
# ---------------------------------------------------------------------------

@dataclass
class ModelSpec:
    provider:        str
    model_id:        str
    context_window:  int
    tpm_limit:       int
    rpm_limit:       int
    rpd_limit:       int
    strengths:       list[str]
    weaknesses:      list[str]
    notes:           str = ""
    # Milestone 10 — fields carried by the provider registry. Defaulted so the
    # hardcoded specs below and any existing callers still construct cleanly.
    base_url:        str = ""
    status:          str = "active"
    trains_on_data:  str = ""
    tpd_limit:       int = 0


MODEL_SPECS: dict[str, ModelSpec] = {

    "groq": ModelSpec(
        provider        = "groq",
        model_id        = "llama-3.3-70b-versatile",
        context_window  = 128_000,
        tpm_limit       = 6_000,
        rpm_limit       = 30,
        rpd_limit       = 14_400,
        base_url        = "https://api.groq.com/openai/v1",
        status          = "active",
        strengths       = [
            "very fast inference",
            "strong general reasoning",
            "good structured output",
            "good code generation",
        ],
        weaknesses      = [
            "low TPM on free tier (6k)",
            "rejects single requests over TPM limit",
        ],
        notes = (
            "Free tier: 6,000 TPM is a hard per-minute cap. "
            "A single request exceeding 6k tokens will be rejected with 413. "
            "Route large-context requests to Google instead."
        ),
    ),

    "google": ModelSpec(
        provider        = "google",
        model_id        = "gemini-2.5-flash",
        context_window  = 1_000_000,
        tpm_limit       = 250_000,
        rpm_limit       = 3,
        rpd_limit       = 20,
        base_url        = "https://generativelanguage.googleapis.com/v1beta/openai/",
        status          = "active",
        strengths       = [
            "enormous context window (1M tokens)",
            "excellent for long documents and large vault loads",
            "strong reasoning and summarisation",
            "multimodal capable",
        ],
        weaknesses      = [
            "slower than Groq",
            "very low RPD on free tier (20 req/day)",
        ],
        notes = (
            "Best choice when the request is large (>5k tokens). "
            "Use as fallback for Groq rate-limit hits. "
            "Only 20 requests per day on free tier — use sparingly."
        ),
    ),

    "webui": ModelSpec(
        provider        = "webui",
        model_id        = "user-mediated",
        context_window  = 999_999_999,   # always passes context checks
        tpm_limit       = 999_999_999,   # always passes TPM checks
        rpm_limit       = 999_999_999,
        rpd_limit       = 999_999_999,
        strengths       = [
            "no API limits",
            "access to premium web models (Claude, GPT-4, Gemini Pro)",
            "works when all API free tiers are exhausted",
            "zero cost",
        ],
        weaknesses      = [
            "requires user to manually copy/paste",
            "breaks the real-time chat flow",
            "response quality depends on which web AI the user chooses",
        ],
        notes = (
            "Virtual provider — never calls an API. "
            "Packages the full conversation context into a markdown block "
            "the user pastes into any web AI. "
            "Always available as the final fallback. "
            "Raises ProviderWebUIHandoff instead of returning a string."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Session error log
# ---------------------------------------------------------------------------

@dataclass
class ErrorEvent:
    provider:   str
    error_type: str
    tokens_est: int
    timestamp:  float = field(default_factory=time.time)


class SessionErrorLog:

    def __init__(self):
        self._events: list[ErrorEvent] = []

    def record(self, provider: str, error_type: str, tokens_est: int = 0) -> None:
        event = ErrorEvent(provider=provider, error_type=error_type, tokens_est=tokens_est)
        self._events.append(event)
        logger.info(
            f"[ModelRegistry] Error recorded — provider={provider} "
            f"type={error_type} tokens≈{tokens_est}"
        )

    def recent_rate_limits(self, provider: str, within_seconds: int = 65) -> int:
        cutoff = time.time() - within_seconds
        return sum(
            1 for e in self._events
            if e.provider == provider
            and e.error_type == "rate_limit"
            and e.timestamp >= cutoff
        )

    def had_context_error(self, provider: str) -> bool:
        return any(
            e.provider == provider and e.error_type == "context_too_large"
            for e in self._events
        )

    def all_events(self) -> list[ErrorEvent]:
        return list(self._events)

    def summary(self) -> str:
        if not self._events:
            return "No errors recorded this session."
        lines = ["Provider errors this session:"]
        for e in self._events:
            ts = time.strftime("%H:%M:%S", time.localtime(e.timestamp))
            lines.append(f"  {ts}  {e.provider:<10} {e.error_type:<22} tokens≈{e.tokens_est}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

CHARS_PER_TOKEN = 4


def estimate_tokens(messages: list, system_prompt: str = "") -> int:
    total_chars = len(system_prompt)
    for msg in messages:
        total_chars += len(msg.content) + 16
    return total_chars // CHARS_PER_TOKEN


# ---------------------------------------------------------------------------
# Model Registry
# ---------------------------------------------------------------------------

class ModelRegistry:

    def __init__(self, config: dict | None = None):
        # Start from the hardcoded specs (a complete working fallback), then
        # merge the provider registry OVER them (file wins). webui has no
        # registry row, so it always survives as the final fallback.
        self.specs     = dict(MODEL_SPECS)
        self.error_log = SessionErrorLog()
        self._load_registry(config or {})

    def _load_registry(self, config: dict) -> None:
        """Seed + load AI/System/Provider-Registry.md and merge over the fallbacks."""
        vault_path = config.get("vault_path", "")
        if not vault_path:
            logger.info("[ModelRegistry] No vault_path — using hardcoded provider specs only")
            return

        from pathlib import Path
        from providers.registry_loader import RegistryLoader   # lazy: avoid import cycle

        registry_path = Path(vault_path) / "AI" / "System" / "Provider-Registry.md"
        loader = RegistryLoader(registry_path)
        loader.seed()

        seen: set[str] = set()
        for spec in loader.load():
            # First row for a provider_key takes the bare key (overwrites the
            # hardcoded fallback — file wins). A repeated key (e.g. the second
            # Groq model) is registered under "<provider>:<model_id>".
            if spec.provider in seen:
                key = f"{spec.provider}:{spec.model_id}"
            else:
                key = spec.provider
                seen.add(spec.provider)
            self.specs[key] = spec

    def spec(self, provider: str) -> Optional[ModelSpec]:
        return self.specs.get(provider)

    def best_provider_for(
        self,
        estimated_tokens: int,
        preferred_order: list[str],
        response_tokens: int = 2048,
    ) -> Optional[str]:
        total_tokens = estimated_tokens + response_tokens

        for name in preferred_order:
            spec = self.specs.get(name)
            if spec is None:
                logger.debug(f"[ModelRegistry] {name}: no spec — skipping")
                continue
            if total_tokens > spec.context_window:
                logger.info(f"[ModelRegistry] {name}: context window too small — skipping")
                continue
            if estimated_tokens > spec.tpm_limit:
                logger.info(f"[ModelRegistry] {name}: input exceeds TPM limit — skipping")
                continue
            if self.error_log.recent_rate_limits(name) > 0:
                logger.info(f"[ModelRegistry] {name}: recent rate-limit — skipping")
                continue
            if self.error_log.had_context_error(name):
                logger.info(f"[ModelRegistry] {name}: had context error this session — skipping")
                continue
            logger.info(
                f"[ModelRegistry] Selected: {name} "
                f"(est. {estimated_tokens} + {response_tokens} = {total_tokens} tokens)"
            )
            return name

        logger.warning(f"[ModelRegistry] No suitable provider for {estimated_tokens} tokens")
        return None

    def capability_report(self) -> str:
        lines = ["\n--- Model Capabilities ---"]
        for name, spec in self.specs.items():
            lines.append(f"\n  {name.upper()}  ({spec.model_id})")
            lines.append(f"    Context window : {spec.context_window:,} tokens")
            lines.append(f"    Free TPM limit : {spec.tpm_limit:,} tokens/min")
            lines.append(f"    Free RPM limit : {spec.rpm_limit}")
            lines.append(f"    Strengths      : {', '.join(spec.strengths[:2])}")
            lines.append(f"    Notes          : {spec.notes[:80]}...")
        lines.append("\n" + self.error_log.summary())
        lines.append("--------------------------")
        return "\n".join(lines)
