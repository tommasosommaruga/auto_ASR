"""Disk checkpoints for parallel STT chunks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import transcribe_checkpoints
from alignment import TimedText
from audio_chunks import AudioChunk


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.audio = self.root / "audio.m4a"
        self.audio.write_bytes(b"fake")

    def tearDown(self):
        self._dir.cleanup()

    def test_save_and_load_round_trip(self):
        chunks = [
            AudioChunk(0, 0.0, 90.0, 0.0, 0.0),
            AudioChunk(1, 90.0, 180.0, 0.0, 0.0),
        ]
        fp = transcribe_checkpoints.fingerprint(
            model="small",
            language="it",
            device="cpu",
            compute="int8",
            audio_path=self.audio,
            chunks=chunks,
        )
        session = transcribe_checkpoints.open_session(
            self.audio, fingerprint_value=fp, total_chunks=2
        )
        transcribe_checkpoints.save_chunk(
            session,
            chunks[0],
            [TimedText(0.1, 0.5, "ciao")],
            "it",
            fingerprint_value=fp,
            total_chunks=2,
        )
        loaded = transcribe_checkpoints.load_completed(session, chunks)
        self.assertIn(0, loaded)
        self.assertNotIn(1, loaded)
        segs, lang = loaded[0]
        self.assertEqual(lang, "it")
        self.assertEqual(segs[0].text, "ciao")

    def test_fingerprint_mismatch_wipes_old_session(self):
        chunks = [AudioChunk(0, 0.0, 90.0, 0.0, 0.0)]
        fp1 = transcribe_checkpoints.fingerprint(
            model="small",
            language="it",
            device="cpu",
            compute="int8",
            audio_path=self.audio,
            chunks=chunks,
        )
        session = transcribe_checkpoints.open_session(
            self.audio, fingerprint_value=fp1, total_chunks=1
        )
        transcribe_checkpoints.save_chunk(
            session,
            chunks[0],
            [TimedText(0.0, 1.0, "old")],
            "it",
            fingerprint_value=fp1,
            total_chunks=1,
        )
        fp2 = transcribe_checkpoints.fingerprint(
            model="medium",
            language="it",
            device="cpu",
            compute="int8",
            audio_path=self.audio,
            chunks=chunks,
        )
        session2 = transcribe_checkpoints.open_session(
            self.audio, fingerprint_value=fp2, total_chunks=1
        )
        loaded = transcribe_checkpoints.load_completed(session2, chunks)
        self.assertEqual(loaded, {})

    def test_clear_removes_dir(self):
        chunks = [AudioChunk(0, 0.0, 10.0, 0.0, 0.0)]
        fp = transcribe_checkpoints.fingerprint(
            model="small",
            language="en",
            device="cpu",
            compute="int8",
            audio_path=self.audio,
            chunks=chunks,
        )
        session = transcribe_checkpoints.open_session(
            self.audio, fingerprint_value=fp, total_chunks=1
        )
        self.assertTrue(session.is_dir())
        transcribe_checkpoints.clear(self.audio)
        self.assertFalse(session.exists())


if __name__ == "__main__":
    unittest.main()
