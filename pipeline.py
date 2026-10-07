"""English transcription plus speaker labels, entirely on this computer."""

from __future__ import annotations

import os
import platform
import tarfile
import threading
import time
import urllib.request
from fnmatch import fnmatch
from pathlib import Path

import av
import ctranslate2
import numpy as np
import sherpa_onnx
from faster_whisper import WhisperModel
from faster_whisper.utils import _MODELS
from huggingface_hub import HfApi
from huggingface_hub import constants as hf_constants
from huggingface_hub import snapshot_download, try_to_load_from_cache
from tqdm.auto import tqdm

import activity
from alignment import SpeakerSpan, TimedText, assign_speakers
from languages import model_for_language
from settings_store import load_settings


def _load_project_env(path: Path) -> None:
    """Read KEY=VALUE lines into the process. Existing variables stay as they are."""
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _hf_token() -> str | None:
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


ROOT = Path(__file__).resolve().parent
_load_project_env(ROOT / ".env")
MODELS = ROOT / "models"
WHISPER_DIR = MODELS / "whisper"
SEGMENTATION_DIR = MODELS / "sherpa-onnx-pyannote-segmentation-3-0"
SEGMENTATION_MODEL = SEGMENTATION_DIR / "model.onnx"
EMBEDDING_MODEL = MODELS / "nemo_en_titanet_small.onnx"

SEGMENTATION_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
EMBEDDING_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/nemo_en_titanet_small.onnx"
)

_whisper_lock = threading.Lock()
_whisper: WhisperModel | None = None
_whisper_key: tuple | None = None
_diarizer_lock = threading.Lock()
_diarizers: dict[tuple, sherpa_onnx.OfflineSpeakerDiarization] = {}

_WHISPER_FILES = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]

# Apple Silicon uses MLX weights (Metal). Same logical Whisper sizes as faster-whisper.
_MLX_REPOS = {
    "tiny.en": "mlx-community/whisper-tiny.en-mlx",
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base.en": "mlx-community/whisper-base.en-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small.en": "mlx-community/whisper-small.en-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium.en": "mlx-community/whisper-medium.en-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "distil-large-v3": "mlx-community/distil-whisper-large-v3",
}


class _HubProgress(tqdm):
    """Report Hugging Face's byte total. File-count bars use a different unit."""

    def __init__(self, *args, **kwargs):
        # huggingface_hub passes name= for its own bar toggles; stock tqdm rejects it.
        kwargs.pop("name", None)
        self._bytes = kwargs.get("unit") == "B"
        super().__init__(*args, **kwargs)
        if self._bytes:
            self._report()

    def update(self, n=1):
        shown = super().update(n)
        if self._bytes:
            self._report()
        return shown

    def refresh(self, *args, **kwargs):
        shown = super().refresh(*args, **kwargs)
        if self._bytes:
            self._report()
        return shown

    def _report(self) -> None:
        activity.note_at_least(int(self.n or 0), int(self.total or 0))


class _DiskProgress:
    """Poll cache folder size when Hugging Face stops sending tqdm updates."""

    def __init__(self, root: Path, interval: float = 0.5):
        self._root = root
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="speech-download-disk",
            daemon=True,
        )

    def __enter__(self):
        self._tick()
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._stop.set()
        self._thread.join(timeout=2)
        self._tick()
        return False

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._tick()

    def _tick(self) -> None:
        try:
            activity.note_at_least(_directory_bytes(self._root), 0)
        except Exception:
            # A single failed stat must not abort the download.
            pass


def _hub_repo_cache_dir(repo: str) -> Path:
    return WHISPER_DIR / f"models--{repo.replace('/', '--')}"


def _directory_bytes(root: Path) -> int:
    if not root.is_dir():
        return 0
    total = 0
    try:
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def speech_cache_bytes(name: str) -> int:
    """Bytes already on disk for a preset (or local folder) speech model."""
    folder = Path(name)
    if folder.is_dir():
        return _directory_bytes(folder)
    repo = _MODELS.get(name)
    if not repo:
        return 0
    return _directory_bytes(_hub_repo_cache_dir(repo))


def _speech_download_total(repo: str) -> int:
    """Full byte size of the files this app will download for a speech repo."""
    try:
        info = HfApi(token=_hf_token()).repo_info(repo, files_metadata=True)
    except Exception:
        return 0
    total = 0
    for sibling in info.siblings or []:
        name = sibling.rfilename
        if not any(fnmatch(name, pattern) for pattern in _WHISPER_FILES):
            continue
        size = getattr(sibling, "size", None)
        if size:
            total += int(size)
    return total


