"""Local speech settings. The page reads and writes these."""

from __future__ import annotations

import json
from pathlib import Path

from languages import normalize_spoken, normalize_translation

ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT / "settings.json"

PRESET_MODELS = [
    "tiny.en",
    "base.en",
    "small.en",
    "medium.en",
    "distil-large-v3",
    "large-v3",
]

DEVICES = ["auto", "cpu", "cuda"]
COMPUTE_TYPES = ["int8", "int8_float16", "float16", "float32", "default"]

DEFAULTS = {
    "model": "small.en",
    "device": "auto",
    "compute_type": "default",
    "cpu_threads": 4,
    "cluster_threshold": 0.5,
    "language": "en",
    "translate_to": "fr",
}


def load_settings() -> dict:
    stored: dict = {}
    if SETTINGS_PATH.exists():
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            stored = raw
    merged = dict(DEFAULTS)
    merged.update({key: stored[key] for key in DEFAULTS if key in stored})
    return normalize(merged)


def save_settings(raw: dict) -> dict:
    settings = normalize(raw)
    SETTINGS_PATH.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )
    return settings


def normalize(raw: dict) -> dict:
    model = str(raw.get("model", DEFAULTS["model"])).strip()
    if not model or len(model) > 300:
        raise ValueError("Enter a model name or a path to a local model folder.")

    device = str(raw.get("device", DEFAULTS["device"])).strip()
    if device not in DEVICES:
        raise ValueError("Device must be auto, cpu, or cuda.")

    compute_type = str(raw.get("compute_type", DEFAULTS["compute_type"])).strip()
    if compute_type not in COMPUTE_TYPES:
        raise ValueError("Choose a compute type from the list.")

    try:
        threads = int(raw.get("cpu_threads", DEFAULTS["cpu_threads"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("Thread count must be a whole number.") from exc
    if threads < 1 or threads > 16:
        raise ValueError("Thread count must be from 1 to 16.")

    try:
        threshold = float(raw.get("cluster_threshold", DEFAULTS["cluster_threshold"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("Speaker threshold must be a number.") from exc
    if threshold < 0.1 or threshold > 1.0:
        raise ValueError("Speaker threshold must be from 0.1 to 1.0.")

    return {
        "model": model,
        "device": device,
        "compute_type": compute_type,
        "cpu_threads": threads,
        "cluster_threshold": round(threshold, 3),
        "language": normalize_spoken(raw.get("language", DEFAULTS["language"])),
        "translate_to": normalize_translation(raw.get("translate_to", DEFAULTS["translate_to"])),
    }
