# Download Progress + Install Consent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make speech-model install progress update from disk growth, and stop silent Hub downloads when the user declines Install.

**Architecture:** Keep `/api/activity` as the UI source of truth. During `snapshot_download`, a 0.5s ticker measures the model cache folder and calls `activity.note` with `max(tqdm, disk)`. Transcription loads Whisper only when already on disk (`local_files_only=True`).

**Tech Stack:** Python 3, FastAPI, huggingface_hub, faster-whisper, vanilla JS

## Global Constraints

- No speed/ETA UI chrome
- Speech downloads only via `/api/install`
- Do not invent a total from disk if HF never reported one
- Skip git commits unless the user asks (repo has no history yet)

---

### Task 1: Activity max-note helper

**Files:**
- Modify: `activity.py`
- Test: `tests/test_activity.py`

**Interfaces:**
- Produces: `note_at_least(received: int, total: int) -> None` — never decreases `received`; keeps existing `total` when new `total` is 0

- [ ] Add failing tests for max semantics
- [ ] Implement `note_at_least`
- [ ] Run `tests/test_activity.py`

### Task 2: Disk ticker + consent in pipeline

**Files:**
- Modify: `pipeline.py`
- Test: `tests/test_downloads.py`

**Interfaces:**
- Consumes: `activity.note_at_least`, `activity.begin`
- Produces: `_ensure_cached_speech_model` starts/stops disk watcher; `_get_whisper` errors if not `speech_ready`, uses `local_files_only=True`

- [ ] Add tests for cache byte counting + no auto-download path
- [ ] Implement cache sizing + ticker around `snapshot_download`
- [ ] Remove auto-download from `_get_whisper`
- [ ] Run download/activity tests

### Task 3: Frontend label

**Files:**
- Modify: `static/app.js` (`paintActivity`)
- Modify: `static/index.html` cache-bust `?v=` on app.js if present

- [ ] Label when total known: `{label} · {percent}% · {received} / {total}`
- [ ] Indeterminate path unchanged

### Task 4: Verify

- [ ] Run full `tests/` suite
