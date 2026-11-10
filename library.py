"""Saved recordings. The transcript is a table the page imports."""

from __future__ import annotations

import csv
import shutil
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIBRARY = ROOT / "library"
TRANSCRIPT_NAME = "transcript.csv"

# Recording facts sit above the turns, in the same file the page imports.
RECORDING_FIELDS = (
    "id",
    "title",
    "created_at",
    "duration",
    "audio",
    "audio_cleaned",
    "transcript_audio",
    "status",
    "source_filename",
    "model",
    "device",
    "language",
    "detected_language",
    "translate_to",
    "num_speakers",
    "diarization_error",
)
TURN_FIELDS = ("speaker", "name", "start", "end", "text", "translation")


def list_recordings(query: str = "") -> list[dict]:
    needle = " ".join(query.lower().split())
    items = []
    if not LIBRARY.is_dir():
        return items
    for folder in LIBRARY.iterdir():
        meta = _read_meta(folder)
        if meta is None:
            continue
        if needle and needle not in _search_text(meta):
            continue
        items.append(_summary(meta))
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items


def get_recording(recording_id: str) -> dict:
    meta = _read_meta(_folder(recording_id))
    if meta is None:
        raise FileNotFoundError(recording_id)
    return _detail(meta)


def audio_path(recording_id: str, source: str = "original") -> Path:
    folder = _folder(recording_id)
    meta = _read_meta(folder)
    if meta is None:
        raise FileNotFoundError(recording_id)
    kind = _normalize_audio_source(source)
    if kind == "cleaned":
        name = meta.get("cleaned_audio_name") or ""
        if not name:
            raise FileNotFoundError(recording_id)
        path = folder / name
    else:
        path = folder / meta["audio_name"]
    if not path.is_file():
        raise FileNotFoundError(recording_id)
    return path


def save_cleaned_audio(recording_id: str, source: Path) -> dict:
    folder = _folder(recording_id)
    meta = _read_meta(folder)
    if meta is None:
        raise FileNotFoundError(recording_id)
    suffix = source.suffix.lower() or ".wav"
    if suffix not in {".wav", ".webm", ".m4a", ".mp3", ".ogg", ".flac"}:
        suffix = ".wav"
    audio_name = f"audio_cleaned{suffix}"
    previous = meta.get("cleaned_audio_name") or ""
    target = folder / audio_name
    shutil.move(str(source), target)
    if previous and previous != audio_name:
        (folder / previous).unlink(missing_ok=True)
    meta["cleaned_audio_name"] = audio_name
    _write_transcript(folder, meta)
    return _detail(meta)


def delete_cleaned_audio(recording_id: str) -> dict:
    folder = _folder(recording_id)
    meta = _read_meta(folder)
    if meta is None:
        raise FileNotFoundError(recording_id)
    name = meta.get("cleaned_audio_name") or ""
    if name:
        (folder / name).unlink(missing_ok=True)
    meta["cleaned_audio_name"] = ""
    if meta.get("transcript_audio") == "cleaned":
        meta["transcript_audio"] = "original"
    _write_transcript(folder, meta)
    return _detail(meta)


def set_transcript_audio(recording_id: str, source: str) -> dict:
    folder = _folder(recording_id)
    meta = _read_meta(folder)
    if meta is None:
        raise FileNotFoundError(recording_id)
    kind = _normalize_audio_source(source)
    if kind == "cleaned" and not meta.get("cleaned_audio_name"):
        raise ValueError("Save a cleaned audio file before choosing it.")
    meta["transcript_audio"] = kind
    _write_transcript(folder, meta)
    return _detail(meta)


def _normalize_audio_source(source: str) -> str:
    kind = str(source or "original").strip().lower()
    if kind in ("", "original", "raw"):
        return "original"
    if kind in ("cleaned", "clean"):
        return "cleaned"
    raise ValueError("Choose original or cleaned audio.")


