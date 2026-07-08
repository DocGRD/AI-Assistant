"""
Background maintenance scheduler — Milestones 16.7 + 17.

One tiny daemon thread (no OS cron / Task Scheduler to install — cross-platform, lives
and dies with the always-on service) that ticks every ~30 min and runs nightly/weekly
maintenance the user asked to be automatic:

  - **Weekly** provider discovery → writes `Provider-Registry-proposed.md` (M16.7).
  - **Nightly** memory consolidation ("dreaming") → writes a consolidation proposal
    under `AI/Memory/proposed/` (M17).

Both are **propose/commit** — they never auto-apply. Discovery state is persisted to
`data/discovery_state.json`; consolidation idempotency comes from its own watermark, with
an in-memory same-day guard so the nightly job fires once per night. Each job is
config-gated. The one-shot CLIs (`vault:discover-providers`, `--consolidate`) remain for
manual/cron use.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

from assistant_core.paths import DATA_DIR

logger = logging.getLogger("assistant")

_STATE_FILE   = DATA_DIR / "discovery_state.json"
_TICK_SECONDS = 1800   # check twice an hour


def _read_last_run(path: Path = _STATE_FILE) -> datetime | None:
    try:
        return datetime.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["last_run"])
    except Exception:
        return None


def _write_last_run(when: datetime, path: Path = _STATE_FILE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last_run": when.isoformat()}), encoding="utf-8")
    except Exception as exc:
        logger.debug(f"[Scheduler] Could not persist discovery state: {exc}")


def discovery_due(now: datetime, last_run: datetime | None,
                  interval_days: int, hour: int) -> bool:
    """Pure decision (unit-tested): fire only in the configured night hour, and only
    once the interval has elapsed. First run fires as soon as that hour arrives."""
    if now.hour != hour:
        return False
    if last_run is None:
        return True
    return (now - last_run) >= timedelta(days=interval_days)


def consolidate_due(now: datetime, hour: int, last_date: str | None) -> bool:
    """Pure decision (unit-tested): fire once per night — in the configured hour and
    not already fired this calendar day."""
    if now.hour != hour:
        return False
    return last_date != now.strftime("%Y-%m-%d")


def daily_due(now: datetime, hour: int, last_date: str | None) -> bool:
    """M34 — fire once per day in the configured hour (briefing, auto-organize)."""
    if now.hour != hour:
        return False
    return last_date != now.strftime("%Y-%m-%d")


class MaintenanceScheduler:
    """Daemon thread: weekly provider discovery + nightly memory consolidation."""

    def __init__(self, vault_path, config: dict, router=None, rag=None):
        self._vault_path = vault_path
        self._config     = config
        self._router     = router
        self._rag        = rag          # embedder resolved lazily at consolidation time
        self._stop       = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_consolidate: str | None = None
        self._last_briefing:    str | None = None   # M34
        self._last_organize:    str | None = None   # M34

    def _enabled(self) -> bool:
        return bool(self._config.get("auto_discovery_enabled", True)
                    or self._config.get("auto_consolidate_enabled", True)
                    or self._config.get("auto_briefing_enabled", True)
                    or self._config.get("auto_organize_enabled", False))

    def start(self) -> None:
        if not self._enabled():
            logger.info("[Scheduler] All background jobs disabled.")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(
            f"[Scheduler] Maintenance started — discovery ~{int(self._config.get('auto_discovery_hour', 3)):02d}:00 "
            f"every {int(self._config.get('auto_discovery_interval_days', 7))}d; "
            f"consolidation ~{int(self._config.get('auto_consolidate_hour', 4)):02d}:00 nightly.")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        d_interval = int(self._config.get("auto_discovery_interval_days", 7))
        d_hour     = int(self._config.get("auto_discovery_hour", 3))
        c_hour     = int(self._config.get("auto_consolidate_hour", 4))
        while not self._stop.is_set():
            now = datetime.now()
            try:
                if self._config.get("auto_discovery_enabled", True) and \
                        discovery_due(now, _read_last_run(), d_interval, d_hour):
                    self._fire_discovery()
                if self._config.get("auto_consolidate_enabled", True) and \
                        consolidate_due(now, c_hour, self._last_consolidate):
                    self._fire_consolidation(now)
                # M34 — proactive agents (read-only briefing; propose-only auto-organize)
                if self._config.get("auto_briefing_enabled", True) and \
                        daily_due(now, int(self._config.get("briefing_hour", 6)), self._last_briefing):
                    self._fire_briefing(now)
                if self._config.get("auto_organize_enabled", False) and \
                        daily_due(now, int(self._config.get("organize_hour", 5)), self._last_organize):
                    self._fire_organize(now)
            except Exception as exc:
                logger.warning(f"[Scheduler] tick failed: {exc}")
            self._stop.wait(_TICK_SECONDS)

    def _fire_briefing(self, now: datetime) -> None:
        self._last_briefing = now.strftime("%Y-%m-%d")   # guard first — once per day
        try:
            from assistant_core.proactive.briefing import write_briefing
            rel = write_briefing(self._vault_path, self._config, self._rag, self._router, now=now)
            logger.info(f"[Scheduler] Daily briefing written: {rel}")
        except Exception as exc:
            logger.warning(f"[Scheduler] briefing failed: {exc}")

    def _fire_organize(self, now: datetime) -> None:
        self._last_organize = now.strftime("%Y-%m-%d")
        if self._router is None:
            return
        try:
            from assistant_core.proactive.organize import run_organize
            rep = run_organize(self._vault_path, self._config, self._rag, self._router)
            logger.info(f"[Scheduler] Auto-organize: proposed for {rep.get('notes', 0)} note(s) "
                        f"→ {rep.get('proposal')}")
        except Exception as exc:
            logger.warning(f"[Scheduler] auto-organize failed: {exc}")

    def _fire_discovery(self) -> None:
        from assistant_core.providers.discovery_job import run_discovery_proposal
        logger.info("[Scheduler] Running weekly provider discovery...")
        ok, msg = run_discovery_proposal(self._vault_path, self._config)
        _write_last_run(datetime.now())   # record even on no-op, so we don't retry all night
        logger.info(f"[Scheduler] Discovery {'wrote proposal' if ok else 'skipped'}: {msg}")

    def _fire_consolidation(self, now: datetime) -> None:
        self._last_consolidate = now.strftime("%Y-%m-%d")   # guard first — fire once tonight
        if self._router is None:
            return
        from assistant_core.consolidation import ConsolidationEngine
        embedder = self._rag.embedder if (self._rag and getattr(self._rag, "enabled", False)) else None
        archive_days = int(self._config.get("episode_archive_days", 30))
        logger.info("[Scheduler] Running nightly memory consolidation...")
        report = ConsolidationEngine(self._vault_path, self._router, embedder).run(
            apply=False, archive_days=archive_days)
        logger.info(f"[Scheduler] Consolidation: {len(report['new_facts'])} new fact(s) "
                    f"proposed (days={report['days']}); archived {len(report['archived'])} episode(s).")

        # M18 — incremental knowledge-graph build in the same nightly window (opt-in,
        # highest cost so gated off by default).
        if self._config.get("auto_graph_enabled", False) and self._router is not None:
            try:
                from assistant_core.graph.job import build_graph
                limit = int(self._config.get("graph_build_limit", 50))
                grep = build_graph(self._vault_path, self._router, limit=limit)
                logger.info(f"[Scheduler] Graph: processed {len(grep['processed'])} note(s), "
                            f"+{grep['relations']} relation(s).")
            except Exception as exc:
                logger.warning(f"[Scheduler] graph build failed: {exc}")
