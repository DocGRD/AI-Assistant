"""v1.9.3 — server-side TTS engine selection (piper preferred, espeak fallback, off)."""

import unittest
from unittest import mock

from assistant_core import tts


class TestTtsSynthesize(unittest.TestCase):
    def test_off_returns_none(self):
        self.assertIsNone(tts.synthesize("hello", {"tts_engine": "off"}))

    def test_empty_text_returns_none(self):
        self.assertIsNone(tts.synthesize("   ", {}))

    def test_prefers_piper_when_it_succeeds(self):
        with mock.patch.object(tts, "_piper", return_value=b"WAVDATA") as mp, \
             mock.patch.object(tts, "_espeak", return_value=b"ESPEAK") as me:
            wav, engine = tts.synthesize("hi", {"tts_piper_model": "/m.onnx"})
        self.assertEqual((wav, engine), (b"WAVDATA", "piper"))
        mp.assert_called_once()
        me.assert_not_called()

    def test_falls_back_to_espeak_when_piper_unavailable(self):
        with mock.patch.object(tts, "_piper", return_value=None), \
             mock.patch.object(tts, "_espeak", return_value=b"ESPEAK"):
            wav, engine = tts.synthesize("hi", {})
        self.assertEqual((wav, engine), (b"ESPEAK", "espeak"))

    def test_piper_forced_does_not_fall_back(self):
        with mock.patch.object(tts, "_piper", return_value=None), \
             mock.patch.object(tts, "_espeak", return_value=b"ESPEAK"):
            self.assertIsNone(tts.synthesize("hi", {"tts_engine": "piper"}))

    def test_none_when_no_engine(self):
        with mock.patch.object(tts, "_piper", return_value=None), \
             mock.patch.object(tts, "_espeak", return_value=None):
            self.assertIsNone(tts.synthesize("hi", {}))

    def test_available_engine_reports_espeak(self):
        with mock.patch.object(tts, "_find_exe", side_effect=lambda n: "/usr/bin/espeak" if "espeak" in n else None):
            self.assertEqual(tts.available_engine({}), "espeak")

    def test_available_engine_off(self):
        self.assertIsNone(tts.available_engine({"tts_engine": "off"}))


if __name__ == "__main__":
    unittest.main()
