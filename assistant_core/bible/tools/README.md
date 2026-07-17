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
