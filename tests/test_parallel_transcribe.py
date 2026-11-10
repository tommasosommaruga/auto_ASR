"""Parallel chunk dispatch and worker policy."""

from __future__ import annotations

import time
import unittest

import numpy as np

import activity
import audio_chunks
import parallel_transcribe
from alignment import TimedText


class WorkerCountTests(unittest.TestCase):
    def test_cpu_uses_half_threads_capped(self):
        self.assertEqual(parallel_transcribe.worker_count("cpu", cpu_threads=8, chunk_count=10), 4)
        self.assertEqual(parallel_transcribe.worker_count("cpu", cpu_threads=2, chunk_count=10), 1)

    def test_cuda_prefers_two(self):
        self.assertEqual(parallel_transcribe.worker_count("cuda", cpu_threads=4, chunk_count=10), 2)

    def test_never_exceeds_chunk_count(self):
        self.assertEqual(parallel_transcribe.worker_count("cuda", cpu_threads=4, chunk_count=1), 1)

    def test_mlx_is_one(self):
        self.assertEqual(parallel_transcribe.worker_count("mlx", cpu_threads=8, chunk_count=10), 1)


class TranscribeChunksTests(unittest.TestCase):
    def tearDown(self):
        activity.clear()

    def test_stub_pool_merges_and_reports_progress(self):
        sr = 16000
        audio = np.zeros(sr * 200, dtype=np.float32)
        chunks = [
            audio_chunks.AudioChunk(0, 0.0, 100.0, 0.0, 0.0),
            audio_chunks.AudioChunk(1, 100.0, 200.0, 0.0, 0.0),
        ]
        seen = []

        def fake_transcribe(samples: np.ndarray):
            # Distinct tag per chunk slice (equal 100s spans; use buffer offset).
            base = audio.__array_interface__["data"][0]
            off = samples.__array_interface__["data"][0] - base
            tag = "a" if off == 0 else "b"
            return [TimedText(0.1, 0.2, tag)], "en"

        def on_progress(done: int, total: int) -> None:
            seen.append((done, total))
            activity.begin("transcribe", f"Transcribing {done}/{total}")
            activity.progress(done, total)

        segments, lang = parallel_transcribe.transcribe_chunks(
            chunks=chunks,
            audio=audio,
            sample_rate=sr,
            worker_n=2,
            transcribe_fn=fake_transcribe,
            on_progress=on_progress,
        )
        self.assertEqual(lang, "en")
        self.assertEqual([row.text for row in segments], ["a", "b"])
        self.assertEqual(seen[-1], (2, 2))
        snap = activity.snapshot()
        self.assertEqual(snap["phase"], "transcribe")
        self.assertEqual(snap["received"], 2)
        self.assertEqual(snap["total"], 2)

    def test_worker_failure_aborts(self):
        sr = 16000
        audio = np.zeros(sr * 20, dtype=np.float32)
        chunks = [
            audio_chunks.AudioChunk(0, 0.0, 10.0, 0.0, 0.0),
            audio_chunks.AudioChunk(1, 10.0, 20.0, 0.0, 0.0),
        ]
        base = audio.__array_interface__["data"][0]
        slow_finished = []

        def boom_or_block(samples: np.ndarray):
            off = samples.__array_interface__["data"][0] - base
            if off == 0:
                raise RuntimeError("chunk failed")
            time.sleep(5)
            slow_finished.append(True)
            return [TimedText(0.1, 0.2, "b")], "en"

        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            parallel_transcribe.transcribe_chunks(
                chunks=chunks,
                audio=audio,
                sample_rate=sr,
                worker_n=2,
                transcribe_fn=boom_or_block,
                on_progress=None,
            )
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.0, "abort must not wait for slow peer chunk")
        self.assertEqual(slow_finished, [])

    def test_prior_results_skip_finished_chunks(self):
        sr = 16000
        audio = np.zeros(sr * 200, dtype=np.float32)
        chunks = [
            audio_chunks.AudioChunk(0, 0.0, 100.0, 0.0, 0.0),
            audio_chunks.AudioChunk(1, 100.0, 200.0, 0.0, 0.0),
        ]
        calls = []

        def fake_transcribe(samples: np.ndarray):
            calls.append(samples.shape[0])
            return [TimedText(0.1, 0.2, "b")], "en"

        segments, lang = parallel_transcribe.transcribe_chunks(
            chunks=chunks,
            audio=audio,
            sample_rate=sr,
            worker_n=2,
            transcribe_fn=fake_transcribe,
            prior_results={0: ([TimedText(0.1, 0.2, "a")], "en")},
        )
        self.assertEqual(lang, "en")
        self.assertEqual([row.text for row in segments], ["a", "b"])
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
