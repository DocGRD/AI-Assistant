"""Parse eBible.org WEB (public-domain) USFM into structured chapters the LoreMaster Bible renderer
can display: each block = {style, v, t}. style is a paragraph/poetry/heading kind; v is the verse
number (or None for a continuation line / heading); t is clean text (Strong's + footnotes stripped,
words-of-Jesus wrapped in {{wj}}…{{/wj}} for red-letter).

Source: eBible.org `engwebp_usfm.zip` (World English Bible, protestant, public domain).
"""
import re


def clean(t: str) -> str:
    t = re.sub(r'\\w ([^|\\]*)(\|[^\\]*)?\\w\*', r'\1', t)    # \w word|strong=..\w* -> word
    t = re.sub(r'\\f .*?\\f\*', '', t)                        # footnotes out
    t = re.sub(r'\\x .*?\\x\*', '', t)                        # source cross-refs out
    t = re.sub(r'\\\+?wj\*', '{{/wj}}', t)                    # words of Jesus (red-letter) — end
    t = re.sub(r'\\\+?wj ?', '{{wj}}', t)                     # words of Jesus (red-letter) — start
    t = re.sub(r'\\\+?[a-z0-9]+\*', '', t)                    # other closing char markers (\nd* \add*)
    t = re.sub(r'\\\+?[a-z0-9]+ ', '', t)                     # other opening char markers (\nd \add)
    t = re.sub(r'\|[^\\ ]*', '', t)                           # stray attributes
    return re.sub(r'\s+', ' ', t).strip()


# markers that begin a NEW visual paragraph / poetry line (so a verse-view break belongs there)
PARA = {"p", "m", "pi", "pi1", "pi2", "pc", "nb", "q1", "qc"}


def parse_book(usfm: str) -> dict:
    chapters, ch, cur, pending = {}, None, "p", True
    for raw in usfm.split("\n"):
        line = raw.strip()
        m = re.match(r'\\c (\d+)', line)
        if m:
            ch = int(m.group(1)); chapters[ch] = []; cur = "p"; pending = True; continue
        if ch is None:
            continue
        ms = re.match(r'\\(s\d?|d|ms\d?) ?(.*)', line)
        if ms:
            style = 'd' if ms.group(1) == 'd' else 's'
            txt = clean(ms.group(2))
            if txt:
                chapters[ch].append({"style": style, "v": None, "t": txt})
            pending = True
            continue
        mq = re.match(r'\\(q\d|qc|qr|p|m|pi\d?|pc|nb|b|li\d?) ?(.*)', line)
        if mq:
            cur = mq.group(1)
            if cur in PARA:
                pending = True
            rest = mq.group(2)
            if not rest.strip():
                continue
            line = rest
        mv = re.match(r'\\v (\d+)\s*(.*)', line)
        if mv:
            chapters[ch].append({"style": cur, "v": int(mv.group(1)),
                                 "t": clean(mv.group(2)), "pstart": pending})
            pending = False
        elif not re.match(r'\\[a-z]', line) or line.startswith('\\w '):
            ct = clean(line)                         # continuation line (poetry 2nd stich etc.)
            if ct and chapters[ch]:
                chapters[ch].append({"style": cur, "v": None, "t": ct})
    return chapters


if __name__ == "__main__":
    print("wj:", clean(r'\wj I am the way\wj*, he said.'))
    print("word:", clean(r'\w In|strong="H1"\w* the beginning.'))
