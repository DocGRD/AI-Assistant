"""On-demand Bible versions (ESV / NASB / NKJV) via their official APIs.

The offline base version is WEB (public domain, bundled). Other translations are fetched live from
their licensed providers and returned as `{verse_number: text}` + a copyright line. The PLUGIN caches
each fetched chapter as a normal `bible/{book}/{version}/…` note, so the reader's cross-references,
red-letter, hovercards, etc. all work and a chapter is only ever fetched once.

Providers:
  * ESV      — api.esv.org (needs the user's free key; terms cap caching at 500 verses → the plugin
               enforces an LRU cap for esv/). Attribution required.
  * NASB/NKJV — api.scripture.api.bible ("Starter", non-commercial; needs the user's key + the
               bible-id for each translation, since which bibles a key can see varies).

Keys + bible-ids come from the service settings (esv_api_key, apibible_api_key,
apibible_nasb_id, apibible_nkjv_id) — never from the vault or the plugin.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request

logger = logging.getLogger("assistant")

# slug -> (display name for ESV queries, USFM id for API.Bible chapter ids)
_BOOKS = {
    "genesis": ("Genesis", "GEN"), "exodus": ("Exodus", "EXO"), "leviticus": ("Leviticus", "LEV"),
    "numbers": ("Numbers", "NUM"), "deuteronomy": ("Deuteronomy", "DEU"), "joshua": ("Joshua", "JOS"),
    "judges": ("Judges", "JDG"), "ruth": ("Ruth", "RUT"), "1-samuel": ("1 Samuel", "1SA"),
    "2-samuel": ("2 Samuel", "2SA"), "1-kings": ("1 Kings", "1KI"), "2-kings": ("2 Kings", "2KI"),
    "1-chronicles": ("1 Chronicles", "1CH"), "2-chronicles": ("2 Chronicles", "2CH"),
    "ezra": ("Ezra", "EZR"), "nehemiah": ("Nehemiah", "NEH"), "esther": ("Esther", "EST"),
    "job": ("Job", "JOB"), "psalms": ("Psalms", "PSA"), "proverbs": ("Proverbs", "PRO"),
    "ecclesiastes": ("Ecclesiastes", "ECC"), "song-of-solomon": ("Song of Solomon", "SNG"),
    "isaiah": ("Isaiah", "ISA"), "jeremiah": ("Jeremiah", "JER"), "lamentations": ("Lamentations", "LAM"),
    "ezekiel": ("Ezekiel", "EZK"), "daniel": ("Daniel", "DAN"), "hosea": ("Hosea", "HOS"),
    "joel": ("Joel", "JOL"), "amos": ("Amos", "AMO"), "obadiah": ("Obadiah", "OBA"),
    "jonah": ("Jonah", "JON"), "micah": ("Micah", "MIC"), "nahum": ("Nahum", "NAM"),
    "habakkuk": ("Habakkuk", "HAB"), "zephaniah": ("Zephaniah", "ZEP"), "haggai": ("Haggai", "HAG"),
    "zechariah": ("Zechariah", "ZEC"), "malachi": ("Malachi", "MAL"), "matthew": ("Matthew", "MAT"),
    "mark": ("Mark", "MRK"), "luke": ("Luke", "LUK"), "john": ("John", "JHN"), "acts": ("Acts", "ACT"),
    "romans": ("Romans", "ROM"), "1-corinthians": ("1 Corinthians", "1CO"),
    "2-corinthians": ("2 Corinthians", "2CO"), "galatians": ("Galatians", "GAL"),
    "ephesians": ("Ephesians", "EPH"), "philippians": ("Philippians", "PHP"),
    "colossians": ("Colossians", "COL"), "1-thessalonians": ("1 Thessalonians", "1TH"),
    "2-thessalonians": ("2 Thessalonians", "2TH"), "1-timothy": ("1 Timothy", "1TI"),
    "2-timothy": ("2 Timothy", "2TI"), "titus": ("Titus", "TIT"), "philemon": ("Philemon", "PHM"),
    "hebrews": ("Hebrews", "HEB"), "james": ("James", "JAS"), "1-peter": ("1 Peter", "1PE"),
    "2-peter": ("2 Peter", "2PE"), "1-john": ("1 John", "1JN"), "2-john": ("2 John", "2JN"),
    "3-john": ("3 John", "3JN"), "jude": ("Jude", "JUD"), "revelation": ("Revelation", "REV"),
}

SUPPORTED = ("esv", "nasb", "nkjv")


def _http_get(url: str, headers: dict, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _split_numbered(text: str) -> dict:
    """Both providers can return verse text with inline `[N]` markers. Split into {n: text}."""
    verses: dict[int, str] = {}
    parts = re.split(r"\[(\d+)\]", text)
    # parts = [pre, "1", body1, "2", body2, ...]
    for i in range(1, len(parts) - 1, 2):
        try:
            n = int(parts[i])
        except ValueError:
            continue
        body = re.sub(r"\s+", " ", parts[i + 1]).strip()
        # drop a trailing "(ESV)"/reference tail that some responses append to the last verse
        body = re.sub(r"\s*\([A-Z0-9 ]{2,8}\)\s*$", "", body)
        if body:
            verses[n] = body
    return verses


def _fetch_esv(book: str, chapter: int, cfg: dict) -> dict:
    key = str(cfg.get("esv_api_key", "")).strip()
    if not key:
        return {"error": "No ESV API key set (service setting 'esv_api_key'). Get a free key at api.esv.org."}
    name = _BOOKS[book][0]
    q = urllib.parse.urlencode({
        "q": f"{name} {chapter}",
        "include-headings": "false", "include-footnotes": "false", "include-passage-references": "false",
        "include-short-copyright": "false", "include-verse-numbers": "true",
        "include-first-verse-numbers": "true", "indent-poetry": "false",
    })
    try:
        raw = _http_get(f"https://api.esv.org/v3/passage/text/?{q}", {"Authorization": f"Token {key}"})
        data = json.loads(raw)
    except Exception as exc:
        return {"error": f"ESV fetch failed: {exc}"}
    passages = data.get("passages") or []
    if not passages:
        return {"error": f"ESV returned no passage for {name} {chapter}."}
    verses = _split_numbered(passages[0])
    if not verses:
        return {"error": f"Couldn't parse ESV verses for {name} {chapter}."}
    return {"ok": True, "verses": verses,
            "copyright": "Scripture quotations marked “ESV” are from the ESV® Bible "
                         "(The Holy Bible, English Standard Version®), © 2001 by Crossway. "
                         "Used by permission. All rights reserved."}


def _fetch_apibible(version: str, book: str, chapter: int, cfg: dict) -> dict:
    key = str(cfg.get("apibible_api_key", "")).strip()
    if not key:
        return {"error": "No API.Bible key set (service setting 'apibible_api_key'). Get a free key at scripture.api.bible."}
    bible_id = str(cfg.get(f"apibible_{version}_id", "")).strip()
    if not bible_id:
        return {"error": f"No bible-id for {version.upper()} (service setting 'apibible_{version}_id'). "
                         "Copy the bible id your key can access from scripture.api.bible."}
    usfm = _BOOKS[book][1]
    chap_id = f"{usfm}.{chapter}"
    q = urllib.parse.urlencode({
        "content-type": "text", "include-verse-numbers": "true", "include-notes": "false",
        "include-titles": "false", "include-chapter-numbers": "false", "include-verse-spans": "false",
    })
    try:
        raw = _http_get(
            f"https://api.scripture.api.bible/v1/bibles/{bible_id}/chapters/{chap_id}?{q}",
            {"api-key": key})
        data = json.loads(raw).get("data") or {}
    except Exception as exc:
        return {"error": f"{version.upper()} fetch failed: {exc}"}
    verses = _split_numbered(data.get("content", ""))
    if not verses:
        return {"error": f"Couldn't parse {version.upper()} verses for {book} {chapter}."}
    return {"ok": True, "verses": verses,
            "copyright": (data.get("copyright") or "").strip()
            or f"{version.upper()} — used by permission of the copyright holder."}


def fetch_chapter(version: str, book: str, chapter: int, cfg: dict) -> dict:
    """Fetch one chapter of a licensed version. Returns {ok, verses:{n:text}, copyright} or {error}."""
    version = (version or "").lower().strip()
    book = (book or "").lower().strip()
    if version not in SUPPORTED:
        return {"error": f"Unsupported version '{version}'. Supported: {', '.join(SUPPORTED)}."}
    if book not in _BOOKS:
        return {"error": f"Unknown book slug '{book}' (e.g. john, 1-corinthians, psalms)."}
    if not chapter or chapter < 1:
        return {"error": "Chapter must be a positive number."}
    if version == "esv":
        return _fetch_esv(book, chapter, cfg)
    return _fetch_apibible(version, book, chapter, cfg)