def save_recording(source: Path, result: dict) -> dict:
    LIBRARY.mkdir(parents=True, exist_ok=True)
    recording_id = uuid.uuid4().hex
    folder = LIBRARY / recording_id
    folder.mkdir()
    audio_name = f"audio{source.suffix.lower()}"
    shutil.move(str(source), folder / audio_name)
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    meta = {
        "id": recording_id,
        "title": _default_title(result.get("turns") or [], created_at),
        "created_at": created_at,
        "duration": float(result.get("duration") or 0),
        "audio_name": audio_name,
        "cleaned_audio_name": "",
        "transcript_audio": "original",
        "status": "ready",
        "source_filename": "",
        "model": result.get("model") or "",
        "device": result.get("device") or "",
        "language": result.get("language") or "en",
        "detected_language": result.get("detected_language") or result.get("language") or "en",
        "translate_to": result.get("translate_to") or "",
        "num_speakers": int(result.get("num_speakers") or -1),
        "turns": result.get("turns") or [],
        "speaker_names": {},
        "diarization_error": result.get("diarization_error"),
    }
    _write_transcript(folder, meta)
    return _detail(meta)


def save_pending_recording(
    source: Path,
    *,
    filename: str = "",
    language: str = "en",
    translate_to: str = "",
    num_speakers: int = -1,
    duration: float = 0.0,
) -> dict:
    """Keep the audio in the library without running Whisper yet."""
    LIBRARY.mkdir(parents=True, exist_ok=True)
    recording_id = uuid.uuid4().hex
    folder = LIBRARY / recording_id
    folder.mkdir()
    suffix = source.suffix.lower() or Path(filename or "audio").suffix.lower() or ".audio"
    audio_name = f"audio{suffix}"
    shutil.move(str(source), folder / audio_name)
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    stem = Path(filename or "audio").stem.strip() or ""
    title = " ".join(stem.split())[:80] if stem else _default_title([], created_at)
    if not title:
        title = _default_title([], created_at)
    meta = {
        "id": recording_id,
        "title": title,
        "created_at": created_at,
        "duration": float(duration or 0),
        "audio_name": audio_name,
        "cleaned_audio_name": "",
        "transcript_audio": "original",
        "status": "pending",
        "source_filename": Path(filename or "").name[:180],
        "model": "",
        "device": "",
        "language": language or "en",
        "detected_language": language or "en",
        "translate_to": translate_to or "",
        "num_speakers": int(num_speakers),
        "turns": [],
        "speaker_names": {},
        "diarization_error": None,
    }
    _write_transcript(folder, meta)
    return _detail(meta)


def find_by_upload(filename: str, size: int) -> dict | None:
    """Find a library item that already came from this phone file (name + bytes)."""
    name = Path(filename or "").name
    size = int(size or 0)
    if not name or size < 1 or not LIBRARY.is_dir():
        return None
    stem = Path(name).stem
    best = None
    best_pending = False
    for folder in LIBRARY.iterdir():
        if not folder.is_dir():
            continue
        meta = _read_meta(folder)
        if meta is None:
            continue
        audio_name = meta.get("audio_name") or ""
        audio_path = folder / audio_name if audio_name else None
        if not audio_path or not audio_path.is_file():
            continue
        if audio_path.stat().st_size != size:
            continue
        source = str(meta.get("source_filename") or "")
        title = str(meta.get("title") or "")
        if source != name and title != stem and title != name:
            continue
        pending = _normalize_status(meta.get("status")) == "pending"
        if best is None or (pending and not best_pending):
            best = meta
            best_pending = pending
    if best is None:
        return None
    return _detail(best)


def update_recording(recording_id: str, title: str | None, speaker_names: dict | None) -> dict:
    folder = _folder(recording_id)
    meta = _read_meta(folder)
    if meta is None:
        raise FileNotFoundError(recording_id)
    if title is not None:
        cleaned = " ".join(title.split())
        if not cleaned or len(cleaned) > 80:
            raise ValueError("Title must be from 1 to 80 characters.")
        meta["title"] = cleaned
    if speaker_names is not None:
        meta["speaker_names"] = _clean_names(speaker_names)
    _write_transcript(folder, meta)
    return _detail(meta)


def delete_recording(recording_id: str) -> None:
    folder = _folder(recording_id)
    if not folder.is_dir():
        raise FileNotFoundError(recording_id)
    shutil.rmtree(folder)


