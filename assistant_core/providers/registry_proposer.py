"""
Self-discovering registry — Milestone 16.7.

Build a *proposed* Provider-Registry.md from each provider's own `/models` endpoint
(via model_discovery) instead of a curated third-party list. Two jobs:

  1. Keep only **chat** models (a heuristic prefilter drops embeddings, whisper/TTS,
     guard/rerank, image/audio/live variants — the stuff `/models` also lists).
  2. **Classify** each kept model by what it's good at (`strengths`), from id heuristics
     plus an editable `AI/System/Model-Capabilities.md` override map (future).

Output is propose/commit: written to `Provider-Registry-proposed.md`; the existing
`vault:update-providers apply` commits it. Models already `active` in the live registry
keep that status + their hand-edited notes; everything new is `candidate` (register, then
promote after `vault:models` / a probe confirms it). RPDs are NOT discoverable via /models
(dashboard-only), so they are carried over from the existing registry or left `?`.
"""

from __future__ import annotations

# id substrings that mean "not a normal chat model" → split into a separate table
# (NOT dropped — we'll likely want embeddings / transcription / safety models later).
_NON_CHAT = (
    "embed", "embedding", "whisper", "-tts", "tts-", "rerank", "guard", "safeguard",
    "-image", "image-", "-vision-embed", "-audio", "audio-", "-live", "live-", "moderation",
    "diffusion", "deplot", "fuyu", "kosmos", "orpheus", "starcoder", "codegemma", "codestral",
)

# (substring, category) — classify the non-chat models we keep in the second table.
_NON_CHAT_CATEGORY: list[tuple[str, str]] = [
    ("embedding", "embedding"), ("embed", "embedding"),
    ("whisper", "transcription"), ("-audio", "audio"), ("audio-", "audio"),
    ("-tts", "text-to-speech"), ("tts-", "text-to-speech"), ("orpheus", "text-to-speech"),
    ("guard", "safety"), ("safeguard", "safety"), ("moderation", "safety"),
    ("rerank", "rerank"),
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


def build_proposed_registry(discovered: dict[str, dict], existing_specs: list,
                            base_urls: dict[str, str]) -> str:
    """
    `discovered` = {provider: {"models": [ids], "error": str|None}} (from discover_models).
    `existing_specs` = current ModelSpecs (to preserve active status + notes + RPD).
    Returns a complete Provider-Registry-proposed.md as a string (propose/commit).
    """
    existing = {(s.provider, s.model_id): s for s in existing_specs}
    chat_rows: list[tuple] = []        # (provider, model_id, status, strengths, rpd, ctx, trains, note)
    other_rows: list[tuple] = []       # (provider, model_id, category, note)
    for provider, info in sorted(discovered.items()):
        if info.get("error"):
            continue
        for mid in info["models"]:
            prev = existing.get((provider, mid))
            if not is_chat_model(mid):
                # Keep it — embeddings/transcription/safety/etc. land in a second table.
                note = (prev.notes if (prev and getattr(prev, "notes", ""))
                        else "discovered from /models — specialized (non-chat)")
                other_rows.append((provider, mid, classify_non_chat(mid), note))
                continue
            status = prev.status if prev else "candidate"
            rpd = prev.rpd_limit if (prev and getattr(prev, "rpd_limit", None)) else "?"
            ctx = prev.context_window if (prev and getattr(prev, "context_window", None)) else "?"
            note = prev.notes if (prev and getattr(prev, "notes", "")) else "discovered from /models — confirm before promoting"
            chat_rows.append((provider, mid, status, " ".join(classify_strengths(mid)),
                              rpd, ctx, _trains_on_data(provider), note))

    lines = [
        "# Provider Registry — PROPOSED (from live /models discovery)",
        "",
        "*Generated by `vault:discover-providers`. Review, then `vault:update-providers apply` to commit.*",
        "*Chat models capability-tagged. RPDs are not discoverable via /models — carried over or `?`.*",
        "",
        "| provider_key | base_url | model_id | context_window | tpm | rpm | rpd | tpd | trains_on_data | status | strengths | notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for provider, mid, status, strengths, rpd, ctx, trains, note in chat_rows:
        base = base_urls.get(provider, "")
        lines.append(f"| {provider} | {base} | {mid} | {ctx} | ? | ? | {rpd} | ? | "
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
