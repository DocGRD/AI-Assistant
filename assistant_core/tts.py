"""
Server-side text-to-speech — v1.9.3.

Read-aloud on desktop uses the browser's Web Speech API, but Obsidian's **Android WebView**
doesn't expose it — so on mobile the service synthesizes the audio and the plugin plays it in
an <audio> element (which Android WebView does support). Zero-cost, local, private: the audio
never leaves the machine/LAN.

Engines (auto-selected, best first):
  1. **Piper** — a small offline neural TTS (natural voice). Uses the `piper` CLI + a voice
     `.onnx` model; configure `tts_piper_model` with the model path.
  2. **espeak / espeak-ng** — always-available fallback (robotic, but no model needed).

Audio is synthesized at normal speed; the plugin changes speed with the <audio> playbackRate,
so we never re-synthesize just to change pace. Never raises — returns None when TTS is off or
no engine is available.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger("assistant")

MAX_CHARS = 8000


def _find_exe(name: str) -> str | None:
    """Resolve a CLI by PATH, or next to the running Python (venv bin) — the service process
    may not have the venv's bin dir on PATH even though `piper` was pip-installed there."""
    found = shutil.which(name)
    if found:
        return found
    for cand in (Path(sys.executable).parent / name, Path(sys.executable).parent / f"{name}.exe"):
        if cand.is_file():
            return str(cand)
    return None


def _resolve_model(cfg: dict) -> str:
    """The Piper voice model path: the `tts_piper_model` config if valid, else auto-discovered —
    the first `*.onnx` under `<repo>/models/piper/`. Auto-discovery means dropping a voice model in
    that folder is enough (no config plumbing, and it survives `git reset`)."""
    m = cfg.get("tts_piper_model", "")
    if m and Path(m).is_file():
        return m
    try:
        from assistant_core.paths import REPO_ROOT
        for f in sorted((REPO_ROOT / "models" / "piper").glob("*.onnx")):
            return str(f)
    except Exception:
        pass
    return ""


def available_engine(config: dict | None = None) -> str | None:
    """Which engine would be used ('piper' / 'espeak'), or None if TTS can't run here."""
    cfg = config or {}
    engine = (cfg.get("tts_engine") or "auto").lower()
    if engine == "off":
        return None
    model = _resolve_model(cfg)
    if engine in ("auto", "piper") and _find_exe("piper") and model and Path(model).is_file():
        return "piper"
    if engine in ("auto", "espeak") and (_find_exe("espeak-ng") or _find_exe("espeak")):
        return "espeak"
    return None


def _run(cmd: list[str], stdin: bytes | None, out_path: str) -> bytes | None:
    try:
        subprocess.run(cmd, input=stdin, check=True, timeout=120, capture_output=True)
        data = Path(out_path).read_bytes()
        return data or None
    except Exception as exc:
        logger.warning(f"[TTS] {cmd[0]} failed: {exc}")
        return None
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


def _piper(text: str, model: str) -> bytes | None:
    exe = _find_exe("piper")
    if not exe or not model or not Path(model).is_file():
        return None
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        out = tf.name
    return _run([exe, "-m", model, "-f", out], stdin=text.encode("utf-8"), out_path=out)


def _espeak(text: str, wpm: int) -> bytes | None:
    exe = _find_exe("espeak-ng") or _find_exe("espeak")
    if not exe:
        return None
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        out = tf.name
    return _run([exe, "-s", str(wpm), "-w", out, text], stdin=None, out_path=out)


def synthesize(text: str, config: dict | None = None) -> tuple[bytes, str] | None:
    """Text → (WAV bytes, engine name), or None if TTS is unavailable/off. Normal speed
    (the client handles pace via playbackRate)."""
    cfg = config or {}
    engine = (cfg.get("tts_engine") or "auto").lower()
    if engine == "off":
        return None
    text = (text or "").strip()
    if not text:
        return None
    text = text[:int(cfg.get("tts_max_chars", MAX_CHARS))]

    if engine in ("auto", "piper"):
        wav = _piper(text, _resolve_model(cfg))
        if wav:
            return wav, "piper"
        if engine == "piper":
            return None

    wav = _espeak(text, int(cfg.get("tts_espeak_wpm", 175)))
    if wav:
        return wav, "espeak"
    return None
