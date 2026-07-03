# GUI Automation Runbook

**What this is.** The step-by-step procedure for driving the Obsidian **plugin GUI**
with desktop automation (screenshots + clicks + typing) and *reasoning over what's on
screen* — the part of testing a human normally does by hand. Every step is
cross-checked against the backend **ground-truth oracle** in
`assistant_core/testing/gui_harness.py`, so a green screenshot is never trusted on its
own.

**Why a harness *and* a runbook.** Screenshot automation is flaky and can't tell a
plausible-looking wrong answer from a right one. The harness computes, offline and at
zero cost, exactly what each command *should* return from the vault. The agent's job is
to make the plugin produce that result on screen and confirm the screenshot matches the
oracle.

---

## 0. Preconditions (once per run)

```bash
# 1. Seed deterministic fixtures + compute the ground-truth oracle + report
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m assistant_core.testing.gui_harness --seed --oracle

# 2. Make sure the service is running (starts it headless if down)
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m assistant_core.testing.gui_harness --ensure
```

The oracle prints `PASS/FAIL` per scenario and writes
`AI/Tests/GUI-Automation-Report.md` in the vault (the **Oracle** column). Open Obsidian,
confirm the vault is loaded and the **AI Assistant** sidebar shows a green **Live**
badge. If the badge is red, the plugin can't reach the server — fix that before driving
the GUI.

## Desktop-automation loop (per scenario)

For each row in the report / each `Scenario` in `gui_harness.SCENARIOS`:

1. **Access.** `request_access` for **Obsidian** (native app → full tier: clickable +
   typeable). Take a `screenshot` to locate the sidebar chat input.
2. **Act.** `left_click` the chat textarea, `type` the scenario's `gui_action` text,
   press `key` **Return** to send.
3. **Observe.** `screenshot` after the reply renders. Read the assistant bubble with
   your own vision — this is the "image recognition + brain" step.
4. **Cross-check.** Compare what's on screen to the scenario's `visual_check` **and** to
   the oracle's expected value in the report. They must agree.
5. **Record.** Put ✅/❌ in the **Screen** column of `GUI-Automation-Report.md`. A
   scenario passes only when the screenshot matches *and* the oracle is ✅.

> Tiered-app note: Obsidian is a third-party native app (full tier). If it ever comes up
> restricted, `open_application` still brings it forward; typing/clicking need full tier.

## Scenarios (all zero-cost `system` commands — no provider quota spent)

| ID | Type in the sidebar | The screenshot must show |
|----|---------------------|--------------------------|
| GUI.01 | `vault:list AI/Help` | The five Help notes, rendered as a list |
| GUI.02 | `vault:query tag:gui-test` | The three `gui-test` fixtures as clickable links |
| GUI.03 | `vault:sources rocket mass heater stores thermal mass and burns wood` | "sourced" + supporting note(s) |
| GUI.04 | `vault:sources zqxwvu plorbnac frembulon wixmordy thlunkasp` | The ⚠ unsourced message |
| GUI.05 | `vault:passage 1 John 2:18-20` | A cited overview naming overlapping 1 John notes |
| GUI.06 | `vault:read AI/Tests/gui-fixtures/gui-fixture-render.md` | **bold** / bullets / `code` rendered as HTML, not raw `**`/`-` |

## Manual-only GUI affordances (visual verdict only — no text oracle)

These have no deterministic backend value; verify them by eye and record in the report's
Notes:

- **Provider toggle** — click *Groq* / *Auto* / *Web UI*; the active chip highlights and
  the next reply's provider label matches.
- **🔒 Private toggle** — enable it; a private turn's reply must come from a no-train
  provider (or show the web-handoff box), never a training provider.
- **📎 Paperclip** — click it; the attach picker opens; picking a doc runs `vault:ingest`,
  picking an image runs `vault:analyze`.
- **⚙ Gear** — opens the plugin's settings tab.
- **Graph viewer** — open it; a radial subgraph popup renders and the entity browser
  lists entities (cross-check `GET /graph/entities`).
- **Edit propose/commit** — select text in a note, ask for an edit; the proposal dialog
  offers **Replace/Reject**; **Replace** applies cleanly (incl. a whole-note edit).

## Interpreting a mismatch

- **Oracle ✅ but screen ❌** → a *plugin* bug (rendering, request wiring, display). File
  it in [[Bug-Log]] with the screenshot.
- **Oracle ❌** → a *backend/fixture* problem; the GUI can't be expected to show a correct
  result. Fix the backend (or the fixture) first, re-run `--oracle`, then re-drive.

---

*Re-run `--seed --oracle` whenever fixtures or the vault change; the report's Oracle
column always reflects the current vault.*
