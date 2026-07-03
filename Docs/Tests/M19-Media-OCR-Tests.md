# M19 — Image, Handwriting & Excalidraw Tests

**Date tested:** _______________
**Tester:** _______________
**Branch:** _______________

Excalidraw drawing text is indexed; `vault:ocr <note>` extracts image/handwriting text (free multimodal
model, local tesseract fallback) into an additive `AI/Derived/` sidecar. Privacy-forced. See
[[Project-State]] M19 and [[User-Guide]].

---

## Section 1 — Automated

### T19.01 — Excalidraw + OCR unit tests
**Steps:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest tests.test_excalidraw tests.test_ocr -v`
**Expected:** Pass — Excalidraw `## Text Elements` extraction (block-ids stripped, JSON fallback); OCR
embed detection, vision→tesseract fallback, privacy threading + no-train provider selection, additive
sidecar.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

---

## Section 2 — Live (box)

### T19.02 — Excalidraw drawing becomes searchable
**Steps:** Reindex a vault containing a `*.excalidraw.md` sermon/diagram note, then
`vault:ask <a phrase written inside the drawing>`.
**Expected:** Vault QA finds it — the drawing's typed text was indexed (not the scene JSON).

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T19.03 — OCR a note's image
**Steps:** In a note, embed an image with text (`![[scan.png]]`). `vault:ocr <that note>`.
**Expected:** Reports N/M images read; a sidecar `AI/Derived/<note>.ocr.md` is created with the extracted
text and a `[[source]]` backlink; the original note is unchanged.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T19.04 — OCR'd text answers in Vault QA
**Steps:** After T19.03 (index refreshed), `vault:ask <a phrase from the image>`.
**Expected:** The answer cites the `AI/Derived/…ocr.md` sidecar.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T19.05 — Privacy
**Steps:** `vault:ocr` a note marked `private: true`.
**Expected:** Its images route only to a no-train multimodal provider or local tesseract — never a
training provider.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T19.07 — 📎 Analyse an image (paperclip / `vault:analyze`)
**Steps:** In the sidebar, click the **📎** paperclip and pick an image in the vault (or type
`vault:analyze <image path>`).
**Expected:** The reply transcribes the image's text and briefly describes it (free multimodal model, or
local tesseract fallback). A private turn uses only no-train/local. Unreadable images return a clear "no
model could read the image" message.

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________

### T19.06 — Graceful without tesseract / vision
**Steps:** On a machine with no tesseract and no multimodal provider, `vault:ocr` a note with an image.
**Expected:** No crash; the sidecar records "[no text extracted]" for that image and the report shows 0
read. (Excalidraw still works — it needs neither.)

- [ ] ✅ Pass  &nbsp; [ ] ❌ Fail  &nbsp; [ ] ⏭ Skip

**Notes:** _______________
