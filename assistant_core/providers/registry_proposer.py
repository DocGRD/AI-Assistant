"""
Self-discovering registry — Milestone 16.7.

Build a *proposed* Provider-Registry.md from each provider's own `/models` endpoint
(via model_discovery) instead of a curated third-party list. Two jobs:

  1. Keep only **chat** models (a heuristic prefilter drops embeddings, whisper/TTS,
     guard/rerank, image/audio/live variants — the stuff `/models` also lists).
  2. **Classify** each kept model by what it's good at (`strengths`), from id heuristics
     plus an editable `AI/System/Model-Capabilities.md` override map (future).

Output is propose/commit: written to `Provider-Registry-proposed.md`; the existing
`vault:update-providers apply` commits it. This is a **merge, not a clobber**: a model already
in the live registry keeps ALL its curated values (context/tpm/rpm/rpd/tpd, trains_on_data,
status, strengths, hand-edited notes), matched tolerantly of a `models/` prefix drift. A
genuinely NEW chat model comes in **candidate** with `?` limits (rate limits are dashboard-only,
not discoverable via /models). The only promotion to **active** is a successful completion probe, for
every provider. Generative-media / embodied models (imagen/veo/lyria/robotics/…) are routed to the
non-chat table so they're never chat-activated.
Written ids have a leading `models/` stripped.
"""

from __future__ import annotations

from datetime import date

from assistant_core.providers.registry_loader import NO_KNOWN_LIMIT

# id substrings that mean "not a normal chat model" → split into a separate table
# (NOT dropped — we'll likely want embeddings / transcription / safety models later).
_NON_CHAT = (
    "embed", "embedding", "whisper", "-tts", "tts-", "rerank", "guard", "safeguard",
    "-image", "image-", "-vision-embed", "-audio", "audio-", "-live", "live-", "moderation",
    "diffusion", "deplot", "fuyu", "kosmos", "orpheus", "starcoder", "codegemma", "codestral",
    # generative-media / embodied families that are NOT chat-completion models — they'd error
    # if routed for chat, so they must never be auto-activated (they go to the non-chat table).
    "imagen", "veo", "lyria", "nano-banana", "robotics", "-er-", "gemini-robotics",
)

# (substring, category) — classify the non-chat models we keep in the second table.
_NON_CHAT_CATEGORY: list[tuple[str, str]] = [
    ("embedding", "embedding"), ("embed", "embedding"),
    ("whisper", "transcription"), ("-audio", "audio"), ("audio-", "audio"),
    ("-tts", "text-to-speech"), ("tts-", "text-to-speech"), ("orpheus", "text-to-speech"),
    ("guard", "safety"), ("safeguard", "safety"), ("moderation", "safety"),
    ("rerank", "rerank"),
    ("imagen", "image"), ("nano-banana", "image"), ("veo", "video"), ("lyria", "music"),
    ("robotics", "robotics"), ("-er-", "robotics"),
    ("-image", "image"), ("image-", "image"), ("diffusion", "image"), ("fuyu", "image"),
    ("-live", "live"), ("live-", "live"), ("kosmos", "multimodal"), ("deplot", "multimodal"),
    ("codegemma", "code"), ("codestral", "code"), ("starcoder", "code"),
]


def classify_non_chat(model_id: str) -> str:
    low = model_id.lower()
    for sub, cat in _NON_CHAT_CATEGORY:
        if sub in low:
            return cat
    return "other"

# (substring, tag) — first matches win; a model can collect several tags
_CAPABILITY_RULES: list[tuple[str, str]] = [
    ("gpt-oss", "reasoning"), ("qwen3", "reasoning"), ("qwq", "reasoning"),
    ("deepseek-r1", "reasoning"), ("deepseek-v", "reasoning"), ("glm-4", "reasoning"),
    ("scout", "multimodal"), ("maverick", "multimodal"), ("vision", "multimodal"),
    ("-vl", "multimodal"), ("flash", "fast"), ("lite", "fast"), ("instant", "fast"),
    ("mini", "small"), ("8b", "small"), ("7b", "small"), ("3b", "small"), ("2b", "small"),
    ("coder", "code"), ("code", "code"),
    ("70b", "quality"), ("120b", "quality"), ("235b", "quality"), ("large", "quality"),
    ("pro", "quality"), ("gemini", "long-context"),
]


