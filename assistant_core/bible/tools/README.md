# Bible note generator (WEB)

Build tooling that turns public-domain source data into the LoreMaster study-Bible notes the
plugin renders. Run once per vault; the output notes are what ship in the vault, not these scripts.

## What it produces
`bible/{NN:02d}-{slug}/web/{slug}-{CCC:03d}.md` — one note per chapter, with:
- frontmatter `cssclasses:[bible]` + `bible-version/book/booknum/chapter/parastarts`
- clean `# Book N` heading, section headings (`##`), italic Psalm titles (`*…*`)
- verses `**N** text ^vN` (inline block anchor); poetry as em-space-indented stichs with hard breaks
- **red-letter** words of Christ wrapped in `<span class="lm-wj">…</span>`, balanced per verse
- prev/next nav; per-book MOC (`{slug}.md`) + master index (`bible.md`)
- NO baked cross-references — those load as a shared overlay from `AI/bible-crossrefs/{book}.json`

## Source data (not committed — public-domain, fetch yourself)
Place both in this directory (or point `BIBLE_SRC` at them):
- `engwebp_usfm.zip` — World English Bible (protestant), USFM, from **eBible.org**. Public domain.
- `cross-references.json` — topical cross-references from **OpenBible.info**. Public domain.
  Keyed `{book_slug}.{chapter}.{verse}` → list of target refs.

## Run
```
# defaults: BIBLE_SRC = this dir, BIBLE_VAULT = C:/development/echo-test-vault
BIBLE_VAULT=/path/to/vault python gen_bible_notes.py
```
`usfm_parse.py` is imported by the generator; run it directly for a quick self-test of the
Strong's-strip / red-letter (`\wj…\wj*`) handling.

## Notes stay plain markdown
The plugin renders richness at read time (`obsidian-plugin/bible.ts` + `styles.css` `.bible`);
the notes themselves remain portable, RAG-indexable markdown. The verse-level embedding index is
built separately by `assistant_core/bible/verse_index.py` from these notes.

## Strong's study data — `gen_strongs.py`
Builds the interlinear + concordance + lexicon sidecars under `AI/bible-strongs/` (machine JSON,
excluded from the RAG index). The reading text stays WEB; this powers the reader's interlinear panel
and concordance. **The WEB USFM's own Strong's tags are corrupt** (Elohim H430 is never tagged, etc.),
so the tagging comes from an accurate public-domain source instead:
- **KJV + Strong's** — kaiserlik/kjv per-book JSON (each verse `en` field is KJV text with inline
  `[Hnnnn]` codes). Download the 66 book files into `BIBLE_SRC/kjv/` (some source files concatenate a
  second book and have malformed non-English fields — the parser reads only `en` via regex and locks
  to the file's own book, so both are handled). This is the canonical basis of Strong's Concordance.
- **openscriptures Strong's dictionaries** — `strongs-hebrew.js` + `strongs-greek.js` in `BIBLE_SRC`
  (lemma + transliteration + definition). Public domain.

Run: `BIBLE_VAULT=/path/to/vault python gen_strongs.py`. Output: per-book interlinear `{book}.json`,
`_concordance-H/G.json` (strong → refs), `_words.json` (English → strongs), `_lexicon-H/G.json`.

## Personal commentary
User-authored, not generated: notes with frontmatter `commentary-ref: <book>.<ch>.<v>` (or a range
`…v-v2`, or a whole chapter `<book>.<ch>`). The plugin (`bible-commentary.ts`) indexes them and marks
annotated verses with a ✎ in the reader.
