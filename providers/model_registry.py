"""
Model Registry
==============
Static knowledge about every provider and model the assistant uses,
plus a session-scoped error log the router consults before each request.

Two data sources:
  1. MODEL_SPECS dict below — hard-coded capabilities, updated when models change.
  2. SessionErrorLog — runtime record of failures this session.

The router calls:
    registry.best_provider_for(estimated_tokens, preferred_order)
and gets back the name of the best available provider, or None if all are unsuitable.

Adding a new provider/model:
    Add one entry to MODEL_SPECS. Nothing else changes.
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
    """
    Static capabilities for one provider/model combination.
    All token counts are in tokens (not characters).
    """
    provider:            str         # key matching _PROVIDER_CLASSES in router
    model_id:            str         # exact string sent to the API
    context_window:      int         # max tokens the model can process total
    tpm_limit:           int         # free-tier tokens per minute limit
    rpm_limit:           int         # free-tier requests per minute limit
    rpd_limit:           int         # free-tier requests per day limit
    strengths:           list[str]   # what this model is good at
    weaknesses:          list[str]   # known limitations
    notes:               str = ""    # any extra human-readable notes


# Current free-tier model specifications (June 2026)
# Update this dict when providers change their models or limits.
MODEL_SPECS: dict[str, ModelSpec] = {

    "groq": ModelSpec(
        provider        = "groq",
        model_id        = "llama-3.3-70b-versatile",
        context_window  = 128_000,
        tpm_limit       = 6_000,      # tokens per minute on free tier
        rpm_limit       = 30,
        rpd_limit       = 14_400,
        strengths       = [
            "very fast inference",
            "strong general reasoning",
            "good at structured output",
            "good code generation",
        ],
        weaknesses      = [
            "low tokens-per-minute on free tier (6k TPM)",
            "will reject single requests larger than TPM limit",
        ],
        notes = (
            "Free tier: 6,000 TPM is a hard per-minute cap, not a burst limit. "
            "A single request exceeding 6k tokens will be rejected with 413. "
            "Route large-context requests to Google instead."
        ),
    ),

    "google": ModelSpec(
        provider        = "google",
        model_id        = "gemini-2.5-flash",
        context_window  = 1_000_000,
        tpm_limit       = 250_000,    # very generous free tier
        rpm_limit       = 5,
        rpd_limit       = 20, 
        strengths       = [
            "enormous context window (1M tokens)",
            "excellent for long documents and large vault loads",
            "strong reasoning and summarisation",
            "multimodal capable",
        ],
        weaknesses      = [
            "slower than Groq",
            "lower RPM on free tier (15 req/min)",
            "lower RPD on free tier vs Groq",
        ],
        notes = (
            "Best choice when the request is large (>5k tokens). "
            "Use as fallback for Groq rate-limit hits and as primary "
            "for large vault context loads."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Session error log
# ---------------------------------------------------------------------------

@dataclass
class ErrorEvent:
    """One recorded error from this session."""
    provider:   str
    error_type: str   # "rate_limit" | "auth" | "context_too_large" | "other"
    tokens_est: int   # estimated token count at time of error (0 if unknown)
    timestamp:  float = field(default_factory=time.time)


class SessionErrorLog:
    """
    Runtime log of provider errors for the current session.
    The router reads this to make smarter routing decisions.
    """

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
        """Count rate-limit events for a provider in the last N seconds."""
        cutoff = time.time() - within_seconds
        return sum(
            1 for e in self._events
            if e.provider == provider
            and e.error_type == "rate_limit"
            and e.timestamp >= cutoff
        )

    def had_context_error(self, provider: str) -> bool:
        """True if this provider has hit a context-too-large error this session."""
        return any(
            e.provider == provider and e.error_type == "context_too_large"
            for e in self._events
        )

    def all_events(self) -> list[ErrorEvent]:
        return list(self._events)

    def summary(self) -> str:
        """Plain-text summary for session log writing."""
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

CHARS_PER_TOKEN = 4  # conservative approximation; real value is ~3.5-4


def estimate_tokens(messages: list, system_prompt: str = "") -> int:
    """
    Estimate total token count for a list of Message objects plus a system prompt.
    Uses 1 token ≈ 4 characters. Accurate enough for routing decisions.
    """
    total_chars = len(system_prompt)
    for msg in messages:
        # role label overhead (~4 tokens each)
        total_chars += len(msg.content) + 16
    return total_chars // CHARS_PER_TOKEN


# ---------------------------------------------------------------------------
# Model Registry (public interface)
# ---------------------------------------------------------------------------

class ModelRegistry:
    """
    Combines static ModelSpec knowledge with the runtime SessionErrorLog
    to answer the router's key question:
        "Given this many tokens, which provider should I use?"
    """

    def __init__(self):
        self.specs      = MODEL_SPECS          # static, shared
        self.error_log  = SessionErrorLog()    # session-scoped

    def spec(self, provider: str) -> Optional[ModelSpec]:
        return self.specs.get(provider)

    def best_provider_for(
        self,
        estimated_tokens: int,
        preferred_order: list[str],
        response_tokens: int = 2048,
    ) -> Optional[str]:
        """
        Return the name of the best available provider for a request of this size.

        Args:
            estimated_tokens: Estimated input token count.
            preferred_order:  Provider names in config preference order.
            response_tokens:  Max tokens reserved for the response.

        Returns:
            Provider name string, or None if no provider can handle the request.

        Decision logic (in order):
            1. Skip if provider has no spec (unknown capabilities).
            2. Skip if total tokens (input + response) exceed context window.
            3. Skip if input alone exceeds the TPM limit (Groq 413 prevention).
            4. Skip if provider had a recent rate-limit hit (within last 65s).
            5. Skip if provider had a context-too-large error this session.
            6. Return the first provider that passes all checks.
        """
        total_tokens = estimated_tokens + response_tokens

        for name in preferred_order:
            spec = self.specs.get(name)
            if spec is None:
                logger.debug(f"[ModelRegistry] {name}: no spec — skipping")
                continue

            # Check context window
            if total_tokens > spec.context_window:
                logger.info(
                    f"[ModelRegistry] {name}: context window too small "
                    f"({total_tokens} > {spec.context_window}) — skipping"
                )
                continue

            # Check TPM limit (prevents 413 on Groq)
            if estimated_tokens > spec.tpm_limit:
                logger.info(
                    f"[ModelRegistry] {name}: input exceeds TPM limit "
                    f"({estimated_tokens} > {spec.tpm_limit}) — skipping"
                )
                continue

            # Check recent rate limits
            recent_rl = self.error_log.recent_rate_limits(name)
            if recent_rl > 0:
                logger.info(
                    f"[ModelRegistry] {name}: {recent_rl} rate-limit(s) in last 65s — skipping"
                )
                continue

            # Check session context errors
            if self.error_log.had_context_error(name):
                logger.info(
                    f"[ModelRegistry] {name}: had context-too-large error this session — skipping"
                )
                continue

            logger.info(
                f"[ModelRegistry] Selected: {name} "
                f"(est. {estimated_tokens} input + {response_tokens} response = {total_tokens} tokens)"
            )
            return name

        logger.warning(
            f"[ModelRegistry] No suitable provider found for {estimated_tokens} tokens"
        )
        return None

    def capability_report(self) -> str:
        """Human-readable report of all known models — for the 'status' command."""
        lines = ["\n--- Model Capabilities ---"]
        for name, spec in self.specs.items():
            lines.append(f"\n  {name.upper()}  ({spec.model_id})")
            lines.append(f"    Context window : {spec.context_window:,} tokens")
            lines.append(f"    Free TPM limit : {spec.tpm_limit:,} tokens/min")
            lines.append(f"    Free RPM limit : {spec.rpm_limit} requests/min")
            lines.append(f"    Strengths      : {', '.join(spec.strengths[:2])}")
            lines.append(f"    Notes          : {spec.notes[:80]}...")
        lines.append("\n" + self.error_log.summary())
        lines.append("--------------------------")
        return "\n".join(lines)
