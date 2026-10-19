"""Local page for recording a discussion and reading who said what."""

from __future__ import annotations

import argparse
import asyncio
import socket
import subprocess
import tempfile
import traceback
from pathlib import Path
from typing import Dict, Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import activity
import chunked_uploads
import library
import pipeline
import translator
from languages import (
    MULTILINGUAL_MODEL,
    SPOKEN_LANGUAGES,
    TRANSLATE_LANGUAGES,
    model_for_language,
    normalize_spoken,
    normalize_translation,
)
from local_cert import ensure_cert
from settings_store import (
    COMPUTE_TYPES,
    DEVICES,
    PRESET_MODELS,
    load_settings,
    save_settings,
)

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_BYTES = 200 * 1024 * 1024

app = FastAPI(title="auto ASR")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class SettingsIn(BaseModel):
    model: str
    device: str = "auto"
    compute_type: str = "default"
    cpu_threads: int = 4
    cluster_threshold: float = 0.5
    language: str = "en"
    translate_to: str = "fr"


class LanguagesIn(BaseModel):
    language: str
    translate_to: str


class RetranscribeIn(BaseModel):
    language: str
    translate_to: str = ""
    audio_source: str = "original"


class TranscriptAudioIn(BaseModel):
    audio_source: str = "original"


class InstallIn(BaseModel):
    language: str = "en"
    translate_to: str = ""
    model: str = ""


class UploadSessionIn(BaseModel):
    filename: str = "audio.webm"
    size: int
    fingerprint: str = ""


class RecordingPatch(BaseModel):
    title: Optional[str] = None
    speaker_names: Optional[Dict[str, str]] = None


