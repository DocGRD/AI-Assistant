"""
Typed / templated notes — Milestone 40 (best-effort, D-authoring).

Integrate rather than reinvent: if the user has the Templater community plugin (or the core
Templates plugin), Loremaster can take one of *their* templates and fill its AI-fillable
fields from context, then write a **propose-only** note under `AI/Proposed/`. Templater's own
`<% ... %>` tags are left untouched so Templater still runs them; only `{{field}}` and
`<!-- fill: instruction -->` markers are filled by the model. Falls back to filling a
template given by path when no plugin is installed.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("assistant")

PROPOSED_DIR = "AI/Proposed"
_FIELD_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")
_FILL_RE = re.compile(r"<!--\s*fill:\s*(.+?)\s*-->", re.IGNORECASE | re.DOTALL)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:50] or "note"


def templates_folder(vault) -> str:
    """The configured templates folder (Templater first, then the core Templates plugin), or ''."""
    for rel, keys in ((".obsidian/plugins/templater-obsidian/data.json",
                       ("templates_folder", "template_folder")),
                      (".obsidian/templates.json", ("folder",))):
        try:
            d = json.loads((Path(vault) / rel).read_text(encoding="utf-8"))
            for k in keys:
                if d.get(k):
                    return str(d[k]).strip("/")
        except Exception:
            continue
    return ""


def list_templates(vault) -> list[str]:
    tf = templates_folder(vault)
    if not tf:
        return []
    d = Path(vault) / tf
    return sorted(p.stem for p in d.glob("*.md")) if d.is_dir() else []


def _resolve(vault, name: str) -> Path | None:
    name = (name or "").strip()
    if not name:
        return None
    cands = []
    tf = templates_folder(vault)
    fname = name if name.endswith(".md") else name + ".md"
    if tf:
        cands.append(Path(vault) / tf / fname)
    cands.append(Path(vault) / fname)                 # direct path fallback
    return next((c for c in cands if c.exists()), None)


def _markers(text: str) -> list[tuple[str, str]]:
    """(raw_placeholder, field_description) for each AI-fillable marker, deduped."""
    out, seen = [], set()
    for m in _FIELD_RE.finditer(text):
        raw, field = m.group(0), m.group(1).strip()
        if field.lower() not in ("title", "date", "time") and raw not in seen:  # skip obvious auto fields
            seen.add(raw); out.append((raw, field))
    for m in _FILL_RE.finditer(text):
        raw, field = m.group(0), m.group(1).strip()
        if raw not in seen:
            seen.add(raw); out.append((raw, field))
    return out


def _fill_values(markers, context, router, private) -> dict[str, str]:
    if router is None or not markers:
        return {}
    from assistant_core.providers.base_provider import Message
    fields = "\n".join(f"- {f}" for _, f in markers)
    prompt = ("Fill each field below from the context. Output ONLY `FIELD: value` lines, one per "
              "field, concise, no commentary.\n\nFIELDS:\n" + fields +
              "\n\nCONTEXT:\n" + (context or "(no extra context — use sensible placeholders)")[:2000])
    try:
        reply, _ = router.generate([Message(role="user", content=prompt)],
                                   task="extract", private=private, allow_webui=False)
    except Exception as exc:
        logger.info(f"[templater] fill call failed: {exc}")
        return {}
    values = {}
    for line in (reply or "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            values[k.strip().lstrip("-* ").strip()] = v.strip()
    return values


def fill_template(vault, name: str, context: str = "", router=None,
                  private: bool = False, now: datetime | None = None) -> dict:
    """Fill `name`'s AI markers from `context` and write a propose-only note. Returns
    {ok, path, fields, filled} — ok=False with `reason` if the template can't be found."""
    now = now or datetime.now()
    tpl = _resolve(vault, name)
    if tpl is None:
        return {"ok": False, "reason": f"template '{name}' not found", "path": None}
    try:
        text = tpl.read_text(encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "path": None}

    markers = _markers(text)
    values = _fill_values(markers, context, router, private)
    filled_n = 0
    out = text
    for raw, field in markers:
        val = values.get(field) or values.get(field.lower())
        if val:
            out = out.replace(raw, val); filled_n += 1
        else:
            out = out.replace(raw, f"({field})")       # leave a visible placeholder

    rel = f"{PROPOSED_DIR}/template-{_slug(name)}-{now.strftime('%Y%m%d-%H%M%S')}.md"
    dest = Path(vault) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(out, encoding="utf-8")
    logger.info(f"[templater] filled '{name}' → {rel} ({filled_n}/{len(markers)} fields)")
    return {"ok": True, "path": rel, "fields": len(markers), "filled": filled_n}
