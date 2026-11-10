"""
Minimal chat-completion probe for provider discovery.

A listed model id is not evidence that a free-tier chat completion works.
This module sends one tiny `/chat/completions` request per selected id and
classifies the HTTP result. Registry status (active / candidate / deprecated)
is decided by registry_proposer, not here.

Caps live in settings (`discovery_probe_max`). `discovery_probe_providers` only
decides who is probed first so one large catalogue cannot use the whole budget.
A successful probe can promote a model from any provider.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

logger = logging.getLogger("assistant")

PROBE_WORKERS = 3
DEFAULT_PROBE_PROVIDERS = ("groq", "cerebras", "google")


@dataclass(frozen=True)
class ProbeResult:
    outcome: str  # ok | not_found | auth | rate_limited | failed
    detail: str = ""


@dataclass
class ProbeRun:
    results: dict[tuple[str, str], ProbeResult] = field(default_factory=dict)
    provider_errors: list[str] = field(default_factory=list)
    probed: int = 0


def _snip(text: str, limit: int = 120) -> str:
    return " ".join((text or "").replace("|", "/").split())[:limit]


def _assistant_text(body: str) -> str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return ""
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(part))
        content = "".join(parts)
    return str(content or "").strip()


def classify_probe_response(status: int, body: str) -> ProbeResult:
    """Map a completion response to a probe outcome. Pure — no I/O."""
    text = body or ""
    low = text.lower()
    if status in (401, 403):
        return ProbeResult("auth", _snip(text) or f"HTTP {status}")
    if status == 429:
        return ProbeResult("rate_limited", _snip(text) or "429")
    if (status == 404 or "model_not_found" in low or "model_decommissioned" in low
            or "decommissioned" in low):
        return ProbeResult("not_found", _snip(text) or f"HTTP {status}")
    if 200 <= status < 300:
        if _assistant_text(text):
            return ProbeResult("ok", "")
        return ProbeResult("failed", "empty completion")
    return ProbeResult("failed", _snip(text) or f"HTTP {status}")


def probe_chat_completion(base_url: str, api_key: str, model_id: str,
                          timeout: float = 20) -> ProbeResult:
    """POST one ping completion. Never raises."""
    url = str(base_url or "").rstrip("/") + "/chat/completions"
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 16,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return classify_probe_response(getattr(resp, "status", 200) or 200, body)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(exc)
        return classify_probe_response(getattr(exc, "code", 0) or 0, body)
    except TimeoutError:
        return ProbeResult("failed", "timeout")
    except Exception as exc:
        return ProbeResult("failed", f"{type(exc).__name__}: {exc}")


def _provider_set(config: dict) -> set[str]:
    raw = config.get("discovery_probe_providers", list(DEFAULT_PROBE_PROVIDERS))
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    return {str(p).strip() for p in (raw or []) if str(p).strip()}


def _probe_max(config: dict) -> int:
    try:
        return max(0, int(config.get("discovery_probe_max", 30)))
    except (TypeError, ValueError):
        return 30


def select_probe_rows(rows, config: dict) -> list:
    """Who gets a completion probe, capped by `discovery_probe_max`.

    Order: previously active rows (any provider), then new chat models.
    `discovery_probe_providers` is a priority list, not an allowlist — those
    providers are probed first, and other providers fill whatever budget remains.
    A successful result may promote any provider; this function only spends the
    probe budget.
    """
    preferred = _provider_set(config)
    active_rows = []
    preferred_new = []
    other_new = []
    for row in rows:
        if not getattr(row, "chat", False):
            continue
        prev = getattr(row, "prev", None)
        prev_status = getattr(prev, "status", None) if prev is not None else None
        if prev_status == "active":
            active_rows.append(row)
        elif prev is None:
            bucket = preferred_new if (not preferred or row.provider in preferred) else other_new
            bucket.append(row)
    return (active_rows + preferred_new + other_new)[:_probe_max(config)]


def run_probes(rows, base_urls: dict[str, str], config: dict, probe_fn=None) -> ProbeRun:
    """Probe the selected rows. Auth failure blocks the rest of that provider
    and prevents any of its models from being treated as probe-OK."""
    targets = select_probe_rows(rows, config)
    call = probe_fn or probe_chat_completion
    pending = list(targets)
    results: dict[tuple[str, str], ProbeResult] = {}
    blocked: set[str] = set()
    provider_errors: list[str] = []
    probed = 0

    while pending:
        batch = []
        while pending and len(batch) < PROBE_WORKERS:
            row = pending.pop(0)
            if row.provider in blocked:
                continue
            batch.append(row)
        if not batch:
            break

        def _one(row):
            key = str(config.get(f"{row.provider}_api_key", "")).strip()
            base = base_urls.get(row.provider, "")
            if not key or not base:
                return row, ProbeResult("failed", "no api key" if not key else "no base_url")
            try:
                return row, call(base, key, row.model_id)
            except Exception as exc:
                return row, ProbeResult("failed", f"{type(exc).__name__}: {exc}")

        with ThreadPoolExecutor(max_workers=min(PROBE_WORKERS, len(batch))) as pool:
            futures = [pool.submit(_one, row) for row in batch]
            for fut in as_completed(futures):
                row, result = fut.result()
                results[(row.provider, row.norm_id)] = result
                probed += 1
                if result.outcome == "auth" and row.provider not in blocked:
                    blocked.add(row.provider)
                    provider_errors.append(row.provider)
                    logger.warning("[Discovery] %s probe auth error — skipping the rest", row.provider)

    for key, result in list(results.items()):
        if key[0] in blocked and result.outcome != "auth":
            results[key] = ProbeResult("auth", "provider auth error")
    return ProbeRun(results=results, provider_errors=provider_errors, probed=probed)