def is_chat_model(model_id: str) -> bool:
    low = model_id.lower()
    return not any(bad in low for bad in _NON_CHAT)


def classify_strengths(model_id: str) -> list[str]:
    low = model_id.lower()
    tags: list[str] = []
    for sub, tag in _CAPABILITY_RULES:
        if sub in low and tag not in tags:
            tags.append(tag)
    return tags or ["general"]


def _trains_on_data(provider: str) -> str:
    return {"groq": "no", "cerebras": "no", "google": "yes", "nvidia": "logs"}.get(provider, "varies")


def bare_model_id(mid: str) -> str:
    """Id stored in the proposal table. Google's `/models` returns `models/gemini-2.5-flash`;
    the adapter needs the bare id, so a leading `models/` is stripped. Case is preserved."""
    if mid.lower().startswith("models/"):
        return mid[len("models/"):]
    return mid


def _norm_id(mid: str) -> str:
    """Normalize a model id for matching against the curated registry. Google's `/models`
    returns `models/gemini-2.5-flash` while the registry may store it bare as `gemini-2.5-flash`;
    without this, that prefix drift makes a KNOWN model look brand-new and its curated limits get
    wiped. Strip a leading `models/` and lowercase."""
    return bare_model_id(mid).lower()


def _fmt_limit(val) -> str:
    """Render a ModelSpec limit int back into a table cell: unknown → '?', else the number."""
    if val in (None, 0, NO_KNOWN_LIMIT):
        return "?"
    return str(val)


class DiscoveredRow:
    """One id from a provider's /models list, matched to the curated registry."""

    def __init__(self, provider: str, model_id: str, norm_id: str, chat: bool, prev):
        self.provider = provider
        self.model_id = model_id
        self.norm_id = norm_id
        self.chat = chat
        self.prev = prev


def iter_discovered_rows(discovered: dict[str, dict], existing_specs: list) -> list[DiscoveredRow]:
    """Chat and non-chat rows in provider order. Model ids are stored bare (no `models/`)."""
    existing = {(s.provider, _norm_id(s.model_id)): s for s in existing_specs}
    rows: list[DiscoveredRow] = []
    for provider, info in sorted(discovered.items()):
        if info.get("error"):
            continue
        for mid in info["models"]:
            bare = bare_model_id(mid)
            prev = existing.get((provider, _norm_id(bare)))
            rows.append(DiscoveredRow(provider, bare, _norm_id(bare), is_chat_model(bare), prev))
    return rows


def _probe_outcome(probe) -> tuple[str | None, str]:
    if not probe:
        return None, ""
    if isinstance(probe, str):
        return probe, ""
    if isinstance(probe, dict):
        return probe.get("outcome"), str(probe.get("detail") or "")
    return getattr(probe, "outcome", None), str(getattr(probe, "detail", "") or "")


def _clean_note(text: str) -> str:
    return " ".join((text or "").replace("|", "/").split())


def resolve_status(prev_status: str | None, outcome: str | None, *,
                   auto_promote: bool) -> str:
    """Status for one chat row after an optional probe.

    New rows default to candidate. The only promotion to active is a successful
    probe, and that is allowed for every provider. 404 demotes to deprecated.
    Timeout/5xx leaves a candidate. 429 keeps a curated active row. 401/403 does
    not promote and does not demote.
    """
    base = prev_status or "candidate"
    if outcome is None:
        return base
    if outcome == "ok":
        if prev_status == "active" or auto_promote:
            return "active"
        return "candidate"
    if outcome == "not_found":
        return "deprecated"
    if outcome == "auth":
        return base
    if outcome == "rate_limited":
        return "active" if prev_status == "active" else "candidate"
    if outcome == "failed":
        return "candidate"
    return base


def _probe_annotation(outcome: str, detail: str, today: str) -> str:
    if outcome == "ok":
        return f"probed OK {today}"
    if outcome == "not_found":
        return "probe failed: " + (_clean_note(detail) or "not found")
    if outcome == "rate_limited":
        return "probe rate-limited"
    if outcome == "auth":
        return "probe auth error"
    return "probe failed: " + (_clean_note(detail) or "error")