AUDIO_TYPES = {
    ".webm": "audio/webm",
    ".mp4": "audio/mp4",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/activity")
def get_activity() -> dict:
    return activity.snapshot()


@app.post("/api/install")
def install_models(body: InstallIn) -> dict:
    """Download the one speech model the next recording will use (internet required)."""
    try:
        if not pipeline.internet_available():
            raise RuntimeError(
                "This computer is offline. Connect to the internet to download models."
            )
        language = normalize_spoken(body.language)
        settings = load_settings()
        model = body.model.strip() or settings["model"]
        if not model or len(model) > 300:
            raise ValueError("Enter a model name or a path to a local model folder.")
        speech = model_for_language(model, language)
        if pipeline.speech_ready(speech):
            return get_downloads()
        if not pipeline.speech_can_download(speech):
            raise RuntimeError(
                f"{speech} is not on this computer, and it cannot be downloaded from here."
            )
        pipeline.ensure_speech_model(speech)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        activity.clear()
    return get_downloads()


@app.get("/api/downloads")
def get_downloads() -> dict:
    settings = load_settings()
    spoken = settings.get("language") or "en"
    active = model_for_language(settings["model"], spoken)
    names = list(dict.fromkeys([
        *PRESET_MODELS,
        *MULTILINGUAL_MODEL.values(),
        settings["model"],
        active,
    ]))
    names = [name for name in names if name]
    online = pipeline.internet_available(timeout=1.5)
    return {
        "speech": {name: pipeline.speech_ready(name) for name in names},
        "downloadable": [name for name in names if pipeline.speech_can_download(name)],
        "speakers": pipeline.speakers_ready(),
        "pairs": translator.installed_pairs(),
        "multilingual": MULTILINGUAL_MODEL,
        "online": online,
    }


@app.get("/api/settings")
def get_settings() -> dict:
    settings = load_settings()
    resolved_device, resolved_compute = pipeline.resolve_device(settings)
    return {
        "settings": settings,
        "resolved": {
            "device": resolved_device,
            "compute_type": resolved_compute,
            "cuda": pipeline.cuda_available(),
            "mlx": pipeline.mlx_available(),
        },
        "presets": PRESET_MODELS,
        "devices": DEVICES,
        "compute_types": COMPUTE_TYPES,
        "spoken_languages": [{"code": code, "name": name} for code, name in SPOKEN_LANGUAGES],
        "translate_languages": [{"code": code, "name": name} for code, name in TRANSLATE_LANGUAGES],
    }


@app.put("/api/settings")
def put_settings(body: SettingsIn) -> dict:
    try:
        saved = save_settings(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pipeline.drop_cached_model()
    resolved_device, resolved_compute = pipeline.resolve_device(saved)
    return {
        **saved,
        "resolved": {
            "device": resolved_device,
            "compute_type": resolved_compute,
            "cuda": pipeline.cuda_available(),
            "mlx": pipeline.mlx_available(),
        },
    }


@app.get("/api/recordings")
def get_recordings(q: str = "") -> dict:
    return {"recordings": library.list_recordings(q)}


@app.get("/api/recordings/{recording_id}")
def get_recording(recording_id: str) -> dict:
    try:
        return library.get_recording(recording_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recording not found.") from exc


@app.get("/api/recordings/{recording_id}/audio")
def get_recording_audio(recording_id: str, source: str = "original") -> FileResponse:
    try:
        path = library.audio_path(recording_id, source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recording not found.") from exc
    media_type = AUDIO_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@app.put("/api/recordings/{recording_id}/cleaned")
async def put_cleaned_audio(
    recording_id: str,
    audio: UploadFile = File(...),
) -> dict:
    path = await _save_upload(audio)
    try:
        return library.save_cleaned_audio(recording_id, path)
    except FileNotFoundError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="Recording not found.") from exc
    except Exception:
        path.unlink(missing_ok=True)
        raise


@app.delete("/api/recordings/{recording_id}/cleaned")
def remove_cleaned_audio(recording_id: str) -> dict:
    try:
        return library.delete_cleaned_audio(recording_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recording not found.") from exc


@app.put("/api/recordings/{recording_id}/transcript-audio")
def put_transcript_audio(recording_id: str, body: TranscriptAudioIn) -> dict:
    try:
        return library.set_transcript_audio(recording_id, body.audio_source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recording not found.") from exc


@app.post("/api/recordings/{recording_id}/transcribe")
def retranscribe_recording(recording_id: str, body: RetranscribeIn) -> dict:
    try:
        language = normalize_spoken(body.language)
        translate_to = normalize_translation(body.translate_to)
        audio_source = body.audio_source
        current = library.get_recording(recording_id)
        path = library.audio_path(recording_id, audio_source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recording not found.") from exc
    try:
        activity.begin("transcribe", "Transcribing")
        settings = dict(load_settings())
        settings["language"] = language
        result = pipeline.transcribe_file(
            path, settings, int(current.get("num_speakers") or -1)
        )
        activity.begin("translate", "Translating")
        turns = translator.fill_translations(
            result["turns"],
            result["detected_language"],
            translate_to,
        )
        library.replace_transcript(
            recording_id,
            turns,
            language,
            result["detected_language"],
            translate_to,
            result["model"],
            result["device"],
            result["diarization_error"],
            result["duration"],
        )
        return library.set_transcript_audio(recording_id, audio_source)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        activity.clear()


@app.patch("/api/recordings/{recording_id}")
def patch_recording(recording_id: str, body: RecordingPatch) -> dict:
    try:
        return library.update_recording(recording_id, body.title, body.speaker_names)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recording not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/recordings/{recording_id}/languages")
def update_languages(recording_id: str, body: LanguagesIn) -> dict:
    try:
        language = normalize_spoken(body.language)
        translate_to = normalize_translation(body.translate_to)
        current = library.get_recording(recording_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recording not found.") from exc
    try:
        if language != current.get("language"):
            activity.begin("transcribe", "Transcribing")
            path = library.audio_path(recording_id)
            settings = dict(load_settings())
            settings["language"] = language
            result = pipeline.transcribe_file(path, settings, int(current.get("num_speakers") or -1))
            activity.begin("translate", "Translating")
            turns = translator.fill_translations(
                result["turns"],
                result["detected_language"],
                translate_to,
            )
            return library.replace_transcript(
                recording_id,
                turns,
                language,
                result["detected_language"],
                translate_to,
                result["model"],
                result["device"],
                result["diarization_error"],
                result["duration"],
            )
        activity.begin("translate", "Translating")
        source = current.get("detected_language") or current.get("language") or "en"
        turns = translator.fill_translations(current["turns"], source, translate_to)
        return library.replace_transcript(
            recording_id,
            turns,
            current.get("language") or language,
            source,
            translate_to,
            current.get("model") or "",
            current.get("device") or "",
            current.get("diarization_error"),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        activity.clear()


@app.delete("/api/recordings/{recording_id}")
def remove_recording(recording_id: str) -> dict:
    try:
        library.delete_recording(recording_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recording not found.") from exc
    return {"ok": True}


@app.post("/api/uploads")
def create_upload(body: UploadSessionIn) -> dict:
    try:
        # Already saved into the library from a previous upload of this file.
        existing_recording = library.find_by_upload(body.filename, body.size)
        if existing_recording is not None:
            chunked_uploads.delete_all_for_file(body.filename, body.size)
            return {
                "already_in_library": True,
                "complete": True,
                "recording": existing_recording,
                "id": "",
                "filename": body.filename,
                "size": body.size,
                "chunk_size": chunked_uploads.CHUNK_SIZE,
                "total_chunks": 0,
                "received": [],
                "bytes_received": body.size,
            }

        best = chunked_uploads.find_best_for(
            body.filename,
            body.size,
            body.fingerprint,
        )
        if best and best["size"] == body.size:
            chunked_uploads.prune_weaker_siblings(
                best["id"],
                body.filename,
                body.size,
            )
            return best
        return chunked_uploads.create_session(body.filename, body.size, body.fingerprint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/uploads/pending")
def list_pending_uploads() -> dict:
    """Complete or partial uploads still sitting in staging (not in the library yet)."""
    items = []
    for item in chunked_uploads.list_sessions():
        if int(item.get("bytes_received") or 0) <= 0:
            continue
        items.append(item)
    return {"uploads": items}


@app.delete("/api/uploads/{upload_id}")
def cancel_upload(upload_id: str) -> dict:
    try:
        chunked_uploads.status(upload_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload not found.") from exc
    chunked_uploads.delete_session(upload_id)
    return {"ok": True}


@app.get("/api/uploads/{upload_id}")
def get_upload(upload_id: str) -> dict:
    try:
        return chunked_uploads.status(upload_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload not found.") from exc


@app.put("/api/uploads/{upload_id}/chunks/{index}")
async def put_upload_chunk(upload_id: str, index: int, request: Request) -> dict:
    payload = await request.body()
    if len(payload) > chunked_uploads.CHUNK_SIZE:
        raise HTTPException(status_code=413, detail="Chunk is too large.")
    try:
        return chunked_uploads.save_chunk(upload_id, index, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/uploads/{upload_id}/save")
async def save_upload(
    upload_id: str,
    num_speakers: str = Form("auto"),
) -> dict:
    """Finish a chunked upload into the library without running Whisper yet."""
    try:
        speaker_count = _parse_speakers(num_speakers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        info = chunked_uploads.status(upload_id)
        path = await asyncio.to_thread(chunked_uploads.assemble, upload_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        settings = load_settings()
        saved = await asyncio.to_thread(
            library.save_pending_recording,
            path,
            filename=info.get("filename") or path.name,
            language=settings.get("language") or "en",
            translate_to=settings.get("translate_to") or "",
            num_speakers=speaker_count,
        )
        chunked_uploads.prune_weaker_siblings(
            upload_id,
            info.get("filename") or "",
            int(info.get("size") or 0),
        )
        chunked_uploads.delete_session(upload_id)
        chunked_uploads.delete_all_for_file(
            info.get("filename") or "",
            int(info.get("size") or 0),
        )
        return saved
    except Exception as exc:
        path.unlink(missing_ok=True)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/uploads/{upload_id}/transcribe")
async def transcribe_upload(
    upload_id: str,
    num_speakers: str = Form("auto"),
) -> dict:
    """Legacy: save then transcribe in one step. Prefer /save + /recordings/.../transcribe."""
    try:
        speaker_count = _parse_speakers(num_speakers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        settings = load_settings()
        info = chunked_uploads.status(upload_id)
        path = await asyncio.to_thread(chunked_uploads.assemble, upload_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        saved = await asyncio.to_thread(
            library.save_pending_recording,
            path,
            filename=info.get("filename") or path.name,
            language=settings.get("language") or "en",
            translate_to=settings.get("translate_to") or "",
            num_speakers=speaker_count,
        )
        chunked_uploads.delete_session(upload_id)
        return await asyncio.to_thread(
            _retranscribe_recording_id,
            saved["id"],
            settings.get("language") or "en",
            settings.get("translate_to") or "",
            "original",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/recordings")
async def create_recording(
    audio: UploadFile = File(...),
    num_speakers: str = Form("auto"),
) -> dict:
    """Save an uploaded file into the library without transcribing yet."""
    try:
        speaker_count = _parse_speakers(num_speakers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    path = await _save_upload(audio)
    try:
        settings = load_settings()
        return await asyncio.to_thread(
            library.save_pending_recording,
            path,
            filename=audio.filename or path.name,
            language=settings.get("language") or "en",
            translate_to=settings.get("translate_to") or "",
            num_speakers=speaker_count,
        )
    except Exception as exc:
        path.unlink(missing_ok=True)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    num_speakers: str = Form("auto"),
) -> dict:
    """Legacy one-shot upload+transcribe. Prefer POST /api/recordings then /transcribe."""
    try:
        speaker_count = _parse_speakers(num_speakers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    path = await _save_upload(audio)
    try:
        return await asyncio.to_thread(
            _transcribe_path_to_library,
            path,
            speaker_count,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _retranscribe_recording_id(
    recording_id: str,
    language: str,
    translate_to: str,
    audio_source: str,
) -> dict:
    current = library.get_recording(recording_id)
    path = library.audio_path(recording_id, audio_source)
    activity.begin("transcribe", "Transcribing")
    try:
        settings = dict(load_settings())
        settings["language"] = language
        result = pipeline.transcribe_file(
            path, settings, int(current.get("num_speakers") or -1)
        )
        activity.begin("translate", "Translating")
        turns = translator.fill_translations(
            result["turns"],
            result["detected_language"],
            translate_to,
        )
        library.replace_transcript(
            recording_id,
            turns,
            language,
            result["detected_language"],
            translate_to,
            result["model"],
            result["device"],
            result["diarization_error"],
            result["duration"],
        )
        return library.set_transcript_audio(recording_id, audio_source)
    finally:
        activity.clear()


def _transcribe_path_to_library(
    path: Path,
    speaker_count: int,
    delete_upload_id: str | None = None,
) -> dict:
    activity.begin("transcribe", "Transcribing")
    try:
        settings = load_settings()
        result = pipeline.transcribe_file(path, settings, speaker_count)
        result["translate_to"] = settings["translate_to"]
        result["num_speakers"] = speaker_count
        activity.begin("translate", "Translating")
        result["turns"] = translator.fill_translations(
            result["turns"],
            result["detected_language"],
            settings["translate_to"],
        )
        saved = library.save_recording(path, result)
        if delete_upload_id:
            chunked_uploads.delete_session(delete_upload_id)
        return saved
    finally:
        activity.clear()
        path.unlink(missing_ok=True)


def _parse_speakers(value: str) -> int:
    cleaned = value.strip().lower()
    if cleaned in ("", "auto"):
        return -1
    try:
        count = int(cleaned)
    except ValueError as exc:
        raise ValueError("Speaker count must be auto or a number.") from exc
    if count < 1 or count > 8:
        raise ValueError("Speaker count must be auto or from 1 to 8.")
    return count


async def _save_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "audio").suffix.lower()
    allowed = {".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".flac", ".aac", ".aiff", ".aif"}
    if suffix not in allowed:
        suffix = ".audio"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    path = Path(handle.name)
    total = 0
    try:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BYTES:
                raise HTTPException(status_code=413, detail="Recording is larger than 200 MB.")
            handle.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="The recording was empty.")
    except Exception:
        handle.close()
        path.unlink(missing_ok=True)
        raise
    handle.close()
    return path


def local_ips() -> list[str]:
    found = set()
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("192.0.2.1", 1))
        found.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except socket.gaierror:
        pass
    return sorted(ip for ip in found if ip and not ip.startswith("127."))


def tailscale_ip() -> str:
    try:
        completed = subprocess.run(
            ["tailscale", "ip", "-4"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""


def print_urls(scheme: str, port: int) -> None:
    print(f"This computer: {scheme}://127.0.0.1:{port}", flush=True)
    for ip in local_ips():
        print(f"Phone on Wi-Fi: {scheme}://{ip}:{port}", flush=True)
    tailnet = tailscale_ip()
    if tailnet:
        print(f"Phone via Tailscale: {scheme}://{tailnet}:{port}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run auto ASR on this computer.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--https", action="store_true")
    args = parser.parse_args()
    ssl_cert = None
    ssl_key = None
    scheme = "http"
    if args.https:
        cert, key = ensure_cert(local_ips())
        ssl_cert = str(cert)
        ssl_key = str(key)
        scheme = "https"
        if args.port == 8000:
            args.port = 8443
    print_urls(scheme, args.port)
    if args.https:
        print("On a phone, trust this computer's certificate once so the mic can start.")
        print(f"Certificate: {ssl_cert}")
    uvicorn.run(app, host=args.host, port=args.port, ssl_certfile=ssl_cert, ssl_keyfile=ssl_key)


if __name__ == "__main__":
    main()
