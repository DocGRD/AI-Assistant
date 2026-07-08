"""
Resource governor — Milestone 34.

Background work (proactive agents now; the goal engine later) must never slow the
foreground down or blow through free-tier limits. Before a background job spends a model
call it asks the governor `may_run()`:

  - **Foreground priority** — the server marks activity on every `/chat`; the governor
    defers while a turn is in flight and for a short cooldown after.
  - **Rate budget** — a rolling per-hour cap on background model calls
    (`background_hourly_budget`) so the day's free-tier quota is left for the user.

The decision is a pure function (`should_defer`) for testing; module-level state wraps it
for the running service. Privacy is handled by the callers (a private note routes
`private=True`); the governor is only about *when* to run, not *how*.
"""

import threading
import time

FG_COOLDOWN_S = 45          # stay paused this long after the last foreground activity
_WINDOW_S     = 3600        # rolling budget window (1 hour)

_lock = threading.Lock()
_fg_active_until: float = 0.0
_bg_calls: list[float] = []   # timestamps of recent background model calls


# ---------------------------------------------------------------------------
# Pure decision (unit-tested) — mirrors scheduler.discovery_due / consolidate_due
# ---------------------------------------------------------------------------

def should_defer(now: float, fg_active_until: float, bg_calls: list[float],
                 hourly_budget: int, window: float = _WINDOW_S) -> bool:
    """True if a background job should NOT run now (foreground busy, or budget spent)."""
    if now < fg_active_until:
        return True
    recent = sum(1 for t in bg_calls if now - t < window)
    return recent >= max(0, hourly_budget)


# ---------------------------------------------------------------------------
# Running-service state
# ---------------------------------------------------------------------------

def mark_foreground_activity(cooldown_s: float = FG_COOLDOWN_S, now: float | None = None) -> None:
    """Called by the server on each user turn — background yields for `cooldown_s`."""
    global _fg_active_until
    with _lock:
        _fg_active_until = (now if now is not None else time.time()) + cooldown_s


def foreground_active(now: float | None = None) -> bool:
    now = now if now is not None else time.time()
    with _lock:
        return now < _fg_active_until


def record_background_call(now: float | None = None) -> None:
    """A background model call was just made — count it against the hourly budget."""
    now = now if now is not None else time.time()
    with _lock:
        _bg_calls[:] = [t for t in _bg_calls if now - t < _WINDOW_S]
        _bg_calls.append(now)


def budget_remaining(hourly_budget: int, now: float | None = None) -> int:
    now = now if now is not None else time.time()
    with _lock:
        recent = sum(1 for t in _bg_calls if now - t < _WINDOW_S)
    return max(0, hourly_budget - recent)


def may_run(config: dict | None = None, now: float | None = None) -> bool:
    """True if a background job may spend a model call right now."""
    now = now if now is not None else time.time()
    hourly_budget = int((config or {}).get("background_hourly_budget", 60))
    with _lock:
        return not should_defer(now, _fg_active_until, list(_bg_calls), hourly_budget)


def _reset_for_tests() -> None:
    global _fg_active_until
    with _lock:
        _fg_active_until = 0.0
        _bg_calls.clear()
