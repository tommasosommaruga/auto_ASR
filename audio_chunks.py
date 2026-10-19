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
    # Long jobs always chunk. MLX is remapped to a CPU worker pool in pipeline
    # (Metal multi-model rarely helps; CT2 concurrency does).
    return float(duration_s) >= PARALLEL_THRESHOLD_S and device in {"cpu", "cuda", "mlx"}


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
    prev_forced = False
    while cursor < total_s:
        remain = total_s - cursor
        left_overlap = overlap_s if cursor > 0.0 and prev_forced else 0.0
        if remain + left_overlap <= max_s:
            break
        ideal = cursor + target_s
        # Reserve overlap pads so each chunk's abs span stays within max_s.
        latest = cursor + max_s - left_overlap - overlap_s
        cut, forced = _pick_cut(silence, sample_rate, ideal, cursor + _MIN_SILENCE_S, latest)
        cuts.append((cut, forced))
        prev_forced = forced
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
