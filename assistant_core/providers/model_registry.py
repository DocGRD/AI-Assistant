"""
Model Registry — Milestone 7 update
=====================================
Changes from Milestone 6:
  - Added ModelSpec for "webui" virtual provider.
    Infinite context window and TPM so it always passes routing checks
    and serves as the guaranteed final fallback.
"""

import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("assistant")


# ---------------------------------------------------------------------------
# Tier + task-capability routing (Milestone 30)
# ---------------------------------------------------------------------------

def derive_tier(model_id: str) -> str:
    """
    Rough capability tier from a model id's parameter count — 'small' | 'mid' | 'large'.
    Used to keep hard/factual tasks off tiny models and to pick an escalation target.
    """
    mid = (model_id or "").lower()
    if "maverick" in mid:                    # big MoE despite 17B active params
        return "large"
    m = re.search(r"(\d+)\s*b", mid)
    if m:
        n = int(m.group(1))
        if n < 14:
            return "small"
        if n <= 45:
            return "mid"
        return "large"
    if "mini" in mid or "nano" in mid or "small" in mid:
        return "small"
    if any(k in mid for k in ("opus", "gpt-4", "70", "120", "405", "large")):
        return "large"
    return "mid"                             # unknown (e.g. gemini-flash) → middle


# Reasoning / chain-of-thought models. They emit a "thinking" preamble (e.g. "We need to run
# command:search …") that breaks the strict contract of the agent loop — a vault:/command:
# directive must sit ALONE on its own line to be executed. So even though some are large and
# smart, they are UNRELIABLE for tool/command turns and are excluded from them (M43).
_REASONING_RE = re.compile(
    r"(gpt-?oss|deepseek-?r1|\br1\b|qwq|magistral|thinking|reason(?:ing|er)?|o1|o3|o4-mini)",
    re.IGNORECASE,
)


def is_reasoning_model(model_id: str) -> bool:
    """True for chain-of-thought models whose preamble breaks strict directive output."""
    return bool(_REASONING_RE.search(model_id or ""))


# task → (prefer a larger tier?, desired strength tags). Absent/unknown task ⇒ neutral.
TASK_PROFILE: dict[str, tuple[bool, set[str]]] = {
    "qa":       (True,  {"reasoning", "quality"}),
    "research": (True,  {"reasoning", "quality"}),
    "verify":   (True,  {"reasoning", "quality"}),
    "graph":    (True,  {"reasoning"}),
    "extract":  (True,  {"reasoning"}),
    "edit":     (False, {"quality"}),
    "grammar":  (False, set()),
    "code":     (False, {"code"}),
    "chat":     (False, set()),
}
_TIER_RANK = {"large": 0, "mid": 1, "small": 2}


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

    @property
    def tier(self) -> str:
        """'small' | 'mid' | 'large' — derived from the model id (M30)."""
        return derive_tier(self.model_id)


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


# A provider is marked unhealthy after this many CONSECUTIVE real-traffic failures.
UNHEALTHY_THRESHOLD = 3


