# GUI Test Run — 2026-07-08 (Round A core + §14 regression)

**Env:** GRDVault + local headless server (dev `8efb5c1`), plugin host `127.0.0.1`, Loremaster plugin.
**Baseline:** 368 automated tests green before the run.

## Results

| Row | Test | Result | Notes |
|---|---|---|---|
|1.1|Plugin identity|✅|Sidebar/ribbon/palette all say **Loremaster**|
|1.3|Connection|✅|"Connected — GROQ", Live|
|10.*|Proactive panel renders|✅|Panel shows with **"Open today's briefing"**|
|3.1|`4 + 6 =`|✅|`4 + 6 = 10` via **SYSTEM** (deterministic); open note NOT dumped|
|3.2|Argue math ("no, = 12")|✅✅|*"Actually, 4 + 6 equals 10."* — **did not flip** (the key regression)|
|2.11|`test` with note open|✅|*"What would you like to work on or explore?"* — brief, **no note dump**|
|7.8|Typo `vault:serch homestead`|✅|Graceful — agent understood intent, searched, reported "no notes containing homestead" + options|
|2.2|Empty send (Enter, blank)|✅|No phantom message, no error|
|5.8|Write note w/ real + fake link|✅|`[[format-test]]` kept, `[[Totally Made Up Note]]` stripped + footnote; footer **"Created by Loremaster"**|
|7.1|"Look on the web for…"|✅|**Autonomous web research** (Gutenberg ~1440, cited note saved) — **not** the paste-into-web-AI handoff|

## Findings
- **All §14 regression items confirmed fixed in the GUI** (math, argue-math, test-framing, fake-links,
  webresearch, Loremaster rename/footer, proactive panel). No ❌.
- ⚠️ **Minor (cosmetic):** when asked to create a note with an exact body, the model sometimes appends a
  chatty trailer into the note (e.g. `(Note created as requested.)`). Not a correctness bug; consider
  tightening the create-note prompt or stripping trailing meta-commentary. *(polish, not a blocker)*

## Not yet exercised this run (for a fuller Round A/B pass)
Editing drift & large-selection chunking in the UI (§5.4/5.5), restructuring approve card (§6),
paperclip ingest/OCR (§7.5), providers/handoff (§8), goals UI flow (§11), watcher (§12),
adversarial/prompt-injection (§13). Backend for all of these is unit-covered + separately live-verified;
they remain in the campaign for a deeper manual pass before v1.2.

**Verdict:** Round-A core + regression **green**. One cosmetic polish item logged.
