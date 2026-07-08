"""
Approval feedback — Milestone 35.1 (the seed of the C7 feedback loop).

Records which *suggested* items the user accepts or rejects (organize tags, related
links, …) as simple accept/reject counts in ``data/feedback.json``, and exposes
``suppressed()`` / ``boosted()`` so future suggestions can **drop what the user keeps
rejecting** and **prefer what they accept**.

Private-safe by construction: only the suggested value (a tag string or a note stem)
and, for links, the note it was suggested *for* are stored — never a note body — and
there are no model calls. ``kind`` groups the space (``"tag"``, ``"link"``, later
``"memory"``/``"edit"`` in M36); ``scope`` narrows a value (per-note for links, so a
link rejected on one note isn't suppressed everywhere).
"""

import json
import logging

from assistant_core.paths import DATA_DIR

logger = logging.getLogger("assistant")

_FILE = DATA_DIR / "feedback.json"
_MIN_REJECT = 2   # need at least this many rejects (and reject > accept) before suppressing


def _load() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug(f"[Feedback] write failed: {exc}")


def _key(value: str, scope: str) -> str:
    return f"{scope}||{value}" if scope else value


def record(kind: str, value: str, accepted: bool, scope: str = "") -> None:
    """Log one accept/reject for a suggested item."""
    if not value:
        return
    data = _load()
    bucket = data.setdefault(kind, {})
    entry = bucket.setdefault(_key(value, scope), {"accept": 0, "reject": 0})
    entry["accept" if accepted else "reject"] += 1
    _save(data)


def counts(kind: str, value: str, scope: str = "") -> dict:
    return _load().get(kind, {}).get(_key(value, scope), {"accept": 0, "reject": 0})


def suppressed(kind: str, value: str, scope: str = "") -> bool:
    """True once the user has rejected this item enough (and more often than accepted)."""
    c = counts(kind, value, scope)
    return c["reject"] >= _MIN_REJECT and c["reject"] > c["accept"]


def boosted(kind: str, value: str, scope: str = "") -> bool:
    """True when the user has accepted this item at least as often as rejected it."""
    c = counts(kind, value, scope)
    return c["accept"] > 0 and c["accept"] >= c["reject"]
