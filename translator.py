"""Offline translation. Language files download once into this project."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import activity

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("XDG_DATA_HOME", str(ROOT / "models"))

import argostranslate.package
import argostranslate.settings
import argostranslate.translate

_index_ready = False


def fill_translations(turns: list[dict], source: str, target: str) -> list[dict]:
    if not target or target == source or source in ("", "auto"):
        return [_with_translation(turn, "") for turn in turns]
    translated = [translate_text(turn.get("text") or "", source, target) for turn in turns]
    return [_with_translation(turn, text) for turn, text in zip(turns, translated)]


def translate_text(text: str, source: str, target: str) -> str:
    cleaned = " ".join(str(text).split())
    if not cleaned or source == target:
        return ""
    _ensure_route(source, target)
    if _direct(source, target):
        return argostranslate.translate.translate(cleaned, source, target)
    if source != "en" and target != "en":
        midpoint = argostranslate.translate.translate(cleaned, source, "en")
        return argostranslate.translate.translate(midpoint, "en", target)
    raise RuntimeError(f"No offline translation from {source} to {target}.")


def _with_translation(turn: dict, translation: str) -> dict:
    updated = dict(turn)
    updated["translation"] = translation
    return updated


def _ensure_route(source: str, target: str) -> None:
    if _direct(source, target):
        return
    if source != "en" and target != "en":
        _ensure_direct(source, "en")
        _ensure_direct("en", target)
        return
    _ensure_direct(source, target)


def installed_pairs() -> list[str]:
    return pairs_in(ROOT / "models" / "argos-translate" / "packages")


def ensure_route(source: str, target: str) -> None:
    _ensure_route(source, target)


def pairs_in(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    found = []
    for meta_path in sorted(root.glob("*/metadata.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        source = str(meta.get("from_code") or "")
        target = str(meta.get("to_code") or "")
        if source and target:
            found.append(f"{source}:{target}")
    return found


def _ensure_direct(source: str, target: str) -> None:
    if _direct(source, target):
        return
    package = _find_package(source, target)
    if package is None:
        raise RuntimeError(f"No offline translation from {source} to {target}.")
    label = f"{package.from_name} → {package.to_name}"
    print(f"Downloading translation {label} …", flush=True)
    _install_package(package, label)


def _install_package(package, label: str) -> None:
    # package.download() reads the whole file into memory and reports no progress.
    if not argostranslate.settings.stanza_available:
        activity.begin("download", label)
        argostranslate.package.install_from_path(package.download())
        return
    filename = argostranslate.package.argospm_package_name(package) + ".argosmodel"
    dest = argostranslate.settings.downloads_dir / filename
    if not dest.exists():
        activity.begin("download", label)
        if not _stream_links(package.links, dest):
            raise RuntimeError(f"Could not download translation {label}.")
    argostranslate.package.install_from_path(dest)
    dest.unlink(missing_ok=True)


def _stream_links(links: list, dest: Path) -> bool:
    for link in links:
        if _stream_url(str(link), dest):
            return True
    return False


def _stream_url(url: str, dest: Path) -> bool:
    temporary = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "auto-asr"})
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except Exception:
        return False
    received = 0
    try:
        total = int(response.headers.get("Content-Length") or 0)
        with temporary.open("wb") as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                activity.note(received, total)
    except Exception:
        temporary.unlink(missing_ok=True)
        return False
    finally:
        response.close()
    if received == 0:
        temporary.unlink(missing_ok=True)
        return False
    temporary.replace(dest)
    return True


def _direct(source: str, target: str) -> bool:
    for installed in argostranslate.translate.get_installed_languages():
        if installed.code != source:
            continue
        if any(translation.to_lang.code == target for translation in installed.translations_from):
            return True
    return False


def _find_package(source: str, target: str):
    global _index_ready
    if not _index_ready:
        argostranslate.package.update_package_index()
        _index_ready = True
    for package in argostranslate.package.get_available_packages():
        if package.from_code == source and package.to_code == target:
            return package
    return None
