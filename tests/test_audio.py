"""M27 — audio transcription (local Whisper). Stdlib unittest, injected transcriber."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.media.audio import transcribe_audio, transcribe_to_sidecar


class TranscribeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "Sermons").mkdir(parents=True, exist_ok=True)
        (self.vault / "Sermons" / "sermon.mp3").write_bytes(b"ID3fakeaudio")

    def tearDown(self):
        self._tmp.cleanup()

    def test_transcribe_with_injected_fn(self):
        text, err = transcribe_audio(self.vault / "Sermons" / "sermon.mp3",
                                     transcribe_fn=lambda p: "Grace and peace to you.")
        self.assertIsNone(err)
        self.assertEqual(text, "Grace and peace to you.")

    def test_missing_audio_and_failure_safe(self):
        self.assertIn("not found", transcribe_audio(self.vault / "nope.mp3")[1])
        _, err = transcribe_audio(self.vault / "Sermons" / "sermon.mp3",
                                  transcribe_fn=lambda p: (_ for _ in ()).throw(RuntimeError("no model")))
        self.assertIn("could not transcribe", err)

    def test_sidecar_written_and_additive(self):
        rep = transcribe_to_sidecar(self.vault, "Sermons/sermon.mp3",
                                    transcribe_fn=lambda p: "Equipped in the last hour.")
        self.assertIsNone(rep["error"])
        self.assertEqual(rep["sidecar"], "AI/Derived/sermon.transcript.md")
        body = (self.vault / rep["sidecar"]).read_text(encoding="utf-8")
        self.assertIn("Equipped in the last hour.", body)
        self.assertIn("ai-derived: transcript", body)
        # original audio untouched
        self.assertTrue((self.vault / "Sermons" / "sermon.mp3").exists())

    def test_sidecar_resolves_by_name(self):
        rep = transcribe_to_sidecar(self.vault, "sermon.mp3",   # bare name → vault search
                                    transcribe_fn=lambda p: "Text.")
        self.assertIsNone(rep["error"])


if __name__ == "__main__":
    unittest.main()
