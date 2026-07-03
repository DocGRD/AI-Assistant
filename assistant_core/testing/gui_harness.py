"""Desktop-GUI end-to-end automation harness.

The milestone unit tests prove the *backend* works. The plugin GUI — typing in the
sidebar, clicking provider toggles, reading the rendered reply, committing an edit
proposal, opening the Graph viewer — is what a human still has to click through by
hand. This harness lets an agent drive that GUI with **desktop automation +
screenshots + reasoning**, while cross-checking every on-screen result against a
backend **ground-truth oracle** so a passing screenshot is never taken on faith.

Design
------
* Each :class:`Scenario` couples a human-readable GUI action (what to click/type in
  Obsidian) with an ``oracle`` — a pure function over the vault that computes exactly
  what the plugin *should* display. The agent compares the screenshot to the oracle.
* Every built-in scenario uses zero-cost ``system`` vault commands (``vault:list`` /
  ``:read`` / ``:query`` / ``:sources`` / ``:passage`` note-gathering / graph reads),
  so a full automated pass spends **no provider quota**.
* :meth:`GuiHarness.probe` mirrors the plugin's ``POST /chat`` request exactly, for an
  optional live cross-check against a running server.

CLI
---
    python -m assistant_core.testing.gui_harness --seed      # write deterministic fixtures
    python -m assistant_core.testing.gui_harness --oracle    # run oracles -> Markdown report
    python -m assistant_core.testing.gui_harness --ensure    # start the server if it is down
    python -m assistant_core.testing.gui_harness --probe "vault:list AI/Help"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

FIXTURE_DIR = "AI/Tests/gui-fixtures"
REPORT_PATH = "AI/Tests/GUI-Automation-Report.md"


# --------------------------------------------------------------------------- config
def _load_settings() -> dict:
    p = Path(__file__).resolve().parents[1] / "config" / "settings.json"
    if not p.exists():
        p = p.with_name("settings.example.json")
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- oracles
@dataclass
class OracleResult:
    ok: bool
    expected: str          # what the plugin screen should show
    detail: str = ""       # supporting ground-truth detail


# Fixtures the scenarios assert against. Deterministic, self-contained.
FIXTURES: dict[str, str] = {
    "gui-fixture-heater.md": (
        "---\ntags: [gui-test]\n---\n"
        "# Rocket Mass Heater\n\n"
        "A rocket mass heater stores thermal mass in a cob bench and burns wood "
        "cleanly at high temperature. The barrel radiates heat quickly.\n"
    ),
    "gui-fixture-passage.md": (
        "---\ntags: [gui-test, sermon]\n---\n"
        "# The Last Hour — 1 John 2:18-20\n\n"
        "Notes on 1 John 2:18-20: the antichrist, the last hour, and the anointing "
        "that abides. Cross-reference 1 John 2:19.\n"
    ),
    "gui-fixture-render.md": (
        "---\ntags: [gui-test]\n---\n"
        "# Markdown Render Check\n\n"
        "This note has **bold text**, a bullet list, and a `code span` so the "
        "sidebar's Markdown rendering can be verified visually.\n\n"
        "- first item\n- second item\n"
    ),
}


def _vault() -> Path:
    return Path(_load_settings()["vault_path"])


def _oracle_list(vault: Path) -> OracleResult:
    d = vault / "AI" / "Help"
    files = sorted(p.name for p in d.glob("*.md")) if d.exists() else []
    return OracleResult(bool(files), f"AI/Help listing shows {len(files)} notes: "
                        + ", ".join(files), detail="; ".join(files))


def _oracle_query(vault: Path) -> OracleResult:
    from assistant_core.query import structured_search
    hits = structured_search(vault, "tag:gui-test")
    paths = [h["path"] for h in hits]
    ok = any(p.endswith("gui-fixture-heater.md") for p in paths)
    return OracleResult(ok, f"query `tag:gui-test` lists {len(paths)} note(s), "
                        f"including the heater fixture", detail="; ".join(paths))


def _oracle_sources(vault: Path) -> OracleResult:
    from assistant_core.provenance import find_sources
    rep = find_sources(vault, "rocket mass heater stores thermal mass and burns wood")
    top = rep["sources"][0]["path"] if rep["sources"] else "(none)"
    ok = rep["sourced"] and bool(rep["sources"])
    return OracleResult(ok, "sources audit reports **sourced** with supporting note(s)",
                        detail=f"sourced={rep['sourced']} top={top}")


def _oracle_unsourced(vault: Path) -> OracleResult:
    from assistant_core.provenance import find_sources
    rep = find_sources(vault, "zqxwvu plorbnac frembulon wixmordy thlunkasp")
    return OracleResult(not rep["sourced"], "sources audit reports **unsourced** "
                        "(no supporting note)", detail=f"sourced={rep['sourced']}")


def _oracle_passage(vault: Path) -> OracleResult:
    from assistant_core.scripture.passage import find_passage_notes
    notes = find_passage_notes(vault, "1 John 2:18-20")
    paths = [n["path"] for n in notes]
    ok = bool(notes)   # notes whose refs overlap 1 John 2:18-20 (fixture in a bare vault; real notes here)
    return OracleResult(ok, f"passage guide cites {len(paths)} note(s) overlapping "
                        "1 John 2:18-20", detail="; ".join(paths[:4]) + (" …" if len(paths) > 4 else ""))


def _oracle_render(vault: Path) -> OracleResult:
    p = vault / FIXTURE_DIR / "gui-fixture-render.md"
    ok = p.exists() and "**bold text**" in p.read_text(encoding="utf-8")
    return OracleResult(ok, "note body renders as HTML: a bold run, a bullet list, and "
                        "a code span (not raw `**` / `-` markup)",
                        detail="fixture present" if ok else "fixture missing")


# --------------------------------------------------------------------------- scenarios
@dataclass
class Scenario:
    id: str
    title: str
    milestone: str
    gui_action: str                       # what the agent types/clicks in the plugin
    visual_check: str                     # what the screenshot must show
    oracle: Callable[[Path], OracleResult]
    cost: str = "system (zero-cost)"


SCENARIOS: list[Scenario] = [
    Scenario("GUI.01", "List a folder", "M16.6",
             "Type `vault:list AI/Help` in the sidebar and send.",
             "A rendered list of the five Help notes appears as an assistant bubble.",
             _oracle_list),
    Scenario("GUI.02", "Structured search", "M26",
             "Type `vault:query tag:gui-test` and send.",
             "The heater/passage/render fixtures are listed as clickable note links.",
             _oracle_query),
    Scenario("GUI.03", "Provenance audit — sourced", "M25",
             "Type `vault:sources rocket mass heater stores thermal mass and burns wood`.",
             "Reply says the claim is sourced and lists the heater fixture first.",
             _oracle_sources),
    Scenario("GUI.04", "Provenance audit — unsourced", "M25",
             "Type `vault:sources zqxwvu plorbnac frembulon wixmordy thlunkasp`.",
             "Reply shows the ⚠ unsourced message.",
             _oracle_unsourced),
    Scenario("GUI.05", "Passage guide", "M24",
             "Type `vault:passage 1 John 2:18-20` and send.",
             "Reply is a cited overview naming the 1 John 2:18-20 fixture note.",
             _oracle_passage),
    Scenario("GUI.06", "Markdown rendering", "plugin",
             "Type `vault:read AI/Tests/gui-fixtures/gui-fixture-render.md`.",
             "The reply renders bold/bullets/code as HTML, not raw Markdown symbols.",
             _oracle_render),
]


# --------------------------------------------------------------------------- harness
@dataclass
class GuiHarness:
    settings: dict = field(default_factory=_load_settings)

    @property
    def vault(self) -> Path:
        return Path(self.settings["vault_path"])

    @property
    def base_url(self) -> str:
        return f"http://{self.settings.get('host', '127.0.0.1')}:{self.settings.get('port', 8765)}"

    # -- fixtures ----------------------------------------------------------------
    def seed_fixtures(self) -> list[str]:
        d = self.vault / FIXTURE_DIR
        d.mkdir(parents=True, exist_ok=True)
        written = []
        for name, body in FIXTURES.items():
            (d / name).write_text(body, encoding="utf-8")
            written.append(f"{FIXTURE_DIR}/{name}")
        return written

    # -- backend oracle ----------------------------------------------------------
    def run_oracles(self) -> list[tuple[Scenario, OracleResult]]:
        return [(s, s.oracle(self.vault)) for s in SCENARIOS]

    # -- live server -------------------------------------------------------------
    @staticmethod
    def _opener():
        """No-proxy opener — Windows urllib otherwise routes localhost via the
        registry's WinINET proxy and gets connection-refused even when the server
        is up (curl bypasses this)."""
        import urllib.request
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def server_up(self, timeout: float = 3.0) -> bool:
        # No `/health` route exists; `/status` is an always-200 GET.
        try:
            with self._opener().open(self.base_url + "/status", timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    def ensure_server(self, wait: float = 60.0) -> bool:
        if self.server_up():
            return True
        subprocess.Popen([sys.executable, "-m", "assistant_core", "--headless"],
                         cwd=str(Path(__file__).resolve().parents[2]),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + wait
        while time.time() < deadline:
            if self.server_up():
                return True
            time.sleep(1.5)
        return False

    def probe(self, message: str, **fields) -> dict:
        """Mirror the plugin's POST /chat. Returns the parsed HandoffResponse."""
        import urllib.request
        payload = {"message": message}
        payload.update(fields)
        req = urllib.request.Request(
            self.base_url + "/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.settings['api_token']}"}
                        if self.settings.get("api_token") else {})},
            method="POST")
        with self._opener().open(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8"))

    # -- report ------------------------------------------------------------------
    def render_report(self, results: list[tuple[Scenario, OracleResult]]) -> str:
        lines = [
            "# GUI Automation Report",
            "",
            "Generated by `assistant_core.testing.gui_harness`. The **Oracle** column is",
            "the objective backend ground truth (auto-computed, zero-cost). Fill the",
            "**Screen** column from the Obsidian screenshot while running the",
            "[[GUI-Automation-Runbook]] with desktop automation.",
            "",
            "| ID | Milestone | GUI action | Oracle (auto) | Expected on screen | Screen ✅/❌ |",
            "|----|-----------|------------|---------------|--------------------|-------------|",
        ]
        for s, r in results:
            mark = "✅" if r.ok else "❌"
            action = s.gui_action.replace("|", "\\|")
            expect = s.visual_check.replace("|", "\\|")
            lines.append(f"| {s.id} | {s.milestone} | {action} | {mark} {r.detail} | {expect} | |")
        n_ok = sum(1 for _, r in results if r.ok)
        lines += ["", f"**Oracle summary:** {n_ok}/{len(results)} ground-truth checks pass.",
                  "A GUI test passes only when the screenshot matches *and* the oracle is ✅."]
        return "\n".join(lines) + "\n"

    def write_report(self, results=None) -> Path:
        results = results or self.run_oracles()
        out = self.vault / REPORT_PATH
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.render_report(results), encoding="utf-8")
        return out


# --------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GUI E2E automation harness")
    ap.add_argument("--seed", action="store_true", help="write deterministic fixtures to the vault")
    ap.add_argument("--oracle", action="store_true", help="run backend oracles and write the report")
    ap.add_argument("--ensure", action="store_true", help="start the assistant server if it is down")
    ap.add_argument("--probe", metavar="MSG", help="send one message to the live server (mirrors the plugin)")
    args = ap.parse_args(argv)

    h = GuiHarness()
    did = False
    if args.seed:
        did = True
        for f in h.seed_fixtures():
            print(f"seeded {f}")
    if args.ensure:
        did = True
        print("server up" if h.ensure_server() else "server FAILED to start")
    if args.oracle:
        did = True
        results = h.run_oracles()
        for s, r in results:
            print(f"{'PASS' if r.ok else 'FAIL'}  {s.id}  {s.title}: {r.detail}")
        print(f"report -> {h.write_report(results)}")
    if args.probe:
        did = True
        if not h.server_up():
            print(f"server not reachable at {h.base_url} — run --ensure first")
            return 2
        resp = h.probe(args.probe)
        print(f"[{resp.get('provider_used')}] {resp.get('reply', '')[:800]}")
    if not did:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