def drop_cached_model() -> None:
    global _whisper, _whisper_key
    with _whisper_lock:
        _whisper = None
        _whisper_key = None


_online_cache = {"checked_at": 0.0, "value": False}


def internet_available(timeout: float = 2.0) -> bool:
    """True when model downloads from Hugging Face are likely to work."""
    now = time.time()
    if now - float(_online_cache["checked_at"]) < 20:
        return bool(_online_cache["value"])
    probes = (
        "https://huggingface.co",
        "https://cdn-lfs.huggingface.co",
    )
    value = False
    for url in probes:
        try:
            urllib.request.urlopen(url, timeout=timeout)  # noqa: S310
            value = True
            break
        except Exception:
            continue
    _online_cache["checked_at"] = now
    _online_cache["value"] = value
    return value


def cuda_available() -> bool:
    try:
        return int(ctranslate2.get_cuda_device_count() or 0) > 0
    except Exception:
        return False


def mlx_available() -> bool:
    """Metal GPU path via mlx-whisper (Apple Silicon only)."""
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return False
    try:
        import mlx_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def mlx_repo_for(name: str) -> str | None:
    cleaned = str(name or "").strip()
    if cleaned in _MLX_REPOS:
        return _MLX_REPOS[cleaned]
    # Custom folder paths stay on faster-whisper/CPU.
    if "/" in cleaned or cleaned.startswith("."):
        return None
    return f"mlx-community/whisper-{cleaned}-mlx"


def resolve_device(settings: dict) -> tuple[str, str]:
    """Pick the fastest ready backend for this machine.

    Order: NVIDIA CUDA → Apple MLX when weights are present → CPU with
    already-downloaded faster-whisper weights → Apple MLX download if nothing
    local exists yet.
    """
    wanted = str(settings.get("device") or "auto").strip() or "auto"
    compute = str(settings.get("compute_type") or "default").strip() or "default"
    model_name = str(settings.get("model") or "").strip()

    def with_compute(device: str) -> tuple[str, str]:
        if compute != "default":
            return device, compute
        if device == "cpu":
            return device, "int8"
        # CUDA and MLX prefer float16-class math.
        return device, "float16"

    if wanted == "cpu":
        return with_compute("cpu")
    if wanted == "cuda":
        if cuda_available():
            return with_compute("cuda")
        # Hardware-agnostic: fall through instead of crashing on a Mac/CPU box.
        wanted = "auto"
    if wanted == "auto":
        if cuda_available():
            return with_compute("cuda")
        mlx_ok = mlx_available()
        mlx_ready = bool(model_name) and mlx_ok and _mlx_speech_ready(model_name)
        ct2_ready = bool(model_name) and _ct2_speech_ready(model_name)
        # Prefer an already-local backend over a multi-GB first-time MLX download.
        if mlx_ready:
            return with_compute("mlx")
        if ct2_ready:
            return with_compute("cpu")
        if mlx_ok and mlx_repo_for(model_name):
            return with_compute("mlx")
        return with_compute("cpu")
    # Unknown explicit value — stay safe.
    return with_compute("cpu")


def speakers_ready() -> bool:
    return SEGMENTATION_MODEL.is_file() and EMBEDDING_MODEL.is_file()


def speech_can_download(name: str) -> bool:
    if name in _MODELS:
        return True
    return mlx_repo_for(name) is not None and mlx_available()


def ensure_speech_model(name: str) -> None:
    settings = dict(load_settings())
    settings["model"] = name
    device, _ = resolve_device(settings)
    if device == "mlx":
        _ensure_mlx_speech_model(name)
        return
    _ensure_cached_speech_model(name)


def speech_ready(name: str) -> bool:
    # Ready if either local backend can run it (CPU/CT2 or Apple GPU/MLX).
    if _ct2_speech_ready(name):
        return True
    return mlx_available() and _mlx_speech_ready(name)


def _ct2_speech_ready(name: str) -> bool:
    folder = Path(name)
    if folder.is_dir() and (folder / "model.bin").is_file():
        return True
    repo = _MODELS.get(name)
    if not repo:
        return False
    cached = try_to_load_from_cache(
        repo_id=repo,
        filename="model.bin",
        cache_dir=str(WHISPER_DIR),
    )
    return isinstance(cached, str)


