"""Hybrid chunk plan and merge for long-audio parallel STT."""

from __future__ import annotations

import unittest

import numpy as np

import audio_chunks
from alignment import TimedText


class ShouldParallelizeTests(unittest.TestCase):
    def test_short_cpu_stays_single_pass(self):
        self.assertFalse(audio_chunks.should_parallelize(179.9, "cpu"))

    def test_long_cpu_parallelizes(self):
        self.assertTrue(audio_chunks.should_parallelize(180.0, "cpu"))

    def test_long_mlx_parallelizes(self):
        self.assertTrue(audio_chunks.should_parallelize(600.0, "mlx"))


class PlanChunksTests(unittest.TestCase):
    def test_short_audio_is_one_chunk(self):
        audio = np.zeros(16000 * 30, dtype=np.float32)
        chunks = audio_chunks.plan_chunks(audio)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].start_s, 0.0)
        self.assertAlmostEqual(chunks[0].end_s, 30.0, places=2)

    def test_hard_max_splits_continuous_speech(self):
        # Loud continuous energy → forced cuts near max with overlap.
        rng = np.random.default_rng(0)
        audio = (rng.random(16000 * 250) * 0.4).astype(np.float32)
        chunks = audio_chunks.plan_chunks(audio, max_s=120.0, target_s=90.0, overlap_s=1.0)
        self.assertGreaterEqual(len(chunks), 3)
        for chunk in chunks:
            self.assertLessEqual(chunk.end_s - chunk.start_s, 120.0 + 1e-3)
        # Adjacent forced cuts should advertise overlap on at least one side.
        self.assertTrue(any(c.overlap_left_s > 0 or c.overlap_right_s > 0 for c in chunks[1:]))

    def test_silence_preferred_near_target(self):
        sr = 16000
        # 100s speech, 2s silence, 100s speech — cut should land in the silence gap.
        speech = np.full(sr * 100, 0.2, dtype=np.float32)
        silence = np.zeros(sr * 2, dtype=np.float32)
        audio = np.concatenate([speech, silence, speech])
        chunks = audio_chunks.plan_chunks(audio, target_s=90.0, max_s=120.0, overlap_s=1.0)
        self.assertEqual(len(chunks), 2)
        cut = chunks[0].end_s
        self.assertGreaterEqual(cut, 100.0)
        self.assertLessEqual(cut, 102.0)


class MergeSegmentsTests(unittest.TestCase):
    def test_offsets_by_chunk_start(self):
        c0 = audio_chunks.AudioChunk(0, 0.0, 90.0, 0.0, 0.0)
        c1 = audio_chunks.AudioChunk(1, 90.0, 180.0, 0.0, 0.0)
        merged = audio_chunks.merge_segments(
            [
                (c0, [TimedText(1.0, 2.0, "hello")]),
                (c1, [TimedText(0.5, 1.5, "world")]),
            ]
        )
        self.assertEqual(merged[0], TimedText(1.0, 2.0, "hello"))
        self.assertEqual(merged[1], TimedText(90.5, 91.5, "world"))

    def test_overlap_dedupes_duplicate_text(self):
        c0 = audio_chunks.AudioChunk(0, 0.0, 91.0, 0.0, 1.0)
        c1 = audio_chunks.AudioChunk(1, 90.0, 180.0, 1.0, 0.0)
        merged = audio_chunks.merge_segments(
            [
                (c0, [TimedText(89.5, 90.5, "same phrase")]),
                (c1, [TimedText(0.2, 1.0, "same phrase")]),
            ]
        )
        texts = [row.text for row in merged]
        self.assertEqual(texts.count("same phrase"), 1)


if __name__ == "__main__":
    unittest.main()