def build_proposed_registry(discovered: dict[str, dict], existing_specs: list,
                            base_urls: dict[str, str], probe_results=None,
                            probe_config: dict | None = None, today: str | None = None) -> str:
    """
    `discovered` = {provider: {"models": [ids], "error": str|None}} (from discover_models).
    `existing_specs` = current ModelSpecs — MERGED, not clobbered: a model already in the
    registry keeps ALL its curated values (context/tpm/rpm/rpd/tpd, trains_on_data, status,
    strengths, notes), matched tolerantly of a `models/` prefix drift. A genuinely new chat
    model comes in **candidate** with `?` limits. `probe_results` maps
    `(provider, normalized id)` to a probe outcome; OK promotes any provider.
    Returns a complete Provider-Registry-proposed.md as a string (propose/commit).
    """
    cfg = probe_config or {}
    auto_promote = bool(cfg.get("discovery_auto_active_on_probe", True))
    probe_results = probe_results or {}
    stamp = today or date.today().isoformat()
    chat_rows: list[tuple] = []        # (provider, mid, ctx, tpm, rpm, rpd, tpd, trains, status, strengths, note)
    other_rows: list[tuple] = []       # (provider, model_id, category, note)
    for row in iter_discovered_rows(discovered, existing_specs):
        prev = row.prev
        mid = row.model_id
        provider = row.provider
        if not row.chat:
            # Keep it — embeddings/transcription/safety/media/etc. land in a second table.
            note = (prev.notes if (prev and getattr(prev, "notes", ""))
                    else "discovered from /models — specialized (non-chat)")
            other_rows.append((provider, mid, classify_non_chat(mid), note))
            continue
        outcome, detail = _probe_outcome(probe_results.get((provider, row.norm_id)))
        prev_status = (getattr(prev, "status", None) or None) if prev is not None else None
        status = resolve_status(prev_status, outcome, auto_promote=auto_promote)
        ctx    = _fmt_limit(getattr(prev, "context_window", None))
        tpm    = _fmt_limit(getattr(prev, "tpm_limit", None))
        rpm    = _fmt_limit(getattr(prev, "rpm_limit", None))
        rpd    = _fmt_limit(getattr(prev, "rpd_limit", None))
        tpd    = _fmt_limit(getattr(prev, "tpd_limit", None))
        trains = (getattr(prev, "trains_on_data", "") or "").strip() or _trains_on_data(provider)
        prev_strengths = getattr(prev, "strengths", None)
        strengths = " ".join(prev_strengths) if prev_strengths else " ".join(classify_strengths(mid))
        if prev and getattr(prev, "notes", ""):
            note = getattr(prev, "notes", "")
        elif outcome:
            note = ""
        else:
            note = "discovered from /models — candidate until probed"
        if outcome:
            extra = _probe_annotation(outcome, detail, stamp)
            note = f"{note}; {extra}" if note else extra
        chat_rows.append((provider, mid, ctx, tpm, rpm, rpd, tpd, trains, status, strengths, note))

    lines = [
        "# Provider Registry — PROPOSED (from live /models discovery)",
        "",
        "*Generated by `vault:discover-providers`. Review, then `vault:update-providers apply` to commit.*",
        "*Chat models capability-tagged. RPDs are not discoverable via /models — carried over or `?`.*",
        "",
        "| provider_key | base_url | model_id | context_window | tpm | rpm | rpd | tpd | trains_on_data | status | strengths | notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for provider, mid, ctx, tpm, rpm, rpd, tpd, trains, status, strengths, note in chat_rows:
        base = base_urls.get(provider, "")
        lines.append(f"| {provider} | {base} | {mid} | {ctx} | {tpm} | {rpm} | {rpd} | {tpd} | "
                     f"{trains} | {status} | {strengths} | {note} |")

    # Second table — specialized / non-chat models, kept for future use (embeddings,
    # transcription, TTS, safety, rerank, image). Not routed for chat; listed so we can
    # promote one when a feature needs it instead of rediscovering it.
    lines += [
        "",
        "## Specialized / non-chat models (not routed for chat — kept for future use)",
        "",
        "| provider_key | base_url | model_id | category | notes |",
        "|---|---|---|---|---|",
    ]
    for provider, mid, category, note in other_rows:
        base = base_urls.get(provider, "")
        lines.append(f"| {provider} | {base} | {mid} | {category} | {note} |")
    lines.append("")
    return "\n".join(lines)