def _mlx_speech_ready(name: str) -> bool:
    repo = mlx_repo_for(name)
    if not repo:
        return False
    # mlx-whisper uses the default Hugging Face cache, not WHISPER_DIR.
    for filename in ("weights.npz", "model.safetensors", "model.safetensors.index.json"):
        cached = try_to_load_from_cache(repo_id=repo, filename=filename)
        if isinstance(cached, str):
            return True
    return False


def _ensure_mlx_speech_model(name: str) -> None:
    repo = mlx_repo_for(name)
    if not repo:
        raise RuntimeError(f"No Apple GPU model mapping for {name}.")
    if _mlx_speech_ready(name):
        return
    activity.begin("download", f"Downloading {name} (Apple GPU)")
    snapshot_download(
        repo_id=repo,
        token=_hf_token(),
        tqdm_class=_HubProgress,
    )


def transcribe_file(path: Path, settings: dict, num_speakers: int) -> dict:
    activity.begin("transcribe", "Transcribing")
    audio = load_mono_f32(path, 16000)
    if audio.size == 0:
        raise RuntimeError("The recording was empty.")

    try:
        ensure_diarization_models()
    except Exception:
        # Speaker files are optional. The transcript still returns without them.
        pass

    requested = settings.get("language") or "en"
    resolved = dict(settings)
    resolved["model"] = model_for_language(settings["model"], requested)
    device, compute = resolve_device(resolved)
    activity.begin("transcribe", "Transcribing")
    if device == "mlx":
        segments, detected = _transcribe_mlx(path, resolved, requested)
    else:
        segments, detected = _transcribe_ct2(path, resolved, requested, device, compute)

    diarization_error = None
    spans: list[SpeakerSpan] = []
    # Keep the audio even when Whisper finds nothing — empty turns still save.
    if segments:
        try:
            spans = _diarize(audio, num_speakers, settings["cluster_threshold"])
        except Exception as exc:
            diarization_error = str(exc)

    turns = assign_speakers(segments, spans)
    text = "\n".join(turn["text"] for turn in turns)
    return {
        "turns": turns,
        "text": text,
        "duration": round(float(audio.shape[0]) / 16000.0, 2),
        "model": resolved["model"],
        "device": device,
        "compute_type": compute,
        "language": requested,
        "detected_language": detected or requested,
        "diarization_error": diarization_error,
    }


def _transcribe_ct2(
    path: Path,
    settings: dict,
    requested: str,
    device: str,
    compute: str,
) -> tuple[list[TimedText], str | None]:
    model, _, _ = _get_whisper(settings, device=device, compute=compute)
    segments_iter, info = model.transcribe(
        str(path),
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


def _transcribe_mlx(
    path: Path,
    settings: dict,
    requested: str,
) -> tuple[list[TimedText], str | None]:
    import mlx_whisper

    name = settings["model"]
    repo = mlx_repo_for(name)
    if not repo:
        raise RuntimeError(f"No Apple GPU model mapping for {name}.")
    ensure_speech_model(name)
    result = mlx_whisper.transcribe(
        str(path),
        path_or_hf_repo=repo,
        language=None if requested == "auto" else requested,
        word_timestamps=False,
        verbose=False,
    )
    segments = []
    for row in result.get("segments") or []:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            TimedText(
                start=float(row.get("start") or 0),
                end=float(row.get("end") or 0),
                text=text,
            )
        )
    detected = result.get("language")
    return segments, str(detected) if detected else None


def load_mono_f32(path: Path, sample_rate: int) -> np.ndarray:
    container = av.open(str(path))
    try:
        if not container.streams.audio:
            raise RuntimeError("That file has no audio track.")
        stream = container.streams.audio[0]
        resampler = av.audio.resampler.AudioResampler(
            format="flt",
            layout="mono",
            rate=sample_rate,
        )
        chunks: list[np.ndarray] = []
        for frame in container.decode(stream):
            _collect_audio(resampler.resample(frame), chunks)
        _collect_audio(resampler.resample(None), chunks)
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)
    finally:
        container.close()


def _collect_audio(resampled, chunks: list[np.ndarray]) -> None:
    if resampled is None:
        return
    frames = resampled if isinstance(resampled, list) else [resampled]
    for frame in frames:
        if frame is None:
            continue
        chunks.append(np.asarray(frame.to_ndarray(), dtype=np.float32).reshape(-1))


