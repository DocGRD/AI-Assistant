"""Canonical 66-book Bible table — the one source of truth for number <-> slug <-> title.

Book *number* (1-66, canonical order), kebab-case *slug* (matches the reader's note folders,
e.g. `bible/40-matthew/...`) and Title-Case *name*. The invariant `slug == name.lower().replace(" ", "-")`
holds for every row. Source-specific abbreviations (USFM in gen_bible_notes, KJV in gen_strongs) and
Matthew Henry's own naming stay local to those generators — only this number/slug/title spine is shared.
"""

# (number, slug, title)
BOOKS = [
    (1, "genesis", "Genesis"), (2, "exodus", "Exodus"), (3, "leviticus", "Leviticus"), (4, "numbers", "Numbers"),
    (5, "deuteronomy", "Deuteronomy"), (6, "joshua", "Joshua"), (7, "judges", "Judges"), (8, "ruth", "Ruth"),
    (9, "1-samuel", "1 Samuel"), (10, "2-samuel", "2 Samuel"), (11, "1-kings", "1 Kings"), (12, "2-kings", "2 Kings"),
    (13, "1-chronicles", "1 Chronicles"), (14, "2-chronicles", "2 Chronicles"), (15, "ezra", "Ezra"), (16, "nehemiah", "Nehemiah"),
    (17, "esther", "Esther"), (18, "job", "Job"), (19, "psalms", "Psalms"), (20, "proverbs", "Proverbs"),
    (21, "ecclesiastes", "Ecclesiastes"), (22, "song-of-solomon", "Song of Solomon"), (23, "isaiah", "Isaiah"), (24, "jeremiah", "Jeremiah"),
    (25, "lamentations", "Lamentations"), (26, "ezekiel", "Ezekiel"), (27, "daniel", "Daniel"), (28, "hosea", "Hosea"),
    (29, "joel", "Joel"), (30, "amos", "Amos"), (31, "obadiah", "Obadiah"), (32, "jonah", "Jonah"),
    (33, "micah", "Micah"), (34, "nahum", "Nahum"), (35, "habakkuk", "Habakkuk"), (36, "zephaniah", "Zephaniah"),
    (37, "haggai", "Haggai"), (38, "zechariah", "Zechariah"), (39, "malachi", "Malachi"), (40, "matthew", "Matthew"),
    (41, "mark", "Mark"), (42, "luke", "Luke"), (43, "john", "John"), (44, "acts", "Acts"),
    (45, "romans", "Romans"), (46, "1-corinthians", "1 Corinthians"), (47, "2-corinthians", "2 Corinthians"), (48, "galatians", "Galatians"),
    (49, "ephesians", "Ephesians"), (50, "philippians", "Philippians"), (51, "colossians", "Colossians"), (52, "1-thessalonians", "1 Thessalonians"),
    (53, "2-thessalonians", "2 Thessalonians"), (54, "1-timothy", "1 Timothy"), (55, "2-timothy", "2 Timothy"), (56, "titus", "Titus"),
    (57, "philemon", "Philemon"), (58, "hebrews", "Hebrews"), (59, "james", "James"), (60, "1-peter", "1 Peter"),
    (61, "2-peter", "2 Peter"), (62, "1-john", "1 John"), (63, "2-john", "2 John"), (64, "3-john", "3 John"),
    (65, "jude", "Jude"), (66, "revelation", "Revelation"),
]

SLUGS = [s for _, s, _ in BOOKS]
SLUG_BY_NUM = {n: s for n, s, _ in BOOKS}
NUM_BY_SLUG = {s: n for n, s, _ in BOOKS}
TITLE_BY_SLUG = {s: t for _, s, t in BOOKS}
TITLE_BY_NUM = {n: t for n, _, t in BOOKS}
NT_SLUGS = [s for n, s, _ in BOOKS if n >= 40]   # Matthew (40) .. Revelation (66)


def pad2(n) -> str:
    return f"{int(n):02d}"


def pad3(n) -> str:
    return f"{int(n):03d}"


def book_label(slug: str) -> str:
    """Human Title-Case name for a book slug (falls back to a de-slugged guess)."""
    return TITLE_BY_SLUG.get(slug, slug.replace("-", " ").title())
