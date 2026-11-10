"""Persist finished parallel STT chunks so a long job can resume after a crash."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from alignment import TimedText
from audio_chunks import AudioChunk

CHECKPOINT_DIRNAME = "transcribe_checkpoints"
MANIFEST_NAME = "manifest.json"


def checkpoint_dir_for(audio_path: Path) -> Path:
    """Checkpoints live next to the recording audio (library/<id>/…)."""
    return Path(audio_path).resolve().parent / CHECKPOINT_DIRNAME


def fingerprint(
    *,
    model: str,
    language: str,
    device: str,
    compute: str,
    audio_path: Path,
    chunks: list[AudioChunk],
) -> str:
    path = Path(audio_path)
    try:
        stat = path.stat()
        size = int(stat.st_size)
        mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)))
    except OSError:
        size = 0
        mtime_ns = 0
    payload = {
        "v": 1,
        "model": str(model),
        "language": str(language),
        "device": str(device),
        "compute": str(compute),
        "audio": str(path.resolve()),
        "size": size,
        "mtime_ns": mtime_ns,
        "chunks": [
            [chunk.index, round(chunk.start_s, 3), round(chunk.end_s, 3)]
            for chunk in chunks
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def open_session(
    audio_path: Path,
    *,
    fingerprint_value: str,
    total_chunks: int,
) -> Path:
    """Reuse matching checkpoints or wipe and start a fresh session dir."""
    root = checkpoint_dir_for(audio_path)
    manifest_path = root / MANIFEST_NAME
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if (
            str(manifest.get("fingerprint") or "") == fingerprint_value
            and int(manifest.get("total") or 0) == int(total_chunks)
        ):
            return root
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    _write_manifest(root, fingerprint_value, total_chunks, completed=[])
    return root


def load_completed(
    root: Path,
    chunks: list[AudioChunk],
) -> dict[int, tuple[list[TimedText], str | None]]:
    """Load finished chunk transcripts keyed by chunk index."""
    by_index = {chunk.index: chunk for chunk in chunks}
    loaded: dict[int, tuple[list[TimedText], str | None]] = {}
    for path in sorted(root.glob("chunk_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        try:
            index = int(data["index"])
        except (KeyError, TypeError, ValueError):
            continue
        if index not in by_index:
            continue
        segments = []
        for row in data.get("segments") or []:
            text = " ".join(str(row.get("text") or "").split())
            if not text:
                continue
            segments.append(
                TimedText(
                    start=float(row.get("start") or 0),
                    end=float(row.get("end") or 0),
                    text=text,
                )
            )
        language = data.get("language")
        loaded[index] = (segments, str(language) if language else None)
    return loaded


def save_chunk(
    root: Path,
    chunk: AudioChunk,
    segments: list[TimedText],
    language: str | None,
    *,
    fingerprint_value: str,
    total_chunks: int,
) -> None:
    """Atomically write one finished chunk and refresh the manifest."""
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "index": chunk.index,
        "start_s": chunk.start_s,
        "end_s": chunk.end_s,
        "language": language,
        "segments": [
            {"start": segment.start, "end": segment.end, "text": segment.text}
            for segment in segments
        ],
    }
    target = root / f"chunk_{chunk.index:04d}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)

    completed = sorted(
        {
            int(path.stem.split("_", 1)[1])
            for path in root.glob("chunk_*.json")
            if "_" in path.stem
        }
    )
    _write_manifest(root, fingerprint_value, total_chunks, completed=completed)


def clear(audio_path: Path) -> None:
    root = checkpoint_dir_for(audio_path)
    if root.exists():
        shutil.rmtree(root)


def _write_manifest(
    root: Path,
    fingerprint_value: str,
    total_chunks: int,
    *,
    completed: list[int],
) -> None:
    manifest = {
        "fingerprint": fingerprint_value,
        "total": int(total_chunks),
        "completed": list(completed),
        "done": len(completed),
    }
    path = root / MANIFEST_NAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
