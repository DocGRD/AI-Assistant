"""
Study reinforcement / spaced repetition — Milestone 28.

Generate review flashcards from a note (one non-agentic LLM call), then schedule them with
a simple SM-2 algorithm so you review at expanding intervals. Cards + scheduling state live
in `AI/Review/deck.json`; `vault:cards <note>` adds cards, `vault:review` shows what's due.
Pure/deterministic scheduling — tested without a model.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("assistant")

DECK_REL = "AI/Review/deck.json"

CARD_SYSTEM = (
    "Make up to 6 spaced-repetition flashcards from the text. Output each card on two lines:\n"
    "Q: <a specific question>\nA: <a short, correct answer>\n"
    "Separate cards with a blank line. Only facts clearly in the text. If none, output NONE."
)


def _today() -> str:
    return date.today().isoformat()


def parse_cards(reply: str) -> list[dict]:
    if reply.strip().upper().startswith("NONE"):
        return []
    cards, q = [], None
    for line in reply.splitlines():
        m = re.match(r"^\s*Q:\s*(.+)$", line, re.I)
        a = re.match(r"^\s*A:\s*(.+)$", line, re.I)
        if m:
            q = m.group(1).strip()
        elif a and q:
            cards.append({"q": q, "a": a.group(1).strip()})
            q = None
    return cards


def generate_cards(router, text: str) -> list[dict]:
    if router is None or not text.strip():
        return []
    from assistant_core.providers.base_provider import Message
    try:
        reply, _ = router.generate(messages=[Message(role="user", content=text[:6000])],
                                   system_prompt=CARD_SYSTEM, max_tokens=500, temperature=0.3,
                                   private=True, allow_webui_on_private=False)
    except Exception as exc:
        logger.warning(f"[Study] card generation failed: {exc}")
        return []
    return parse_cards(reply or "")


def _load(vault) -> list[dict]:
    try:
        return json.loads((Path(vault) / DECK_REL).read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(vault, deck: list[dict]) -> None:
    p = Path(vault) / DECK_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(deck, indent=1), encoding="utf-8")


def _new_card(q: str, a: str, source: str, today: str) -> dict:
    cid = hashlib.sha1((q + a).encode("utf-8")).hexdigest()[:12]
    return {"id": cid, "q": q, "a": a, "source": source,
            "ease": 2.5, "interval": 0, "reps": 0, "due": today}


def add_cards(vault, cards: list[dict], source: str, today: str | None = None) -> int:
    """Add new (non-duplicate) cards to the deck, due today. Returns how many were added."""
    today = today or _today()
    deck = _load(vault)
    have = {c["id"] for c in deck}
    added = 0
    for c in cards:
        card = _new_card(c["q"], c["a"], source, today)
        if card["id"] not in have:
            deck.append(card); have.add(card["id"]); added += 1
    _save(vault, deck)
    return added


def sm2(card: dict, grade: int, today: str | None = None) -> dict:
    """Update a card in place with SM-2 given grade 0-5 (>=3 passes). Returns the card."""
    today_d = datetime.strptime(today or _today(), "%Y-%m-%d").date()
    if grade < 3:
        card["reps"], card["interval"] = 0, 1
    else:
        card["reps"] += 1
        card["interval"] = 1 if card["reps"] == 1 else (6 if card["reps"] == 2
                                                        else round(card["interval"] * card["ease"]))
    card["ease"] = max(1.3, card["ease"] + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)))
    card["ease"] = round(card["ease"], 2)
    card["due"] = (today_d + timedelta(days=card["interval"])).isoformat()
    return card


def due_cards(vault, today: str | None = None) -> list[dict]:
    today = today or _today()
    return [c for c in _load(vault) if c.get("due", today) <= today]


def review(vault, card_id: str, grade: int, today: str | None = None) -> bool:
    """Grade one card (0-5), reschedule, persist. Returns False if the card is unknown."""
    deck = _load(vault)
    for c in deck:
        if c["id"] == card_id:
            sm2(c, grade, today)
            _save(vault, deck)
            return True
    return False
