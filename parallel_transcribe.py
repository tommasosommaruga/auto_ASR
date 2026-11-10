"""Run transcription over audio chunks concurrently for one recording."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import numpy as np

import audio_chunks
from alignment import TimedText
from audio_chunks import AudioChunk

TranscribeFn = Callable[[np.ndarray], tuple[list[TimedText], Optional[str]]]
ProgressFn = Callable[[int, int], None]
ChunkDoneFn = Callable[[AudioChunk, list[TimedText], Optional[str]], None]
PriorMap = dict[int, tuple[list[TimedText], Optional[str]]]


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
    prior_results: PriorMap | None = None,
    on_chunk_complete: ChunkDoneFn | None = None,
) -> tuple[list[TimedText], str | None]:
    if not chunks:
        return [], None

    total = len(chunks)
    results: dict[int, tuple[AudioChunk, list[TimedText], str | None]] = {}
    prior = prior_results or {}
    for chunk in chunks:
        if chunk.index not in prior:
            continue
        segments, language = prior[chunk.index]
        results[chunk.index] = (chunk, list(segments), language)

    pending = [chunk for chunk in chunks if chunk.index not in results]
    done = len(results)
    if on_progress is not None:
        on_progress(done, total)

    if not pending:
        return _finalize(results)

    workers = max(1, min(int(worker_n), len(pending)))

    def run_one(chunk: AudioChunk) -> tuple[AudioChunk, list[TimedText], str | None]:
        samples = audio_chunks.slice_audio(audio, chunk, sample_rate)
        segments, language = transcribe_fn(samples)
        return chunk, segments, language

    pool = ThreadPoolExecutor(max_workers=workers)
    futures = {pool.submit(run_one, chunk): chunk for chunk in pending}
    aborted = False
    try:
        for future in as_completed(futures):
            try:
                chunk, segments, language = future.result()
            except Exception:
                aborted = True
                for pending_future in futures:
                    pending_future.cancel()
                pool.shutdown(wait=False, cancel_futures=True)
                raise
            results[chunk.index] = (chunk, segments, language)
            if on_chunk_complete is not None:
                on_chunk_complete(chunk, segments, language)
            done += 1
            if on_progress is not None:
                on_progress(done, total)
    finally:
        if not aborted:
            pool.shutdown(wait=True)

    return _finalize(results)


def _finalize(
    results: dict[int, tuple[AudioChunk, list[TimedText], str | None]],
) -> tuple[list[TimedText], str | None]:
    ordered = [results[index] for index in sorted(results)]
    detected = next((lang for _, _, lang in ordered if lang), None)
    merged = audio_chunks.merge_segments([(chunk, segs) for chunk, segs, _ in ordered])
    return merged, detected