class SessionErrorLog:

    def __init__(self):
        self._events: list[ErrorEvent] = []
        # Milestone 10 — per-provider health from REAL traffic only (never probing).
        self._consecutive: dict[str, int] = {}   # consecutive failures since last success
        self._success:     dict[str, int] = {}   # total successes this session
        self._fail:        dict[str, int] = {}    # total failures this session

    def record(self, provider: str, error_type: str, tokens_est: int = 0) -> None:
        event = ErrorEvent(provider=provider, error_type=error_type, tokens_est=tokens_est)
        self._events.append(event)
        self._consecutive[provider] = self._consecutive.get(provider, 0) + 1
        self._fail[provider]        = self._fail.get(provider, 0) + 1
        logger.info(
            f"[ModelRegistry] Error recorded — provider={provider} "
            f"type={error_type} tokens≈{tokens_est} "
            f"(consecutive={self._consecutive[provider]})"
        )

    # ------------------------------------------------------------------
    # Health (Milestone 10)
    # ------------------------------------------------------------------

    def record_success(self, provider: str) -> None:
        """A real request succeeded — reset the consecutive-failure counter."""
        self._success[provider] = self._success.get(provider, 0) + 1
        if self._consecutive.get(provider, 0):
            logger.info(f"[ModelRegistry] {provider} recovered — health reset")
        self._consecutive[provider] = 0

    def is_healthy(self, provider: str) -> bool:
        """Healthy until UNHEALTHY_THRESHOLD consecutive failures accumulate."""
        return self._consecutive.get(provider, 0) < UNHEALTHY_THRESHOLD

    def just_went_unhealthy(self, provider: str) -> bool:
        """True only on the exact failure that crosses the threshold (for one-shot flags)."""
        return self._consecutive.get(provider, 0) == UNHEALTHY_THRESHOLD

    def unhealthy_providers(self) -> list[str]:
        return [p for p, c in self._consecutive.items() if c >= UNHEALTHY_THRESHOLD]

    def health_summary(self) -> str:
        if not (self._success or self._fail):
            return "No provider traffic recorded this session."
        lines = ["Provider health this session:"]
        names = sorted(set(self._success) | set(self._fail))
        for p in names:
            ok  = self._success.get(p, 0)
            bad = self._fail.get(p, 0)
            flag = "" if self.is_healthy(p) else "  ⚠ UNHEALTHY"
            lines.append(f"  {p:<28} ok={ok} fail={bad} consec={self._consecutive.get(p, 0)}{flag}")
        return "\n".join(lines)

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
        self.specs        = dict(MODEL_SPECS)
        self.error_log    = SessionErrorLog()
        self.last_updated = "unknown"
        self._load_registry(config or {})

    def _load_registry(self, config: dict) -> None:
        """Seed + load AI/System/Provider-Registry.md and merge over the fallbacks."""
        from assistant_core.paths import is_vault
        vault_path = config.get("vault_path", "")
        if not is_vault(vault_path):
            # Not a real Obsidian vault (missing / typo'd / no .obsidian) — use the
            # hardcoded fallbacks and DO NOT seed a registry file (which would create
            # an AI/ tree in a non-vault directory — T3.20).
            logger.info("[ModelRegistry] vault_path is not a valid vault — using hardcoded "
                        "provider specs only (no registry seed)")
            return

        from pathlib import Path
        from assistant_core.providers.registry_loader import RegistryLoader   # lazy: avoid import cycle

        registry_path = Path(vault_path) / "AI" / "System" / "Provider-Registry.md"
        loader = RegistryLoader(registry_path)
        loader.seed()

        seen: set[str] = set()
        specs_loaded = loader.load()
        self.last_updated = loader.last_updated
        for spec in specs_loaded:
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

    # ------------------------------------------------------------------
    # Privacy- and task-aware selection (Milestone 10)
    # ------------------------------------------------------------------

    # Base preference order (design §10.4 / Provider-Registry "Routing intent").
    # Unknown route keys sort after these but before webui (appended separately).
    # groq leads for everyday short turns: Google's free tier is only ~20 requests/day
    # for gemini-2.5-flash, so routing it first burned the quota instantly and churned
    # into fallback every request (observed in T5.01 logs). Google stays available and
    # the task buckets still elevate it for genuine long-context work.
    DEFAULT_PREFERENCE = ["groq", "cerebras", "google", "groq:llama-3.1-8b-instant"]

    # Above this (estimated input + planned response) a request is "high volume"
    # and we prefer batch/volume providers.
    LARGE_TOKENS = 8_000

    def is_tool_reliable(self, route_key: str) -> bool:
        """True if this model can reliably emit vault:/command: directives on their own line —
        i.e. not a reasoning/CoT model and not a tiny model. Used to keep tool/command turns
        (and overrides for them) on models that follow the strict format (M43)."""
        spec = self.specs.get((route_key or "").lower())
        if spec is None:
            return False
        return spec.tier != "small" and not is_reasoning_model(spec.model_id)

    def _tags(self, spec: ModelSpec) -> set[str]:
        """Lowercased word tags from a spec's strengths, for task matching."""
        tags: set[str] = set()
        for s in spec.strengths:
            for word in s.replace(",", " ").split():
                tags.add(word.strip().lower())
        return tags

    def route_order(
        self,
        available:       list[str],
        private:         bool = False,
        est_tokens:      int  = 0,
        response_tokens: int  = 2048,
        long_form:       bool = False,
        want_tools:      bool = False,
        task:            str | None = None,
        require_tools:   bool = False,
    ) -> list[str]:
        """
        Return route keys to try, best first. Pure and testable.

        Order of filtering (privacy FIRST, per design):
          1. start from active built route keys in `available` (webui excluded —
             it is appended by the router as a separate fallback; candidate rows
             are never in `available` because the router never builds them).
          2. PRIVACY: if private, drop every model whose trains_on_data != "no".
          3. HEALTH: drop models the error log marks unhealthy.
          4. SIZE: drop models that cannot fit the request.
          5. TASK RANK: order by (task bucket, default preference index).
        """
        total = est_tokens + response_tokens
        high_volume = long_form or total >= self.LARGE_TOKENS

        candidates: list[str] = []
        for name in available:
            spec = self.specs.get(name)
            if spec is None or spec.provider == "webui" or spec.status != "active":
                continue
            if private and (spec.trains_on_data or "").lower() != "no":
                continue                                   # 2. privacy filter FIRST
            if not self.error_log.is_healthy(name):
                continue                                   # 3. health filter
            if total > spec.context_window or est_tokens > spec.tpm_limit:
                continue                                   # 4. size feasibility
            candidates.append(name)

        # M43 — tool/command turns must use models that reliably emit directives on their own
        # line. Drop reasoning models (CoT preamble breaks the format) and tiny models. Keep the
        # filtered set only when non-empty, so a degraded state still answers rather than erroring.
        if require_tools:
            reliable = [c for c in candidates if self.is_tool_reliable(c)]
            if reliable:
                candidates = reliable
            else:
                logger.warning("[ModelRegistry] no tool-reliable model available — "
                               "falling back to the full set for this turn")

        def default_index(name: str) -> int:
            try:
                return self.DEFAULT_PREFERENCE.index(name)
            except ValueError:
                return len(self.DEFAULT_PREFERENCE)        # unknown → after known

        def bucket(name: str) -> int:
            spec = self.specs[name]
            tags = self._tags(spec)
            if high_volume:
                if tags & {"volume", "batch", "high-volume"}:
                    return 0
                if "long-context" in tags or spec.context_window >= 500_000:
                    return 1
                return 2
            if want_tools:
                return 0 if (tags & {"tool-use", "tool", "tools"}) else 1
            return 0                                        # default short request

        # M30 — task-aware capability ranking. Neutral (0,0) when no task is given or
        # the task is unknown, so callers that don't pass a task keep the M10 ordering.
        prefer_larger, want = TASK_PROFILE.get((task or "").lower(), (False, set()))

        def cap_key(name: str) -> tuple[int, int]:
            if not prefer_larger and not want:
                return (0, 0)
            spec = self.specs[name]
            tier_rank = _TIER_RANK.get(spec.tier, 1) if prefer_larger else 0
            match     = len(want & self._tags(spec)) if want else 0
            return (tier_rank, -match)                       # larger tier first, more matches first

        def curated(name: str) -> int:
            # Curated (fast, known-good) providers always outrank discovered/candidate ones —
            # capability only reorders WITHIN a group, so a capable-but-slow provider (e.g. a
            # timing-out nvidia endpoint) can never jump ahead of the curated defaults.
            return 0 if name in self.DEFAULT_PREFERENCE else 1

        candidates.sort(key=lambda n: (bucket(n), curated(n), *cap_key(n), default_index(n)))
        logger.info(
            f"[ModelRegistry] route_order(private={private}, high_volume={high_volume}, "
            f"task={task}) → {candidates}"
        )
        return candidates

    def healthy_active_provider_keys(self, available: list[str]) -> set[str]:
        """Distinct provider_keys that are active, built, and currently healthy (for the ≥3 floor)."""
        keys: set[str] = set()
        for name in available:
            spec = self.specs.get(name)
            if spec is None or spec.provider == "webui" or spec.status != "active":
                continue
            if self.error_log.is_healthy(name):
                keys.add(spec.provider)
        return keys

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