def _get_whisper(
    settings: dict,
    device: str | None = None,
    compute: str | None = None,
) -> tuple[WhisperModel, str, str]:
    global _whisper, _whisper_key
    if device is None or compute is None:
        device, compute = resolve_device(settings)
    if device == "mlx":
        raise RuntimeError("Apple GPU uses MLX, not the CUDA/CPU Whisper loader.")
    key = (settings["model"], device, compute, settings["cpu_threads"])
    with _whisper_lock:
        if _whisper is not None and _whisper_key == key:
            return _whisper, device, compute
        name = settings["model"]
        if not _ct2_speech_ready(name):
            raise RuntimeError(
                f"{name} is not installed on this computer. "
                "Install it when prompted, or choose an installed model in Settings."
            )
        try:
            model = WhisperModel(
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
            message = str(exc)
            if device == "cuda":
                raise RuntimeError(
                    "CUDA is not available on this computer. "
                    "Choose auto or cpu in Settings."
                ) from exc
            raise RuntimeError(
                f"Could not load model {name}. {message}"
            ) from exc
        _whisper = model
        _whisper_key = key
        return model, device, compute


def _diarize(audio: np.ndarray, num_speakers: int, threshold: float) -> list[SpeakerSpan]:
    clusters = num_speakers if num_speakers > 0 else -1
    diarizer = _get_diarizer(clusters, threshold)
    if audio.shape[0] < diarizer.sample_rate // 2:
        return []
    result = diarizer.process(np.ascontiguousarray(audio, dtype=np.float32))
    spans = []
    for row in result.sort_by_start_time():
        spans.append(
            SpeakerSpan(start=float(row.start), end=float(row.end), speaker=int(row.speaker))
        )
    return spans


def _get_diarizer(num_clusters: int, threshold: float):
    ensure_diarization_models()
    key = (num_clusters, round(float(threshold), 3))
    with _diarizer_lock:
        cached = _diarizers.get(key)
        if cached is not None:
            return cached
        if len(_diarizers) > 6:
            _diarizers.clear()
        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(SEGMENTATION_MODEL),
                    window_shift_ratio=0.1,
                ),
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(EMBEDDING_MODEL),
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=num_clusters,
                threshold=float(threshold),
            ),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not config.validate():
            raise RuntimeError(
                "Speaker model files are missing or unreadable in the models folder."
            )
        diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
        _diarizers[key] = diarizer
        return diarizer


def ensure_diarization_models() -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    if not SEGMENTATION_MODEL.is_file():
        archive = MODELS / "segmentation.tar.bz2"
        _download(SEGMENTATION_URL, archive, "Speaker segmentation")
        _extract_archive(archive, MODELS)
        archive.unlink(missing_ok=True)
    if not SEGMENTATION_MODEL.is_file():
        raise RuntimeError("The speaker segmentation model did not unpack correctly.")
    if not EMBEDDING_MODEL.is_file():
        _download(EMBEDDING_URL, EMBEDDING_MODEL, "Speaker voices")


def _ensure_cached_speech_model(name: str) -> None:
    if speech_ready(name):
        return
    repo = _MODELS.get(name)
    if repo is None:
        return
    activity.begin("download", f"Speech model {name}")
    cache_root = _hub_repo_cache_dir(repo)
    # Lock the denominator before HF discovers files one-by-one (that made the
    # bar jump from ~40% down to ~0% when model.bin was added to the total).
    expected = _speech_download_total(repo)
    if expected > 0:
        activity.note_at_least(_directory_bytes(cache_root), expected)
    # Xet keeps *.incomplete at 0 bytes until the end, so the UI freezes after the
    # first total. Plain HTTP streams into the file and progress can move.
    previous_xet = hf_constants.HF_HUB_DISABLE_XET
    hf_constants.HF_HUB_DISABLE_XET = True
    try:
        with _DiskProgress(cache_root):
            snapshot_download(
                repo,
                cache_dir=str(WHISPER_DIR),
                allow_patterns=_WHISPER_FILES,
                tqdm_class=_HubProgress,
                token=_hf_token(),
            )
    finally:
        hf_constants.HF_HUB_DISABLE_XET = previous_xet


def _download(url: str, dest: Path, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "auto-asr"})
    print(f"Downloading {label} …", flush=True)
    activity.begin("download", label)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            total = int(response.headers.get("Content-Length") or 0)
            received = 0
            with temporary.open("wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    received += len(chunk)
                    activity.note(received, total)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Could not download {url}. {exc}") from exc
    temporary.replace(dest)


def _extract_archive(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, "r:bz2") as bundle:
        for member in bundle.getmembers():
            target = (dest / member.name).resolve()
            if not _is_inside(dest.resolve(), target):
                raise RuntimeError("The model archive contained an unsafe path.")
        bundle.extractall(dest)


def _is_inside(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True
