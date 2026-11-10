"""Chunked uploads that can resume after a flaky phone connection."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UPLOAD_ROOT = ROOT / "upload_sessions"
# Few large chunks keep Tailscale/TLS overhead low while still allowing resume.
CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB
MAX_BYTES = 200 * 1024 * 1024
_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def create_session(filename: str, size: int, fingerprint: str = "") -> dict:
    if size < 1 or size > MAX_BYTES:
        raise ValueError("Recording must be from 1 byte to 200 MB.")
    suffix = Path(filename or "audio").suffix.lower()
    allowed = {".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".flac", ".aac", ".aiff", ".aif"}
    if suffix not in allowed:
        suffix = ".audio"
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    upload_id = uuid.uuid4().hex
    folder = UPLOAD_ROOT / upload_id
    folder.mkdir()
    meta = {
        "id": upload_id,
        "filename": Path(filename or f"audio{suffix}").name[:180],
        "suffix": suffix,
        "size": int(size),
        "chunk_size": CHUNK_SIZE,
        "fingerprint": str(fingerprint or "")[:300],
        "created_at": time.time(),
        "received": [],
    }
    _write_meta(folder, meta)
    return status(upload_id)


def status(upload_id: str) -> dict:
    meta = _read_meta(_folder(upload_id))
    received = sorted(int(index) for index in meta.get("received") or [])
    size = int(meta["size"])
    chunk_size = int(meta["chunk_size"])
    total_chunks = (size + chunk_size - 1) // chunk_size
    bytes_received = 0
    for index in received:
        start = index * chunk_size
        end = min(size, start + chunk_size)
        bytes_received += max(0, end - start)
    return {
        "id": meta["id"],
        "filename": meta["filename"],
        "size": size,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "received": received,
        "bytes_received": bytes_received,
        "complete": len(received) >= total_chunks and total_chunks > 0,
        "fingerprint": meta.get("fingerprint") or "",
    }


def save_chunk(upload_id: str, index: int, payload: bytes) -> dict:
    folder = _folder(upload_id)
    meta = _read_meta(folder)
    size = int(meta["size"])
    chunk_size = int(meta["chunk_size"])
    total_chunks = (size + chunk_size - 1) // chunk_size
    if index < 0 or index >= total_chunks:
        raise ValueError("That chunk index is outside the file.")
    expected = min(chunk_size, size - index * chunk_size)
    if len(payload) != expected:
        raise ValueError(
            f"Chunk {index} should be {expected} bytes, got {len(payload)}."
        )
    part = folder / f"{index:06d}.part"
    part.write_bytes(payload)
    received = set(int(value) for value in meta.get("received") or [])
    received.add(index)
    meta["received"] = sorted(received)
    _write_meta(folder, meta)
    return status(upload_id)


def assemble(upload_id: str) -> Path:
    folder = _folder(upload_id)
    meta = _read_meta(folder)
    info = status(upload_id)
    if not info["complete"]:
        missing = [
            index
            for index in range(info["total_chunks"])
            if index not in set(info["received"])
        ]
        raise ValueError(
            f"Upload is incomplete. Missing {len(missing)} chunk(s)."
        )
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=meta["suffix"])
    path = Path(handle.name)
    try:
        for index in range(info["total_chunks"]):
            part = folder / f"{index:06d}.part"
            if not part.is_file():
                raise ValueError(f"Chunk {index} is missing on disk.")
            handle.write(part.read_bytes())
    except Exception:
        handle.close()
        path.unlink(missing_ok=True)
        raise
    handle.close()
    if path.stat().st_size != int(meta["size"]):
        path.unlink(missing_ok=True)
        raise ValueError("Assembled file size did not match the upload.")
    return path


def delete_session(upload_id: str) -> None:
    folder = UPLOAD_ROOT / upload_id
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


def list_sessions() -> list[dict]:
    if not UPLOAD_ROOT.is_dir():
        return []
    items = []
    for folder in UPLOAD_ROOT.iterdir():
        if not folder.is_dir():
            continue
        try:
            items.append(status(folder.name))
        except FileNotFoundError:
            continue
    items.sort(
        key=lambda item: (
            1 if item.get("complete") else 0,
            int(item.get("bytes_received") or 0),
        ),
        reverse=True,
    )
    return items


def find_best_for(
    filename: str,
    size: int,
    fingerprint: str = "",
) -> dict | None:
    """Best session for this file: complete first, then most bytes received.

    Matches by filename+size and/or fingerprint core (name|size), so phone
    re-picks and empty retry sessions never hide a finished upload.
    """
    name = Path(filename or "").name
    size = int(size or 0)
    if size < 1 or not UPLOAD_ROOT.is_dir():
        return None
    needle = str(fingerprint or "").strip()
    best_id = None
    best_score = (-1, -1, -1.0)
    for folder in UPLOAD_ROOT.iterdir():
        if not folder.is_dir():
            continue
        try:
            meta = _read_meta(folder)
        except FileNotFoundError:
            continue
        meta_name = Path(str(meta.get("filename") or "")).name
        meta_size = int(meta.get("size") or 0)
        if meta_size != size:
            continue
        same_file = bool(name) and meta_name == name
        same_fp = bool(needle) and _fingerprint_matches(
            meta.get("fingerprint") or "",
            needle,
        )
        if not same_file and not same_fp:
            continue
        info = status(meta["id"])
        score = (
            1 if info.get("complete") else 0,
            int(info.get("bytes_received") or 0),
            float(meta.get("created_at") or 0),
        )
        if score >= best_score:
            best_score = score
            best_id = meta["id"]
    if best_id is None:
        return None
    return status(best_id)


def prune_weaker_siblings(keep_id: str, filename: str, size: int) -> None:
    """Drop empty/weaker retries of the same file so they cannot win later."""
    name = Path(filename or "").name
    size = int(size or 0)
    if not keep_id or not name or size < 1 or not UPLOAD_ROOT.is_dir():
        return
    try:
        keep = status(keep_id)
    except FileNotFoundError:
        return
    keep_bytes = int(keep.get("bytes_received") or 0)
    for folder in list(UPLOAD_ROOT.iterdir()):
        if not folder.is_dir() or folder.name == keep_id:
            continue
        try:
            meta = _read_meta(folder)
        except FileNotFoundError:
            continue
        if Path(str(meta.get("filename") or "")).name != name:
            continue
        if int(meta.get("size") or 0) != size:
            continue
        try:
            info = status(folder.name)
        except FileNotFoundError:
            continue
        other_bytes = int(info.get("bytes_received") or 0)
        # Never delete a stronger/complete sibling in favor of a weaker keep.
        if other_bytes > keep_bytes:
            continue
        if keep.get("complete") and info.get("complete") and other_bytes == keep_bytes:
            delete_session(folder.name)
            continue
        if other_bytes == 0 or other_bytes < keep_bytes or (
            keep.get("complete") and not info.get("complete")
        ):
            delete_session(folder.name)


def delete_all_for_file(filename: str, size: int) -> None:
    """Remove every staging session for this file (e.g. after it is in the library)."""
    name = Path(filename or "").name
    size = int(size or 0)
    if not name or size < 1 or not UPLOAD_ROOT.is_dir():
        return
    for folder in list(UPLOAD_ROOT.iterdir()):
        if not folder.is_dir():
            continue
        try:
            meta = _read_meta(folder)
        except FileNotFoundError:
            continue
        if Path(str(meta.get("filename") or "")).name != name:
            continue
        if int(meta.get("size") or 0) != size:
            continue
        delete_session(folder.name)


def find_by_fingerprint(fingerprint: str) -> dict | None:
    needle = str(fingerprint or "").strip()
    if not needle:
        return None
    parts = needle.split("|")
    name = parts[0] if parts else ""
    try:
        size = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        size = 0
    return find_best_for(name, size, needle)


def find_by_file(filename: str, size: int) -> dict | None:
    return find_best_for(filename, size, "")


def _fingerprint_matches(stored: str, needle: str) -> bool:
    if stored == needle:
        return True
    # Ignore trailing lastModified so Android re-selects still match.
    return _fingerprint_core(stored) == _fingerprint_core(needle) and bool(
        _fingerprint_core(needle)
    )


def _fingerprint_core(value: str) -> str:
    parts = str(value or "").split("|")
    if len(parts) >= 2:
        return f"{parts[0]}|{parts[1]}"
    return str(value or "").strip()


def _folder(upload_id: str) -> Path:
    if not _ID_RE.match(upload_id or ""):
        raise FileNotFoundError(upload_id)
    folder = UPLOAD_ROOT / upload_id
    if not folder.is_dir():
        raise FileNotFoundError(upload_id)
    return folder


def _write_meta(folder: Path, meta: dict) -> None:
    path = folder / "meta.json"
    path.write_text(json.dumps(meta), encoding="utf-8")


def _read_meta(folder: Path) -> dict:
    path = folder / "meta.json"
    if not path.is_file():
        raise FileNotFoundError(folder.name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FileNotFoundError(folder.name) from exc
