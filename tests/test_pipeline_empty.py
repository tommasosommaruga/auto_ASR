"""No speech still keeps a usable result so the audio can be saved."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

import library
import pipeline


class EmptySpeechTests(unittest.TestCase):
    def setUp(self):
        self._original = library.LIBRARY
        self._directory = tempfile.TemporaryDirectory()
        library.LIBRARY = Path(self._directory.name)

    def tearDown(self):
        library.LIBRARY = self._original
        self._directory.cleanup()

    def test_library_keeps_audio_when_transcript_is_empty(self):
        source = Path(self._directory.name) / "quiet.webm"
        source.write_bytes(b"fake-audio-bytes")
        saved = library.save_recording(
            source,
            {
                "turns": [],
                "duration": 3.5,
                "model": "small",
                "device": "cpu",
                "language": "en",
                "detected_language": "en",
            },
        )
        self.assertEqual(saved["turns"], [])
        self.assertTrue(saved["title"].startswith("Recording "))
        self.assertEqual(saved["preview"], "")
        self.assertTrue(library.audio_path(saved["id"]).is_file())
        self.assertFalse(source.exists())

    def test_transcribe_returns_empty_turns_instead_of_failing(self):
        audio = np.zeros(16000, dtype=np.float32)
        model = MagicMock()
        info = MagicMock()
        info.language = "en"
        model.transcribe.return_value = (iter([]), info)

        with patch.object(pipeline, "load_mono_f32", return_value=audio), patch.object(
            pipeline, "ensure_diarization_models"
        ), patch.object(pipeline, "_get_whisper", return_value=(model, "cpu", "int8")), patch.object(
            pipeline, "_diarize", return_value=[]
        ):
            result = pipeline.transcribe_file(
                Path("quiet.webm"),
                {"model": "small", "language": "en", "device": "cpu",
                 "compute_type": "int8", "cpu_threads": 4, "cluster_threshold": 0.7},
                -1,
            )

        self.assertEqual(result["turns"], [])
        self.assertEqual(result["text"], "")
        self.assertEqual(result["duration"], 1.0)
        self.assertEqual(result["model"], "small")


if __name__ == "__main__":
    unittest.main()