def _folder(recording_id: str) -> Path:
    if len(recording_id) != 32 or any(char not in "0123456789abcdef" for char in recording_id):
        raise FileNotFoundError(recording_id)
    return LIBRARY / recording_id


def _read_meta(folder: Path) -> dict | None:
    transcript = folder / TRANSCRIPT_NAME
    if not transcript.is_file():
        return None
    return _read_transcript(transcript)


def _write_transcript(folder: Path, meta: dict) -> None:
    path = folder / TRANSCRIPT_NAME
    names = meta.get("speaker_names") or {}
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["[recording]"])
        writer.writerow(["field", "value"])
        for field in RECORDING_FIELDS:
            writer.writerow([field, _recording_value(meta, field)])
        writer.writerow([])
        writer.writerow(["[turns]"])
        writer.writerow(TURN_FIELDS)
        for turn in meta.get("turns") or []:
            speaker = turn.get("speaker")
            name = names.get(str(speaker)) or turn.get("name") or ""
            writer.writerow([
                speaker,
                name,
                turn.get("start", 0),
                turn.get("end", 0),
                turn.get("text") or "",
                turn.get("translation") or "",
            ])


def _recording_value(meta: dict, field: str) -> str:
    if field == "audio":
        return str(meta.get("audio_name") or "")
    if field == "audio_cleaned":
        return str(meta.get("cleaned_audio_name") or "")
    if field == "transcript_audio":
        return str(meta.get("transcript_audio") or "original")
    if field == "diarization_error":
        error = meta.get("diarization_error")
        return "" if error is None else str(error)
    value = meta.get(field)
    if value is None:
        return ""
    return str(value)


