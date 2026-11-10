# Parallel chunk transcription for long audio

## Problem

Long recordings run through a single Whisper call inside one heavy job. Wall-clock
time grows roughly with duration. The app already saves audio first and keeps a
single activity slot; we need faster transcription for big files without a
multi-recording job queue.

## Goals

- Speed up **one** long recording by splitting audio, transcribing chunks
  concurrently where the device allows, then merging.
- Keep **one heavy job** and existing `/api/activity` polling.
- Stay correct for speakers: diarize the **full** file after merge.
- Short files stay on today’s single-pass path (no split overhead).

## Non-goals

- Concurrent transcription of multiple recordings (queue of heavy jobs).
- Feedback-shell / Android / upload API redesign.
- New Settings UI for v1 (constants + existing `device` / `cpu_threads`).
- Guaranteeing multi-worker speedup on MLX/Metal in v1.

## Decisions (locked)

| Choice | Value |
|--------|--------|
| Scope | Parallelize **one** file (not multi-recording jobs) |
| Devices | Adaptive: cpu / cuda parallel; mlx single-pass for v1 |
| Gate | Parallel path only if duration ≥ **180s** |
| Split | Hybrid: prefer silence cuts; hard max with ~1s overlap |
| Diarization | Once, on full mono audio, after merge |
| API | Unchanged; still `pipeline.transcribe_file` |

## Architecture

```
load mono 16 kHz
  → duration < 180s OR device == mlx:
        single Whisper pass (current behavior)
  → else:
        hybrid chunk plan
        → N workers (cpu / cuda)
        → merge TimedText (offsets + overlap dedupe)
  → diarize full audio (optional models)
  → assign_speakers → turns
```

Public surface stays `pipeline.transcribe_file(path, settings, num_speakers)`.
Chunk planning and merge live in focused modules so `pipeline.py` only branches.

## Chunking

Constants (v1, not exposed in UI):

- `PARALLEL_THRESHOLD_S = 180`
- Target chunk ≈ **90s**, hard max ≈ **120s**
- Overlap ≈ **1.0s** on forced cuts
- Sample rate: **16000** (same as `load_mono_f32`)

Hybrid plan on the in-memory mono buffer:

1. Find silence regions via simple energy / VAD on the waveform (lightweight;
   not a second neural model).
2. Prefer cut points inside silence near the target length.
3. If speech is continuous past the hard max, hard-cut with overlap metadata.
4. Drop empty chunks.

Each chunk carries: `start_s`, `end_s`, `overlap_left_s`, `overlap_right_s`,
and a view/slice of the float32 samples (or temp wav path if a backend requires
a file — prefer in-memory / short temp files only when the Whisper API needs a path).

## Merge

- Add chunk `start_s` to every segment’s `start` / `end`.
- In overlap zones, drop near-duplicate text (same normalized text and close
  times); prefer the segment more fully inside its chunk’s non-overlap core.
- Sort by `start`.
- `detected_language`: first non-empty worker language (sufficient for v1).

Never invent text at boundaries; worst case is dropping a duplicated phrase.

## Workers

After `resolve_device(settings)`:

| Device | Workers | Model loading |
|--------|---------|----------------|
| **cpu** | `min(4, max(1, cpu_threads // 2))`, capped by chunk count | One CT2 `WhisperModel` per worker for the job |
| **cuda** | Prefer **2**, else **1**; on second-model OOM fall back to 1 and continue | Separate models when VRAM allows |
| **mlx** | n/a for v1 | Keep **single-pass** (no split); revisit if measured win |

The parallel path does not serialize all chunks behind today’s single global
`_whisper` lock. Short single-pass may keep the existing singleton cache.

Threads per CT2 model should remain modest so N workers × `cpu_threads` does
not oversubscribe the machine (derive from existing `cpu_threads` setting).

## Activity

Still one job:

- `phase`: `transcribe`
- `label`: `Transcribing {done}/{total}` while chunks run
- `received` / `total`: chunks completed / chunks total (reuse poll fields)
- Single-pass: current `Transcribing` label; progress may stay 0/0
- On hard failure: clear activity; leave recording **pending**; no partial
  transcript write

## Errors

- Empty audio / missing installed model: fail before split (unchanged).
- Any chunk hard-fails: abort remaining work, clear activity, pending + error.
- CUDA OOM on extra model: reduce workers to 1 and continue (not user-facing).
- Diarization failure after successful merge: keep turns, set
  `diarization_error` (unchanged).

## Settings

v1: no new Settings fields. Use constants above plus existing `device`,
`compute_type`, `cpu_threads`, `model`, `language`.

Optional later (out of scope): `parallel_threshold_s`, `max_transcribe_workers`.

## Files

- Create: `audio_chunks.py` — pure split plan + merge helpers
- Create: `parallel_transcribe.py` — worker pool, dispatch, activity updates
- Modify: `pipeline.py` — branch in `transcribe_file` on duration/device
- Touch `activity.py` only if existing `begin` / `note` cannot express chunk
  progress cleanly (prefer reuse)
- Tests: `tests/test_audio_chunks.py`, `tests/test_parallel_transcribe.py`
- This spec: `docs/superpowers/specs/2026-10-18-parallel-chunk-transcribe-design.md`

No changes to upload endpoints, Android, or feedback-shell for v1.

## Testing

- Unit: silence cuts, hard max, overlap metadata, threshold gate.
- Unit: merge offsets and overlap dedupe.
- Unit: worker-count helpers for cpu / cuda / mlx policy.
- Unit with stub chunk transcriber: pool completes, activity `received`/`total`
  advance, merge order correct.
- Manual: long CPU (and CUDA if available) file shows chunk progress and finishes
  faster than single-pass; short file and MLX unchanged; speakers still labeled.

## Done when

- A recording ≥ 180s on cpu/cuda uses hybrid chunks and N workers, with
  `/api/activity` reflecting chunk progress.
- Recordings under 180s and all MLX jobs keep single-pass behavior.
- Speakers come from one full-file diarization after merge.
- Existing empty-transcript and activity tests stay green; new unit tests cover
  split, merge, and pool behavior.
