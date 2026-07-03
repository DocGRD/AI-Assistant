"""
Live model discovery — Milestone 10 extension.

Ask each provider's own OpenAI-compatible `/models` endpoint which models YOUR
account can actually use, instead of trusting a curated third-party list. This is
the authoritative source: the same call that confirmed the registry's `active`
rows. Used by the `vault:models` command (report) and, later, to propose registry
rows from discovery.

`list_fn` is injectable so tests never hit the network.
"""

import logging

logger = logging.getLogger("assistant")


def _default_list_fn(base_url: str, api_key: str) -> list[str]:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=20, max_retries=0)
    return sorted(m.id for m in client.models.list().data)


def discover_models(providers: dict[str, str], config: dict, list_fn=None) -> dict[str, dict]:
    """
    For each `{provider_key: base_url}`, query `<base_url>/models` with the key from
    settings (`<provider_key>_api_key`). Returns
    `{provider_key: {"models": [ids], "error": None | str}}` — never raises.
    """
    list_fn = list_fn or _default_list_fn
    out: dict[str, dict] = {}
    for prov, base_url in providers.items():
        key = str(config.get(f"{prov}_api_key", "")).strip()
        if not key:
            out[prov] = {"models": [], "error": "no api key set"}
            continue
        try:
            out[prov] = {"models": list(list_fn(base_url, key)), "error": None}
        except Exception as exc:
            out[prov] = {"models": [], "error": f"{type(exc).__name__}: {exc}"}
            logger.warning(f"[Discovery] {prov} /models failed: {exc}")
    return out