def _read_transcript(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
    except OSError:
        return None
    section = ""
    recording: dict[str, str] = {}
    turns = []
    header: list[str] | None = None
    for row in rows:
        if not row or not any(cell.strip() for cell in row):
            header = None
            continue
        marker = row[0].strip()
        if marker in ("[recording]", "[turns]"):
            section = marker
            header = None
            continue
        if header is None:
            header = row
            continue
        if section == "[recording]" and len(row) >= 2:
            recording[row[0]] = row[1]
            continue
        if section == "[turns]":
            turns.append({
                header[index]: row[index] if index < len(row) else ""
                for index in range(len(header))
            })
    if "id" not in recording:
        return None
    return _meta_from_table(recording, turns)


def _meta_from_table(recording: dict[str, str], turns: list[dict]) -> dict:
    names: dict[str, str] = {}
    normalized = []
    for turn in turns:
        try:
            speaker = int(float(turn.get("speaker") or 0))
            start = float(turn.get("start") or 0)
            end = float(turn.get("end") or 0)
        except ValueError:
            continue
        name = " ".join(str(turn.get("name") or "").split())
        if name:
            names[str(speaker)] = name
        normalized.append({
            "speaker": speaker,
            "start": start,
            "end": end,
            "text": turn.get("text") or "",
            "translation": turn.get("translation") or "",
        })
    error = recording.get("diarization_error") or ""
    try:
        duration = float(recording.get("duration") or 0)
    except ValueError:
        duration = 0.0
    try:
        num_speakers = int(float(recording.get("num_speakers") or -1))
    except ValueError:
        num_speakers = -1
    return {
        "id": recording["id"],
        "title": recording.get("title") or "",
        "created_at": recording.get("created_at") or "",
        "duration": duration,
        "audio_name": recording.get("audio") or "",
        "cleaned_audio_name": recording.get("audio_cleaned") or "",
        "transcript_audio": (
            "cleaned"
            if (recording.get("transcript_audio") or "").strip().lower() == "cleaned"
            and (recording.get("audio_cleaned") or "")
            else "original"
        ),
        "status": _normalize_status(recording.get("status")),
        "source_filename": recording.get("source_filename") or "",
        "model": recording.get("model") or "",
        "device": recording.get("device") or "",
        "language": recording.get("language") or "en",
        "detected_language": recording.get("detected_language") or recording.get("language") or "en",
        "translate_to": recording.get("translate_to") or "",
        "num_speakers": num_speakers,
        "turns": normalized,
        "speaker_names": names,
        "diarization_error": error or None,
    }


def _normalize_status(value) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned == "pending":
        return "pending"
    return "ready"


def replace_transcript(
    recording_id: str,
    turns: list[dict],
    language: str,
    detected_language: str,
    translate_to: str,
    model: str,
    device: str,
    diarization_error,
    duration: float | None = None,
) -> dict:
    folder = _folder(recording_id)
    meta = _read_meta(folder)
    if meta is None:
        raise FileNotFoundError(recording_id)
    meta["turns"] = turns
    meta["language"] = language
    meta["detected_language"] = detected_language
    meta["translate_to"] = translate_to
    if model:
        meta["model"] = model
    if device:
        meta["device"] = device
    meta["diarization_error"] = diarization_error
    if duration is not None:
        meta["duration"] = float(duration)
    meta["status"] = "ready"
    _write_transcript(folder, meta)
    return _detail(meta)


def _reading(turn: dict) -> str:
    translation = " ".join(str(turn.get("translation") or "").split())
    if translation:
        return translation
    return " ".join(str(turn.get("text") or "").split())


def _default_title(turns: list[dict], created_at: str) -> str:
    if turns:
        text = _reading(turns[0])
        if text:
            if len(text) <= 60:
                return text
            return text[:57].rstrip() + "..."
    try:
        moment = datetime.fromisoformat(created_at)
    except ValueError:
        moment = datetime.now().astimezone()
    return moment.strftime("Recording %d %b %H:%M")


def _summary(meta: dict) -> dict:
    turns = meta.get("turns") or []
    preview = ""
    if turns:
        preview = _reading(turns[0])
        if len(preview) > 140:
            preview = preview[:137].rstrip() + "..."
    speakers = {turn.get("speaker") for turn in turns}
    status = _normalize_status(meta.get("status"))
    return {
        "id": meta["id"],
        "title": meta.get("title") or "Recording",
        "created_at": meta.get("created_at") or "",
        "duration": float(meta.get("duration") or 0),
        "preview": preview,
        "speaker_count": len(speakers),
        "status": status,
        "pending": status == "pending",
        "language": meta.get("language") or "en",
        "detected_language": meta.get("detected_language") or meta.get("language") or "en",
        "translate_to": meta.get("translate_to") or "",
        "num_speakers": int(meta.get("num_speakers") or -1),
    }


def _detail(meta: dict) -> dict:
    detail = _summary(meta)
    recording_id = meta["id"]
    has_cleaned = bool(meta.get("cleaned_audio_name"))
    transcript_audio = meta.get("transcript_audio") or "original"
    if transcript_audio == "cleaned" and not has_cleaned:
        transcript_audio = "original"
    detail.update(
        {
            "model": meta.get("model") or "",
            "device": meta.get("device") or "",
            "turns": meta.get("turns") or [],
            "speaker_names": meta.get("speaker_names") or {},
            "diarization_error": meta.get("diarization_error"),
            "has_cleaned": has_cleaned,
            "transcript_audio": transcript_audio,
            "audio_url": f"/api/recordings/{recording_id}/audio?source=original",
            "cleaned_audio_url": (
                f"/api/recordings/{recording_id}/audio?source=cleaned" if has_cleaned else ""
            ),
        }
    )
    return detail


def _search_text(meta: dict) -> str:
    parts = [str(meta.get("title") or "")]
    for turn in meta.get("turns") or []:
        parts.append(str(turn.get("text") or ""))
        parts.append(str(turn.get("translation") or ""))
    return " ".join(parts).lower()


def _clean_names(raw: dict) -> dict[str, str]:
    if not isinstance(raw, dict) or len(raw) > 12:
        raise ValueError("Speaker names were not accepted.")
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        speaker = str(key)
        if not speaker.isdigit() or int(speaker) > 8:
            raise ValueError("Speaker names were not accepted.")
        name = " ".join(str(value).split())
        if not name or len(name) > 40:
            raise ValueError("Each speaker name must be from 1 to 40 characters.")
        cleaned[speaker] = name
    return cleaned
