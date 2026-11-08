# PR draft: Better TTS + chat-driven read-aloud

**Status:** Proposal  
**Related:** v1.7 read-aloud (`reader.ts`), v1.9.3 server TTS notes in Project-State  
**Goal:** Replace weak browser TTS quality, add Modern Greek support, and let the user ask Loremaster in chat to read a note or section aloud.

---

## Problem

1. **Quality** — Desktop Web Speech spells English words, has flat inflection, and handles Greek poorly. The Android Piper path is better but incomplete and not preferred on desktop.
2. **Chat gap** — The agent has no way to *request* read-aloud. Users say “read this note” and the model correctly replies that *it* has no audio, even though the plugin does.
3. **Greek** — User prefers Modern Greek pronunciation. Current path feeds raw Greek to an English-centric engine.

---

## Design principles

- Stay **zero-cost / local-first / private** (audio never leaves the machine or LAN).
- Prefer **server Piper** as the primary engine (desktop + mobile); Web Speech only as a last-resort fallback.
- Chat integration follows existing patterns (`command:run`, edit proposals): agent emits a directive → plugin intercepts → user sees controls (no silent autonomous audio).
- Update the system prompt so the agent knows the *system* can speak even if the LLM itself cannot.

---

## Behaviour changes

### 1. Server TTS becomes primary

- Strengthen / restore `assistant_core/tts.py` + `POST /tts`.
- Add multi-voice support with automatic language routing:
  - **English:** high-quality Piper medium/high voices (e.g. `en_US-lessac-medium`, `en_US-amy-medium`, `en_US-ryan-high`).
  - **Modern Greek:** prefer `el_GR-joy-medium` (human-trained, much better quality). **Licence: CC BY-NC 4.0** — document clearly; for commercial redistribution, fall back to MIT-licensed `el_GR-rapunzelina-medium`.
- Use simple language detection (Unicode Greek runs → Greek voice; otherwise English).
- Improve preprocessing: strip frontmatter/Markdown more cleanly, expand common abbreviations, and improve sentence boundaries for Greek.
- Proposed request body:

```json
{
  "text": "...",
  "voice": "auto",
  "speed": 1.0,
  "lang": "auto"
}
```

The `voice` field may also be set to a specific voice, such as `en_US-lessac-medium` or `el_GR-joy-medium`. The `lang` field may be `auto`, `en`, or `el`.

- Response: `audio/wav` (or error JSON).

### 2. Plugin reader updates (`obsidian-plugin/reader.ts`)

- Prefer server `/tts` even on desktop when the service is reachable.
- Fall back to Web Speech only if the server is unavailable.
- Support language-aware playback (split mixed English/Greek segments when useful).
- Keep the existing floating bar (play/pause, prev/next sentence where possible, speed, stop).
- Add settings for preferred English voice, preferred Greek voice, and a “prefer server TTS” toggle.

### 3. Chat → Speak integration

Add a new agent-visible directive (plugin intercepts, same family as edit proposals / `command:run`):

```text
[[SPEAK: path/to/note.md]]
[[SPEAK: path/to/note.md | section: "Greek formatting"]]
[[SPEAK: path/to/note.md | from: "The Greek word"]]
[[SPEAK: selection]]
```

Optional chat form:

```text
vault:speak <path> [--section "heading"] [--from "snippet"]
```

When the plugin sees it:

- Resolve the note, section, or selection.
- Call the improved reader (server Piper preferred).
- Show the floating control bar + follow-along highlight when in the editor.

**Required system-prompt addition:**

> The Loremaster system (plugin + service) can read notes aloud via offline TTS.  
> When the user asks you to “read X aloud” or “read the section about Y”, emit `[[SPEAK: …]]`.  
> You yourself do not produce audio; the plugin does. Prefer this over denying the capability.

Also update `AI/Help/Commands.md` and Features so Vault QA / the agent can discover the feature.

### 4. Greek handling

- Detect Greek script runs (or honour an explicit `lang=el` / heading).
- Route those segments to the Modern Greek Piper voice.
- Keep surrounding English on the English voice.
- Document that scholarly/Koine reconstruction is not the goal; Modern Greek is.

---

## Files likely touched

| File | Change |
|---|---|
| `assistant_core/tts.py` | Create/restore multi-voice Piper + preprocessing |
| `assistant_core/server/core.py` | `/tts` route improvements |
| `obsidian-plugin/reader.ts` | Prefer server TTS; language split; settings |
| `obsidian-plugin/main.ts` / `ChatView.ts` | Intercept `[[SPEAK:…]]` / `vault:speak` |
| System prompt + seed help | Agent knows it can request speak |
| `Docs/Help/Commands.md`, Features, Whats-New | User docs |
| Tests | Unit tests for preprocessing + language detection; integration test for `/tts` |

---

## Implementation order

1. Server TTS multi-voice + Greek + better preprocessing.
2. Plugin prefers server TTS + settings.
3. `[[SPEAK]]` intercept + system-prompt update.
4. Help docs + tests + licence notes for JOY voice.

---

## Out of scope (follow-ups)

- Kokoro-82M as an optional higher-quality English engine (Apache-2.0, excellent quality; no native Greek).
- Streaming TTS / SSML-like prosody controls.
- Automatic insertion of phonetic respellings from commentary notes.
- True modern Greek reconstructed pronunciation models.

---

## Acceptance criteria

- “Read note aloud” on a mixed English + Modern Greek note produces intelligible English and Modern Greek (not letter-by-letter).
- User can say in chat “read the Greek formatting section of this note” and the plugin starts reading after the agent emits `[[SPEAK:…]]`.
- Agent no longer claims the system has no read-aloud capability once the prompt is updated.
- Desktop and Android both use the same quality path when the service is up.
- JOY voice licence is documented; MIT fallback exists.
