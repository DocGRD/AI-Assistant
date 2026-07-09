# GUI Test Run — 2026-07-09 (v1.6, Milestones 1–40)

Live regression on **GRDVault** (~2,300 notes) via a local headless server + the v1.6.0 plugin.
Method: curl against `/chat` for every command surface (real vault data) + desktop-automation for the new
v1.6 UI. Baseline: **450 automated tests green**.

## Command surfaces (curl, real vault) — all ✅
| Milestone | Command | Result |
|---|---|---|
| M3 | `vault:read` / `search` / `list` | ✅ read Learned-Facts; search "prayer" → 72 notes; list rendered |
| M11 | `vault:ask` | ✅ answered (agent searched + summarised the prayer notes) |
| M18 | `vault:guide prayer` | ✅ built a cited guide |
| M25 | `vault:sources` | ✅ correctly flagged an unsourced claim |
| M26 | `vault:query tag:prayer` | ✅ structured tag search (distinct from full-text) |
| M28 | `vault:review` | ✅ 6 cards due |
| M30 | fake `[[link]]` on create | ✅ stripped to text + footnote (no dangling link) |
| M32 | `7 * 8 + 2 =` | ✅ `58` (deterministic) |
| M37 | `vault:contradictions` | ✅ 20 flagged |
| M37 | `write_guard` on create | ✅ fabricated stat flagged "⚠ unsourced claims" |
| M38 | `vault:analytics` | ✅ report written (~7s) |
| M38 | `vault:moc prayer` | ✅ propose-only MOC |
| M39 | `vault:actions <note>` | ✅ extracted 2 to-dos |
| M39 | `vault:goal --template digest` | ✅ planned 5-step goal |
| M39 | `vault:goals` | ✅ listed |
| M40 | `vault:clip <web url>` | ✅ clipped + indexed (Obsidian wiki) |
| M40 | `vault:template Meeting :: …` | ✅ filled `{{}}` fields, kept `<% %>` (2/2) |

## New v1.6 UI (desktop automation) — all ✅
- **Badge toolbar**: `📥 Approvals (2)`, `🎯 Goals`, `🗞️ Briefing` — sidebar decluttered (stacked panels gone).
- **Approvals modal**: one window over all kinds — organize (tags, link, **📁 folder move**, **project**),
  proposed goal (steps + Approve/Reject). Applied `project: Q3` per-item → frontmatter set, item removed,
  badge decremented. (Slice B + Slice C folder/project verified.)
- **Inline Compose modal** (Slice A): selected a paragraph → *Rewrite selection (inline)* → previewed a
  concise rewrite → **Accept** replaced it in place. Continue/Compose share the same popup.

## Fixes made during this run
- **`vault:template` separator** was an em-dash (` — `) — awkward to type and broke JSON bodies. Changed to
  ASCII `::` (`vault:template <name> :: <context>`). Re-verified: template filled 2/2 fields.

## Verdict
v1.6 does what we think it does — M1–M40 command surfaces and the new inline-edit + badge-modal UI all
behave end-to-end on a real 2,300-note vault. One UX bug found and fixed. Ready to ship v1.6.0.
