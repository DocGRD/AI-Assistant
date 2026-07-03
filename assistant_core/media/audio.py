"""
Audio transcription — Milestone 27.

Turn sermon/lecture audio into searchable text. Transcription runs **locally** via
`faster-whisper` (free, offline — audio never leaves the machine); it's an optional
dependency, so a missing install returns a clear message instead of raising. The result
is written as an additive `AI/Derived/<name>.transcript.md` sidecar the M11 index picks
up. The transcriber is injectable so the flow is testable without the model.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("assistant")

DERIVED_DIR = "AI/Derived"
AUDIO_EXT = (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".webm", ".mp4")


def _whisper_transcribe(path: Path, model_size: str = "base") -> str:
    from faster_whisper import WhisperModel   # optional dep
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(path))
    return " ".join(seg.text.strip() for seg in segments).strip()


def transcribe_audio(path, config: dict | None = None, transcribe_fn=None) -> tuple[str, str | None]:
    """Transcribe one audio file → (text, error). `transcribe_fn(path)` overrides the
    local model (tests). Never raises."""
    path = Path(path)
    if not path.is_file():
        return "", f"audio not found: {path}"
    fn = transcribe_fn or (lambda p: _whisper_transcribe(p, (config or {}).get("whisper_model", "base")))
    try:
        text = (fn(path) or "").strip()
    except Exception as exc:
        logger.warning(f"[Audio] transcription failed for {path.name}: {exc}")
        return "", ("could not transcribe (install faster-whisper: pip install faster-whisper, "
                    f"or check the file). Detail: {exc}")
    if not text:
        return "", "transcription produced no text"
    return text, None


def transcribe_to_sidecar(vault, audio_rel: str, config: dict | None = None,
                          transcribe_fn=None, rag=None) -> dict:
    """Transcribe an audio file in the vault → AI/Derived/<name>.transcript.md, indexed."""
    report = {"audio": audio_rel, "sidecar": None, "chars": 0, "error": None}
    src = Path(vault) / audio_rel
    if not src.is_file():
        from assistant_core.media.ocr import resolve_image_path  # reuses vault-file resolution
        found = resolve_image_path(vault, audio_rel)
        if found:
            src = found
    if not src.is_file():
        report["error"] = f"audio not found: {audio_rel}"; return report

    text, err = transcribe_audio(src, config, transcribe_fn)
    if err:
        report["error"] = err; return report

    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    stem = src.stem
    rel = f"{DERIVED_DIR}/{stem}.transcript.md"
    out = Path(vault) / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"---\nai-derived: transcript\nsource: {audio_rel}\ngenerated: {date}\n---\n\n"
        f"# Transcript — {stem}\n\n"
        f"> Local transcription of `{audio_rel}` ({date}). The audio never left the machine.\n\n"
        f"{text}\n", encoding="utf-8")
    report.update(sidecar=rel, chars=len(text))
    logger.info(f"[Audio] transcribed {audio_rel} → {rel} ({len(text)} chars)")

    if rag is not None and getattr(rag, "enabled", False):
        try:
            rag.maybe_index_note(rel, out.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug(f"[Audio] index of {rel} failed: {exc}")
    return report
