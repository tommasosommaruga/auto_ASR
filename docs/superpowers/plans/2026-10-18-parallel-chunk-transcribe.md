# Parallel Chunk Transcription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speed up one long recording by hybrid-splitting audio, transcribing chunks concurrently on cpu/cuda, merging segments, then diarizing the full file — without a multi-recording job queue.

**Architecture:** Pure `audio_chunks.py` plans splits and merges `TimedText`. `parallel_transcribe.py` runs a small CT2 model pool with activity chunk progress. `pipeline.transcribe_file` branches: short or mlx → single-pass; long cpu/cuda → parallel path. Diarization stays once on the full buffer after merge.

**Tech Stack:** Python 3, NumPy, faster-whisper / CTranslate2, existing `activity` + `alignment.TimedText`, `unittest`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-18-parallel-chunk-transcribe-design.md`
- One heavy job only; no multi-recording STT queue
- `PARALLEL_THRESHOLD_S = 180`; target chunk ~90s; hard max ~120s; overlap ~1.0s
- cpu/cuda parallel; mlx remains single-pass in v1
- Diarize full audio after merge
- No Settings UI; no Android / upload / feedback-shell changes
- Prefer in-memory numpy chunks (faster-whisper accepts `np.ndarray`)
- Skip git commits unless the user asks
- Confirm before large rewrites of uncommitted local edits in unrelated files

## File map

| File | Responsibility |
|------|----------------|
| `audio_chunks.py` | Constants, `AudioChunk` plan, hybrid split, merge + overlap dedupe |
| `parallel_transcribe.py` | Worker count, model pool, dispatch, activity updates |
| `activity.py` | Add progress updater that does **not** force `phase=download` |
| `pipeline.py` | Branch in `transcribe_file`; expose model factory for the pool |
| `tests/test_audio_chunks.py` | Split / merge unit tests |
| `tests/test_parallel_transcribe.py` | Worker policy + stubbed pool / activity |
| `tests/test_activity.py` | Cover new progress helper |
| `tests/test_pipeline_empty.py` | Keep green; add long-audio branch mock if needed |

---

### Task 1: Chunk plan + merge (pure)

**Files:**
- Create: `audio_chunks.py`
- Create: `tests/test_audio_chunks.py`

**Interfaces:**
- Produces:
  - Constants: `PARALLEL_THRESHOLD_S = 180`, `TARGET_CHUNK_S = 90.0`, `MAX_CHUNK_S = 120.0`, `OVERLAP_S = 1.0`, `SAMPLE_RATE = 16000`
  - `@dataclass(frozen=True) class AudioChunk`: `index: int`, `start_s: float`, `end_s: float`, `overlap_left_s: float`, `overlap_right_s: float`
  - `duration_seconds(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float`
  - `should_parallelize(duration_s: float, device: str) -> bool` — True iff `duration_s >= PARALLEL_THRESHOLD_S` and `device` in `{"cpu", "cuda"}`
  - `plan_chunks(audio: np.ndarray, sample_rate: int = SAMPLE_RATE, *, target_s: float = TARGET_CHUNK_S, max_s: float = MAX_CHUNK_S, overlap_s: float = OVERLAP_S) -> list[AudioChunk]`
  - `slice_audio(audio: np.ndarray, chunk: AudioChunk, sample_rate: int = SAMPLE_RATE) -> np.ndarray`
  - `merge_segments(chunk_results: list[tuple[AudioChunk, list[TimedText]]]) -> list[TimedText]`
- Consumes: `alignment.TimedText`, `numpy`

- [ ] **Step 1: Write failing tests**

Create `tests/test_audio_chunks.py`:

```python
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

    def test_long_mlx_stays_single_pass(self):
        self.assertFalse(audio_chunks.should_parallelize(600.0, "mlx"))


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
```

- [ ] **Step 2: Run tests — expect fail**

Run: `python -m unittest tests.test_audio_chunks -v`

Expected: FAIL / import error (`No module named 'audio_chunks'`)

- [ ] **Step 3: Implement `audio_chunks.py`**

```python
"""Split long mono audio into chunks and merge timed transcript pieces."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from alignment import TimedText

PARALLEL_THRESHOLD_S = 180
TARGET_CHUNK_S = 90.0
MAX_CHUNK_S = 120.0
OVERLAP_S = 1.0
SAMPLE_RATE = 16000

# Energy VAD knobs (lightweight; not a neural model).
_FRAME_S = 0.02
_SILENCE_RMS = 0.01
_MIN_SILENCE_S = 0.3


@dataclass(frozen=True)
class AudioChunk:
    index: int
    start_s: float
    end_s: float
    overlap_left_s: float
    overlap_right_s: float


def duration_seconds(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    if audio.size == 0:
        return 0.0
    return float(audio.shape[0]) / float(sample_rate)


def should_parallelize(duration_s: float, device: str) -> bool:
    return float(duration_s) >= PARALLEL_THRESHOLD_S and device in {"cpu", "cuda"}


def plan_chunks(
    audio: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    *,
    target_s: float = TARGET_CHUNK_S,
    max_s: float = MAX_CHUNK_S,
    overlap_s: float = OVERLAP_S,
) -> list[AudioChunk]:
    total_s = duration_seconds(audio, sample_rate)
    if total_s <= 0:
        return []
    if total_s <= max_s:
        return [AudioChunk(0, 0.0, total_s, 0.0, 0.0)]

    silence = _silence_mask(audio, sample_rate)
    cuts: list[tuple[float, bool]] = []  # (time_s, forced)
    cursor = 0.0
    while cursor < total_s:
        remain = total_s - cursor
        if remain <= max_s:
            break
        ideal = cursor + target_s
        latest = cursor + max_s
        cut, forced = _pick_cut(silence, sample_rate, ideal, cursor + _MIN_SILENCE_S, latest)
        cuts.append((cut, forced))
        cursor = cut

    return _chunks_from_cuts(total_s, cuts, overlap_s)


def slice_audio(
    audio: np.ndarray,
    chunk: AudioChunk,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    start = int(round(chunk.start_s * sample_rate))
    end = int(round(chunk.end_s * sample_rate))
    start = max(0, min(start, audio.shape[0]))
    end = max(start, min(end, audio.shape[0]))
    return np.ascontiguousarray(audio[start:end], dtype=np.float32)


def merge_segments(
    chunk_results: list[tuple[AudioChunk, list[TimedText]]],
) -> list[TimedText]:
    ranked: list[tuple[float, float, str, float]] = []
    for chunk, segments in chunk_results:
        core_start = chunk.start_s + chunk.overlap_left_s
        core_end = chunk.end_s - chunk.overlap_right_s
        for segment in segments:
            text = " ".join(segment.text.split())
            if not text:
                continue
            start = float(segment.start) + chunk.start_s
            end = float(segment.end) + chunk.start_s
            mid = (start + end) / 2.0
            if core_end > core_start and core_start <= mid <= core_end:
                score = 2.0
            elif chunk.start_s <= mid <= chunk.end_s:
                score = 1.0
            else:
                score = 0.0
            ranked.append((start, end, text, score))

    ranked.sort(key=lambda row: (row[0], -row[3]))
    merged: list[TimedText] = []
    for start, end, text, score in ranked:
        if merged:
            prev = merged[-1]
            same = " ".join(prev.text.split()).lower() == text.lower()
            close = abs(prev.start - start) <= 1.25 and abs(prev.end - end) <= 1.25
            if same and close:
                # Keep the higher-score copy already placed (sorted -score).
                continue
        merged.append(TimedText(start=round(start, 2), end=round(end, 2), text=text))
    return merged


def _silence_mask(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    frame = max(1, int(sample_rate * _FRAME_S))
    n = audio.shape[0] // frame
    if n == 0:
        return np.zeros(0, dtype=bool)
    trimmed = audio[: n * frame].reshape(n, frame)
    rms = np.sqrt(np.mean(np.square(trimmed), axis=1))
    return rms < _SILENCE_RMS


def _pick_cut(
    silence: np.ndarray,
    sample_rate: int,
    ideal_s: float,
    earliest_s: float,
    latest_s: float,
) -> tuple[float, bool]:
    if silence.size == 0:
        return latest_s, True
    frame_s = _FRAME_S
    lo = int(earliest_s / frame_s)
    hi = int(latest_s / frame_s)
    lo = max(0, min(lo, silence.size - 1))
    hi = max(lo, min(hi, silence.size - 1))
    ideal_i = int(ideal_s / frame_s)
    best_i = None
    best_dist = None
    run = 0
    need = max(1, int(_MIN_SILENCE_S / frame_s))
    for i in range(lo, hi + 1):
        if silence[i]:
            run += 1
        else:
            run = 0
        if run >= need:
            dist = abs(i - ideal_i)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_i = i
    if best_i is None:
        return latest_s, True
    return (best_i + 1) * frame_s, False


def _chunks_from_cuts(
    total_s: float,
    cuts: list[tuple[float, bool]],
    overlap_s: float,
) -> list[AudioChunk]:
    boundaries = [0.0] + [c[0] for c in cuts] + [total_s]
    forced_flags = [False] + [c[1] for c in cuts] + [False]
    chunks: list[AudioChunk] = []
    for index in range(len(boundaries) - 1):
        start = boundaries[index]
        end = boundaries[index + 1]
        if end <= start:
            continue
        # Expand into overlap only across forced cuts.
        left = overlap_s if index > 0 and forced_flags[index] else 0.0
        right = overlap_s if index + 1 < len(forced_flags) - 1 and forced_flags[index + 1] else 0.0
        abs_start = max(0.0, start - left)
        abs_end = min(total_s, end + right)
        chunks.append(
            AudioChunk(
                index=len(chunks),
                start_s=abs_start,
                end_s=abs_end,
                overlap_left_s=start - abs_start,
                overlap_right_s=abs_end - end,
            )
        )
    return chunks
```

Tune silence thresholds if `test_silence_preferred_near_target` is flaky (raise speech amplitude / lower `_SILENCE_RMS`). Keep the test intent: cut lands in the gap.

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m unittest tests.test_audio_chunks -v`

Expected: OK

- [ ] **Step 5: Commit** (only if the user asked)

```bash
git add audio_chunks.py tests/test_audio_chunks.py
git commit -m "Add hybrid audio chunk plan and segment merge."
```

---

### Task 2: Activity progress without forcing download phase

**Files:**
- Modify: `activity.py`
- Modify: `tests/test_activity.py`

**Interfaces:**
- Produces: `activity.progress(received: int, total: int) -> None` — updates `received`/`total`, keeps `active=True`, does **not** change `phase` or `label`
- Consumes: existing lock/`_state`
- Why: `activity.note` always sets `phase="download"`, which would break chunk UI labels during `transcribe`

- [ ] **Step 1: Write failing test**

Append to `tests/test_activity.py`:

```python
    def test_progress_keeps_transcribe_phase(self):
        activity.begin("transcribe", "Transcribing 0/4")
        activity.progress(2, 4)
        snap = activity.snapshot()
        self.assertEqual(snap["phase"], "transcribe")
        self.assertEqual(snap["label"], "Transcribing 0/4")
        self.assertEqual(snap["received"], 2)
        self.assertEqual(snap["total"], 4)
        self.assertEqual(snap["remaining"], 2)
```

- [ ] **Step 2: Run test — expect fail**

Run: `python -m unittest tests.FAKESECRET_e4f5g6h7i8j9k0l1m2n3 -v`

Expected: FAIL (`AttributeError: module 'activity' has no attribute 'progress'`)

- [ ] **Step 3: Implement**

Add to `activity.py` after `note_at_least`:

```python
def progress(received: int, total: int) -> None:
    """Update byte/chunk counters without changing phase (unlike note())."""
    with _lock:
        _state["active"] = True
        _state["received"] = max(0, int(received))
        _state["total"] = max(0, int(total))
```

Also add a small helper used by the parallel runner (same file or in `parallel_transcribe.py`):

Prefer updating the label from the runner via `activity.begin("transcribe", f"Transcribing {done}/{total}")` then `activity.progress(done, total)` so the strip shows both label and bar.

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m unittest tests.test_activity -v`

Expected: OK

- [ ] **Step 5: Commit** (only if the user asked)

```bash
git add activity.py tests/test_activity.py
git commit -m "Allow activity progress without forcing download phase."
```

---

### Task 3: Parallel runner with injectable transcriber

**Files:**
- Create: `parallel_transcribe.py`
- Create: `tests/test_parallel_transcribe.py`

**Interfaces:**
- Produces:
  - `worker_count(device: str, cpu_threads: int, chunk_count: int) -> int`
  - `transcribe_chunks(*, chunks: list[AudioChunk], audio: np.ndarray, sample_rate: int, worker_n: int, transcribe_fn: Callable[[np.ndarray], tuple[list[TimedText], str | None]], on_progress: Callable[[int, int], None] | None = None) -> tuple[list[TimedText], str | None]`
  - `transcribe_fn` receives one chunk’s samples and returns `(segments_local_time, language)`
  - On first exception from a worker: cancel remaining futures, re-raise
- Consumes: `audio_chunks`, `concurrent.futures.ThreadPoolExecutor`, `activity` (via `on_progress` callback — keep module free of Whisper)

- [ ] **Step 1: Write failing tests**

Create `tests/test_parallel_transcribe.py`:

```python
"""Parallel chunk dispatch and worker policy."""

from __future__ import annotations

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
            # Distinct text per chunk length so merge keeps both.
            tag = "a" if samples.shape[0] == sr * 100 else "b"
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

        def boom(samples: np.ndarray):
            raise RuntimeError("chunk failed")

        with self.assertRaises(RuntimeError):
            parallel_transcribe.transcribe_chunks(
                chunks=chunks,
                audio=audio,
                sample_rate=sr,
                worker_n=2,
                transcribe_fn=boom,
                on_progress=None,
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests — expect fail**

Run: `python -m unittest tests.test_parallel_transcribe -v`

Expected: FAIL / import error

- [ ] **Step 3: Implement `parallel_transcribe.py`**

```python
"""Run Whisper over audio chunks concurrently for one recording."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import numpy as np

import audio_chunks
from alignment import TimedText
from audio_chunks import AudioChunk

TranscribeFn = Callable[[np.ndarray], tuple[list[TimedText], str | None]]
ProgressFn = Callable[[int, int], None]


def worker_count(device: str, cpu_threads: int, chunk_count: int) -> int:
    if chunk_count <= 0:
        return 0
    if device == "cuda":
        n = 2
    elif device == "cpu":
        n = min(4, max(1, int(cpu_threads) // 2))
    else:
        n = 1
    return max(1, min(n, chunk_count))


def transcribe_chunks(
    *,
    chunks: list[AudioChunk],
    audio: np.ndarray,
    sample_rate: int,
    worker_n: int,
    transcribe_fn: TranscribeFn,
    on_progress: ProgressFn | None = None,
) -> tuple[list[TimedText], str | None]:
    if not chunks:
        return [], None

    total = len(chunks)
    if on_progress is not None:
        on_progress(0, total)

    results: dict[int, tuple[AudioChunk, list[TimedText], str | None]] = {}
    workers = max(1, min(int(worker_n), total))

    def run_one(chunk: AudioChunk) -> tuple[AudioChunk, list[TimedText], str | None]:
        samples = audio_chunks.slice_audio(audio, chunk, sample_rate)
        segments, language = transcribe_fn(samples)
        return chunk, segments, language

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_one, chunk): chunk for chunk in chunks}
            done = 0
            for future in as_completed(futures):
                chunk, segments, language = future.result()
                results[chunk.index] = (chunk, segments, language)
                done += 1
                if on_progress is not None:
                    on_progress(done, total)
    except Exception:
        # as_completed raises from future.result(); executor context exits and cancels.
        raise

    ordered = [results[index] for index in sorted(results)]
    detected = next((lang for _, _, lang in ordered if lang), None)
    merged = audio_chunks.merge_segments([(chunk, segs) for chunk, segs, _ in ordered])
    return merged, detected
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m unittest tests.test_parallel_transcribe -v`

Expected: OK

- [ ] **Step 5: Commit** (only if the user asked)

```bash
git add parallel_transcribe.py tests/test_parallel_transcribe.py
git commit -m "Add parallel chunk transcription runner."
```

---

### Task 4: Whisper model factory + CT2 chunk callable

**Files:**
- Modify: `pipeline.py` (extract factory; add chunk transcribe helper; branch `transcribe_file`)
- Modify: `tests/test_pipeline_empty.py` (ensure short path still works; add parallel-path mock test)

**Interfaces:**
- Produces:
  - `pipeline.create_whisper_model(settings, device, compute) -> WhisperModel` — always constructs (no global cache)
  - Keep `_get_whisper` using cache via `create_whisper_model` for single-pass
  - `pipeline._transcribe_ct2_audio(model, audio: np.ndarray, requested: str) -> tuple[list[TimedText], str | None]`
  - `pipeline._transcribe_parallel_ct2(audio, path, settings, requested, device, compute) -> tuple[list[TimedText], str | None]`
  - `transcribe_file` uses `should_parallelize` after `resolve_device`
- Consumes: `audio_chunks`, `parallel_transcribe`, `activity`

- [ ] **Step 1: Write failing pipeline branch test**

Add to `tests/test_pipeline_empty.py` (or new `tests/test_pipeline_parallel.py` if cleaner):

```python
    def test_long_cpu_uses_parallel_path(self):
        audio = np.zeros(16000 * 200, dtype=np.float32)
        calls = {"n": 0}

        def fake_parallel(**kwargs):
            calls["n"] += 1
            return [TimedText(0.0, 1.0, "hi")], "en"

        with patch.object(pipeline, "load_mono_f32", return_value=audio), patch.object(
            pipeline, "ensure_diarization_models"
        ), patch.object(pipeline, "resolve_device", return_value=("cpu", "int8")), patch.object(
            pipeline, "_transcribe_parallel_ct2", side_effect=fake_parallel
        ) as parallel_mock, patch.object(
            pipeline, "_transcribe_ct2"
        ) as single_mock, patch.object(pipeline, "_diarize", return_value=[]):
            from alignment import TimedText  # if not already imported
            result = pipeline.transcribe_file(
                Path("long.webm"),
                {"model": "small", "language": "en", "device": "cpu",
                 "compute_type": "int8", "cpu_threads": 4, "cluster_threshold": 0.7},
                -1,
            )
        self.assertEqual(calls["n"], 1)
        single_mock.assert_not_called()
        self.assertEqual(result["turns"][0]["text"], "hi")
```

Fix imports at top of the test file (`TimedText` from `alignment`). Adjust `fake_parallel` signature to match whatever `_transcribe_parallel_ct2` defines (positional is fine).

Also keep existing empty short-audio test green (200s → parallel; 1s → single).

- [ ] **Step 2: Run test — expect fail**

Run: `python -m unittest tests.test_pipeline_empty -v`

Expected: FAIL (`_transcribe_parallel_ct2` missing) until Step 3.

- [ ] **Step 3: Implement pipeline wiring**

1. Refactor `_get_whisper` body that constructs `WhisperModel(...)` into:

```python
def create_whisper_model(settings: dict, device: str, compute: str) -> WhisperModel:
    name = settings["model"]
    if not _ct2_speech_ready(name):
        raise RuntimeError(
            f"{name} is not installed on this computer. "
            "Install it when prompted, or choose an installed model in Settings."
        )
    try:
        return WhisperModel(
            name,
            device=device,
            compute_type=compute,
            cpu_threads=settings["cpu_threads"],
            download_root=str(WHISPER_DIR),
            local_files_only=True,
            use_auth_token=_hf_token(),
        )
    except RuntimeError:
        raise
    except Exception as exc:
        # keep existing cuda / generic error mapping from _get_whisper
        ...
```

2. `_get_whisper` caches `create_whisper_model` result under `_whisper_lock` as today.

3. Add CT2-on-ndarray helper:

```python
def _transcribe_ct2_audio(
    model: WhisperModel,
    audio: np.ndarray,
    requested: str,
) -> tuple[list[TimedText], str | None]:
    segments_iter, info = model.transcribe(
        audio,
        language=None if requested == "auto" else requested,
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    segments = [
        TimedText(start=segment.start, end=segment.end, text=segment.text)
        for segment in segments_iter
    ]
    return segments, getattr(info, "language", None)
```

4. Add parallel orchestrator:

```python
def _transcribe_parallel_ct2(
    audio: np.ndarray,
    settings: dict,
    requested: str,
    device: str,
    compute: str,
) -> tuple[list[TimedText], str | None]:
    import audio_chunks
    import parallel_transcribe

    chunks = audio_chunks.plan_chunks(audio)
    threads = int(settings["cpu_threads"])
    workers = parallel_transcribe.worker_count(device, threads, len(chunks))
    # Avoid oversubscription: each pooled model gets a share of threads.
    per_worker_settings = dict(settings)
    per_worker_settings["cpu_threads"] = max(1, threads // max(1, workers))

    models: list[WhisperModel] = []
    try:
        for _ in range(workers):
            try:
                models.append(create_whisper_model(per_worker_settings, device, compute))
            except Exception:
                if device == "cuda" and models:
                    break  # OOM on 2nd model → continue with fewer workers
                raise
        if not models:
            raise RuntimeError("Could not load the speech model for parallel transcription.")
        workers = len(models)
        counter = {"i": 0}
        lock = threading.Lock()

        def transcribe_fn(samples: np.ndarray):
            with lock:
                model = models[counter["i"] % len(models)]
                counter["i"] += 1
            # Better: assign model per future via worker-local storage.
            return _transcribe_ct2_audio(model, samples, requested)

        # Prefer one model per in-flight task without a racy counter:
        # build a queue.Queue of models; each task checkout/return.
        ...
```

Use a `queue.Queue` of models (put each model once; task `get` → transcribe → `put`):

```python
    import queue

    model_q: queue.Queue[WhisperModel] = queue.Queue()
    for model in models:
        model_q.put(model)

    def transcribe_fn(samples: np.ndarray):
        model = model_q.get()
        try:
            return _transcribe_ct2_audio(model, samples, requested)
        finally:
            model_q.put(model)

    def on_progress(done: int, total: int) -> None:
        activity.begin("transcribe", f"Transcribing {done}/{total}")
        activity.progress(done, total)

    try:
        return parallel_transcribe.transcribe_chunks(
            chunks=chunks,
            audio=audio,
            sample_rate=audio_chunks.SAMPLE_RATE,
            worker_n=workers,
            transcribe_fn=transcribe_fn,
            on_progress=on_progress,
        )
    finally:
        # Drop pooled models; single-pass cache remains separate.
        models.clear()
```

5. Branch in `transcribe_file` after `resolve_device`:

```python
    duration_s = float(audio.shape[0]) / 16000.0
    activity.begin("transcribe", "Transcribing")
    if audio_chunks.should_parallelize(duration_s, device):
        segments, detected = _transcribe_parallel_ct2(
            audio, resolved, requested, device, compute
        )
    elif device == "mlx":
        segments, detected = _transcribe_mlx(path, resolved, requested)
    else:
        segments, detected = _transcribe_ct2(path, resolved, requested, device, compute)
```

Keep imports at module top (`import audio_chunks`, `import parallel_transcribe`) — no inline imports except existing mlx lazy import pattern if required for optional deps. Prefer top-level imports for `audio_chunks` / `parallel_transcribe`.

Place `queue` / `threading` imports at top of `pipeline.py` (`threading` already imported).

- [ ] **Step 4: Run tests — expect pass**

Run:

```bash
python -m unittest tests.test_pipeline_empty tests.test_audio_chunks tests.test_parallel_transcribe tests.test_activity -v
```

Expected: OK

Also run full suite:

```bash
python -m unittest discover -s tests -v
```

Expected: OK

- [ ] **Step 5: Commit** (only if the user asked)

```bash
git add pipeline.py tests/test_pipeline_empty.py tests/test_pipeline_parallel.py
git commit -m "Wire parallel chunk transcription into long cpu/cuda jobs."
```

---

### Task 5: Manual verification checklist

**Files:** none (manual)

- [ ] **Step 1: Short clip regression**

Record or upload under 3 minutes on cpu → Transcribe → activity label stays `Transcribing` (not `0/N`) → Ready transcript.

- [ ] **Step 2: Long clip parallel**

Use at least 3 minutes audio on cpu (or cuda). Watch `/api/activity` or UI: `Transcribing k/n` with `received`/`total` advancing. Confirm wall-clock improves vs prior single-pass on the same machine/model when workers > 1.

- [ ] **Step 3: Speakers**

Long file with 2 speakers → turns still get speaker labels (full-file diarize path).

- [ ] **Step 4: Failure soft path**

Force a chunk failure (temporary bad mock or corrupt mid-file only in a dev branch) → job errors, activity clears, library item remains pending without a half transcript.

- [ ] **Step 5: MLX (if on Apple Silicon)**

Long file with device auto→mlx → still single-pass; no chunk labels required.

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| Hybrid split + overlap | Task 1 |
| Merge + dedupe | Task 1 |
| Threshold 180s; mlx single-pass | Task 1 `should_parallelize` + Task 4 branch |
| cpu/cuda workers | Task 3 + Task 4 pool |
| CUDA OOM → fewer workers | Task 4 model load loop |
| Activity chunk progress | Task 2 + Task 3/4 `on_progress` |
| Full-file diarize after merge | Task 4 keeps existing post-STT diarize |
| No API / Settings / Android | Not in file map |
| Unit tests split/merge/pool | Tasks 1–3 |
| Empty / short path green | Task 4 + existing tests |

No TBD placeholders. Types use `AudioChunk`, `TimedText`, `transcribe_chunks`, `create_whisper_model` consistently across tasks.
