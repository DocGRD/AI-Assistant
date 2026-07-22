"""Guards the shared canonical book table (assistant_core/bible/books.py) and its consumers.

The 66-book number/slug/title spine used to be copy-pasted across several generators (and the
runtime verse index). It now lives once in `books.py`; these tests keep that single source honest
and catch any drift between it and the generators' source-specific abbreviation columns.
"""
import pathlib
import sys
import unittest

from assistant_core.bible import books

_TOOLS = pathlib.Path(__file__).resolve().parents[1] / "assistant_core" / "bible" / "tools"


class BooksCanonicalTests(unittest.TestCase):
    def test_shape_and_invariants(self):
        self.assertEqual(len(books.BOOKS), 66)
        self.assertEqual([n for n, _, _ in books.BOOKS], list(range(1, 67)))   # numbered 1..66 in order
        self.assertEqual(len(set(books.SLUGS)), 66)                            # slugs unique
        for _n, s, t in books.BOOKS:
            self.assertEqual(s, t.lower().replace(" ", "-"), t)                # the slug<->title invariant

    def test_derived_maps_agree(self):
        self.assertEqual(books.NUM_BY_SLUG["john"], 43)
        self.assertEqual(books.SLUG_BY_NUM[43], "john")
        self.assertEqual(books.TITLE_BY_SLUG["1-corinthians"], "1 Corinthians")
        self.assertEqual(books.NT_SLUGS, [s for n, s, _ in books.BOOKS if n >= 40])
        self.assertEqual(len(books.NT_SLUGS), 27)                              # Matthew..Revelation

    def test_helpers(self):
        self.assertEqual(books.pad2(40), "40")
        self.assertEqual(books.pad3(3), "003")
        self.assertEqual(books.book_label("song-of-solomon"), "Song of Solomon")  # not "Song Of Solomon"
        self.assertEqual(books.book_label("matthew"), "Matthew")
        self.assertEqual(books.book_label("unknown-book"), "Unknown Book")     # graceful fallback

    def test_runtime_verse_index_uses_canonical(self):
        import assistant_core.bible.verse_index as vi
        self.assertEqual(vi._BOOKS, {s: t for _, s, t in books.BOOKS})

    def test_generators_align_with_canonical(self):
        """Each generator's source-specific abbreviation list must stay in lock-step with the
        canonical number/slug/title spine — this is what makes the dedup safe to re-run."""
        sys.path.append(str(_TOOLS))
        import gen_strongs
        import gen_bible_notes
        import gen_sblgnt
        # gen_strongs.BOOKS = (kjv_abbr, number, slug); numbers+slugs come from the canonical table.
        self.assertEqual([(n, s) for _, n, s in gen_strongs.BOOKS],
                         [(n, s) for n, s, _ in books.BOOKS])
        self.assertEqual(len(gen_strongs.KJV_ABBRS), 66)
        self.assertEqual(gen_strongs.NUM, books.NUM_BY_SLUG)
        # gen_bible_notes.BOOKS = (usfm_code, number, title); numbers+titles from the canonical table.
        self.assertEqual([(n, t) for _, n, t in gen_bible_notes.BOOKS],
                         [(n, t) for n, _, t in books.BOOKS])
        self.assertEqual(len(gen_bible_notes.USFM_ABBRS), 66)
        # gen_sblgnt reuses the NT slice directly.
        self.assertEqual(gen_sblgnt.NT_SLUGS, books.NT_SLUGS)


if __name__ == "__main__":
    unittest.main()
